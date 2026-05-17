from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kero.config import KeroConfig
from kero.memory.retrieval import compact_lines, utc_now
from kero.memory.store import CuratedMemoryStore, LongTermMemoryStore, MemoryEntry, ProfileStore, atomic_write_text, file_lock


@dataclass(frozen=True)
class TurnRecord:
    user: str
    assistant: str
    created_at: str


@dataclass(frozen=True)
class RecalledMemory:
    id: str
    text: str
    kind: str
    source: str
    score: float
    created_at: str


@dataclass(frozen=True)
class MemoryContext:
    profile: dict[str, Any]
    memory_snapshot: str
    user_snapshot: str
    recalled_memories: list[RecalledMemory]
    recent_turns: list[TurnRecord]

    def render_for_prompt(self) -> str:
        sections: list[str] = []
        if self.user_snapshot:
            sections.append(self.user_snapshot)
        if self.memory_snapshot:
            sections.append(self.memory_snapshot)
        if self.profile:
            profile_lines: list[str] = []
            for key in (
                "user_name",
                "emotional_baseline",
                "companion_strategy",
            ):
                value = self.profile.get(key)
                if value:
                    profile_lines.append(f"- {key}: {value}")
            for key in ("preferences", "communication_style", "topics", "facts"):
                values = self.profile.get(key) or []
                if values:
                    profile_lines.append(f"- {key}: " + "; ".join(str(item) for item in values[:8]))
            if profile_lines:
                sections.append("## STRUCTURED USER PROFILE\n" + "\n".join(profile_lines))
        return "\n\n".join(sections)

    def render_recall_block(self) -> str:
        if not self.recalled_memories:
            return ""
        lines = [
            "[System note: The following is recalled memory context, not new user input.]",
            "",
        ]
        lines.extend(
            f"- ({item.kind}, score={item.score:.2f}) {item.text}"
            for item in self.recalled_memories
        )
        return "<memory-context>\n" + "\n".join(lines) + "\n</memory-context>"


