from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kero.config import KeroConfig
from kero.llm import LLMClient, LLMError
from kero.memory import MemoryManager
from kero.memory.retrieval import utc_now
from kero.memory.store import atomic_write_text, file_lock


@dataclass
class ReflectionResult:
    trigger: str
    summary: str
    profile_update: dict[str, Any] = field(default_factory=dict)
    durable_memories: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    used_fallback: bool = False


class ReflectionEngine:
    def __init__(self, config: KeroConfig, memory: MemoryManager, llm: LLMClient):
        self.config = config
        self.memory = memory
        self.llm = llm
        self.path = config.home / "reflections" / "reflections.jsonl"

    def maybe_reflect(self, trigger: str = "interval") -> ReflectionResult | None:
        if self.memory.turns_since_reflection < self.config.memory.reflection_interval_turns:
            return None
        if len(self.memory.short_term) < self.config.memory.reflection_min_turns:
            return None
        return self.reflect(trigger=trigger)

    def reflect(self, trigger: str = "manual") -> ReflectionResult | None:
        if not self.memory.short_term:
            return None
        transcript = self.memory.recent_transcript()
        result = self._reflect_with_llm(trigger, transcript)
        if result is None:
            result = self._reflect_with_rules(trigger, transcript)
        self._apply(result)
        self.memory.mark_reflected()
        return result

    def _reflect_with_llm(self, trigger: str, transcript: str) -> ReflectionResult | None:
        if not self.llm.is_configured():
            return None
        system = (
            "You are Kero's memory reflection module. Extract only stable, useful "
            "companion memory from a recent conversation. Return strict JSON. "
            "Do not include transient task progress, raw secrets, or one-off chatter."
        )
        user = (
            "Recent transcript:\n"
            f"{transcript}\n\n"
            "Return JSON with this schema:\n"
            "{\n"
            '  "summary": "one short session summary",\n'
            '  "profile_update": {\n'
            '    "user_name": "",\n'
            '    "facts": [],\n'
            '    "preferences": [],\n'
            '    "communication_style": [],\n'
            '    "emotional_baseline": "",\n'
            '    "companion_strategy": "",\n'
            '    "topics": []\n'
            "  },\n"
            '  "durable_memories": []\n'
            "}"
        )
        try:
            response = self.llm.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                purpose="reflection",
            )
        except LLMError:
            return None
        data = _extract_json_object(response.content)
        if not data:
            return None
        summary = str(data.get("summary") or "").strip()
        profile_update = data.get("profile_update") if isinstance(data.get("profile_update"), dict) else {}
        durable = data.get("durable_memories") or []
        if isinstance(durable, str):
            durable = [durable]
        durable = [str(item).strip() for item in durable if str(item).strip()]
        return ReflectionResult(
            trigger=trigger,
            summary=summary or "Conversation reflected.",
            profile_update=profile_update,
            durable_memories=durable,
            used_fallback=False,
        )

    def _reflect_with_rules(self, trigger: str, transcript: str) -> ReflectionResult:
        profile_update: dict[str, Any] = {
            "facts": [],
            "preferences": [],
            "communication_style": [],
            "topics": [],
        }
        durable: list[str] = []

        user_lines = [turn.user for turn in self.memory.short_term]
        joined = "\n".join(user_lines)
        name_match = re.search(r"(?:我叫|叫我|我的名字是)\s*([\u4e00-\u9fffA-Za-z0-9_\-]{1,24})", joined)
        if name_match:
            profile_update["user_name"] = name_match.group(1)
            durable.append(f"User name: {name_match.group(1)}")

        for pattern, bucket, prefix in (
            (r"(?:我喜欢|喜欢)\s*([^。！？\n]{2,80})", "preferences", "User likes"),
            (r"(?:我不喜欢|讨厌)\s*([^。！？\n]{2,80})", "preferences", "User dislikes"),
            (r"(?:请记住|记住|别忘了)\s*[:：]?\s*([^。！？\n]{2,120})", "facts", "User asked Kero to remember"),
            (r"(?:以后你|之后你)\s*([^。！？\n]{2,120})", "communication_style", "User wants Kero to"),
        ):
            for match in re.finditer(pattern, joined, re.IGNORECASE):
                value = match.group(1).strip()
                item = f"{prefix}: {value}"
                if value not in profile_update[bucket]:
                    profile_update[bucket].append(value)
                durable.append(item)

        if any(word in joined for word in ("焦虑", "压力", "难过", "失眠", "累")):
            profile_update["emotional_baseline"] = "User may be under stress; respond with calm, grounded companionship."
            profile_update["companion_strategy"] = "Use gentle validation, help split problems into small next steps, and avoid rushing."
        elif any(word in joined for word in ("开心", "顺利", "期待", "喜欢")):
            profile_update["companion_strategy"] = "Invite the user to savor positive moments and ask warm follow-up questions."

        summary = "Captured stable preferences and companion cues from the recent conversation."
        if not durable and not any(profile_update.values()):
            summary = "No durable memory found; kept the session as transient context."
        return ReflectionResult(
            trigger=trigger,
            summary=summary,
            profile_update=profile_update,
            durable_memories=list(dict.fromkeys(durable))[:8],
            used_fallback=True,
        )

    def _apply(self, result: ReflectionResult) -> None:
        if result.profile_update:
            self.memory.merge_profile(result.profile_update)
        if result.summary:
            self.memory.add_long_term(
                result.summary,
                kind="reflection",
                source=f"reflection:{result.trigger}",
                importance=0.55,
                tags=["reflection"],
            )
        for item in result.durable_memories:
            self.memory.add_long_term(
                item,
                kind="fact",
                source=f"reflection:{result.trigger}",
                importance=0.75,
                tags=["extracted"],
            )
        self._append(result)

    def _append(self, result: ReflectionResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(result), ensure_ascii=False)
        with file_lock(self.path):
            existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
            atomic_write_text(self.path, existing + line + "\n")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