class SessionLog:
    def __init__(self, path: Path):
        self.path = path

    def append(self, record: TurnRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"user": record.user, "assistant": record.assistant, "created_at": record.created_at},
            ensure_ascii=False,
        )
        with file_lock(self.path):
            existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
            atomic_write_text(self.path, existing + line + "\n")

    def all(self) -> list[TurnRecord]:
        if not self.path.exists():
            return []
        turns: list[TurnRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                turns.append(
                    TurnRecord(
                        user=str(data.get("user") or ""),
                        assistant=str(data.get("assistant") or ""),
                        created_at=str(data.get("created_at") or ""),
                    )
                )
            except json.JSONDecodeError:
                continue
        return turns


class MemoryManager:
    """Kero's memory facade.

    The shape intentionally mirrors Hermes' split:
    - curated memory: small bounded MEMORY.md / USER.md injected every turn;
    - long-term memory: searchable JSONL facts and reflections;
    - session log: full local transcript for reflection and lightweight recall.
    """

    def __init__(self, config: KeroConfig):
        self.config = config
        self.home = config.home
        self.curated = CuratedMemoryStore(
            self.home,
            memory_char_limit=config.memory.memory_char_limit,
            user_char_limit=config.memory.user_char_limit,
        )
        self.long_term = LongTermMemoryStore(
            self.home / "memory" / "long_term.jsonl",
            char_limit=config.memory.long_term_char_limit,
        )
        self.profile_store = ProfileStore(self.home / "profile" / "profile.json")
        self.session_log = SessionLog(self.home / "sessions" / "current.jsonl")
        self.short_term: list[TurnRecord] = []
        self.turns_since_reflection = 0

        self.curated.load()
        self.profile_store.load()
        self.short_term = self.session_log.all()[-self.config.memory.short_term_turns :]

    def build_context(self, query: str) -> MemoryContext:
        recalled = [
            RecalledMemory(
                id=entry.id,
                text=entry.text,
                kind=entry.kind,
                source=entry.source,
                score=score,
                created_at=entry.created_at,
            )
            for entry, score in self.long_term.search(
                query,
                top_k=self.config.memory.recall_top_k,
                min_score=self.config.memory.recall_min_score,
            )
        ]
        return MemoryContext(
            profile=self.profile_store.snapshot(),
            memory_snapshot=self.curated.format_snapshot("memory"),
            user_snapshot=self.curated.format_snapshot("user"),
            recalled_memories=recalled,
            recent_turns=list(self.short_term),
        )

    def record_turn(self, user: str, assistant: str) -> TurnRecord:
        record = TurnRecord(user=user, assistant=assistant, created_at=utc_now())
        self.short_term.append(record)
        self.short_term = self.short_term[-self.config.memory.short_term_turns :]
        self.session_log.append(record)
        self.turns_since_reflection += 1
        return record

    def remember(
        self,
        text: str,
        *,
        target: str = "memory",
        kind: str = "fact",
        source: str = "manual",
        importance: float = 0.7,
    ) -> dict[str, Any]:
        curated_result = self.curated.add("user" if target == "user" else "memory", text)
        entry = None
        if curated_result.get("success"):
            entry = self.long_term.add(
                text,
                kind=kind,
                source=source,
                importance=importance,
                tags=[target],
            )
        result = dict(curated_result)
        if entry:
            result["long_term_id"] = entry.id
        return result

    def forget(self, substring: str) -> dict[str, Any]:
        removed_memory = self.curated.remove("memory", substring)
        removed_user = self.curated.remove("user", substring)
        removed_long = self.long_term.remove(substring)
        return {
            "memory": removed_memory,
            "user": removed_user,
            "long_term_removed": removed_long,
        }

    def merge_profile(self, update: dict[str, Any]) -> None:
        self.profile_store.merge(update)
        self._mirror_profile_to_curated(update)

    def add_long_term(
        self,
        text: str,
        *,
        kind: str = "fact",
        source: str = "reflection",
        importance: float = 0.6,
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        return self.long_term.add(
            text,
            kind=kind,
            source=source,
            importance=importance,
            tags=tags or [],
        )

    def recent_transcript(self, limit_chars: int = 6000) -> str:
        lines: list[str] = []
        for turn in self.short_term:
            lines.append(f"User: {turn.user}")
            lines.append(f"Kero: {turn.assistant}")
        return "\n".join(compact_lines(lines, limit_chars))

    def clear_session(self) -> None:
        self.short_term = []

    def mark_reflected(self) -> None:
        self.turns_since_reflection = 0

    def status(self) -> dict[str, Any]:
        memory_path = self.home / "memories" / "MEMORY.md"
        user_path = self.home / "memories" / "USER.md"
        long_term_path = self.home / "memory" / "long_term.jsonl"
        profile_path = self.home / "profile" / "profile.json"
        session_path = self.home / "sessions" / "current.jsonl"
        paths = {
            "MEMORY.md": memory_path,
            "USER.md": user_path,
            "long_term.jsonl": long_term_path,
            "profile.json": profile_path,
            "current.jsonl": session_path,
        }
        return {
            name: {
                "path": str(path),
                "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() else 0,
            }
            for name, path in paths.items()
        }

    def _mirror_profile_to_curated(self, update: dict[str, Any]) -> None:
        user_name = str(update.get("user_name") or "").strip()
        if user_name:
            self.curated.add("user", f"User name: {user_name}")

        for key, prefix in (
            ("preferences", "User preference"),
            ("communication_style", "Communication style"),
            ("facts", "User fact"),
        ):
            values = update.get(key) or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                value = str(value).strip()
                if value:
                    self.curated.add("user", f"{prefix}: {value}")

        strategy = str(update.get("companion_strategy") or "").strip()
        if strategy:
            self.curated.add("memory", f"Companion strategy: {strategy}")
