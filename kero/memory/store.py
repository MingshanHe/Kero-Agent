from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kero.memory.retrieval import best_score, utc_now
from kero.memory.safety import scan_memory_content

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback path
    fcntl = None


ENTRY_DELIMITER = "\n§\n"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".kero_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@contextmanager
def file_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


@dataclass
class MemoryEntry:
    text: str
    kind: str = "fact"
    source: str = "manual"
    importance: float = 0.5
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            text=str(data.get("text") or data.get("content") or "").strip(),
            kind=str(data.get("kind") or "fact"),
            source=str(data.get("source") or "manual"),
            importance=float(data.get("importance", 0.5)),
            tags=[str(item) for item in data.get("tags", []) if str(item).strip()],
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or data.get("created_at") or utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["importance"] = max(0.0, min(1.0, float(data["importance"])))
        return data


class CuratedMemoryStore:
    """Hermes-inspired bounded MEMORY.md / USER.md store.

    The store keeps a frozen snapshot captured at session load. Writes are
    durable immediately, but callers can keep using the snapshot to preserve a
    stable prompt for the active session, just like Hermes does.
    """

    def __init__(self, home: Path, memory_char_limit: int, user_char_limit: int):
        self.home = home
        self.memory_dir = home / "memories"
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self.memory_entries: list[str] = []
        self.user_entries: list[str] = []
        self._snapshot: dict[str, str] = {"memory": "", "user": ""}

    def load(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._path_for("memory").touch(exist_ok=True)
        self._path_for("user").touch(exist_ok=True)
        self.memory_entries = list(dict.fromkeys(self._read_file(self._path_for("memory"))))
        self.user_entries = list(dict.fromkeys(self._read_file(self._path_for("user"))))
        self._snapshot = {
            "memory": self._render_block("memory", self.memory_entries),
            "user": self._render_block("user", self.user_entries),
        }

    def add(self, target: str, content: str) -> dict[str, Any]:
        target = self._normalize_target(target)
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}
        error = scan_memory_content(content)
        if error:
            return {"success": False, "error": error}

        with file_lock(self._path_for(target)):
            self._reload_target(target)
            entries = self._entries_for(target)
            if content in entries:
                return self._success(target, "Entry already exists.")
            test_entries = entries + [content]
            if len(ENTRY_DELIMITER.join(test_entries)) > self._limit_for(target):
                return {
                    "success": False,
                    "error": (
                        f"{target} memory would exceed "
                        f"{self._limit_for(target)} chars. Replace or forget first."
                    ),
                }
            entries.append(content)
            self._write_target(target)
        return self._success(target, "Entry added.")

    def replace(self, target: str, old_text: str, content: str) -> dict[str, Any]:
        target = self._normalize_target(target)
        old_text = old_text.strip()
        content = content.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}
        if not content:
            return {"success": False, "error": "content cannot be empty."}
        error = scan_memory_content(content)
        if error:
            return {"success": False, "error": error}

        with file_lock(self._path_for(target)):
            self._reload_target(target)
            entries = self._entries_for(target)
            matches = [(idx, entry) for idx, entry in enumerate(entries) if old_text in entry]
            if not matches:
                return {"success": False, "error": f"No entry matched '{old_text}'."}
            unique = {entry for _, entry in matches}
            if len(unique) > 1:
                return {
                    "success": False,
                    "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                    "matches": [entry[:100] for _, entry in matches],
                }
            idx = matches[0][0]
            test_entries = entries.copy()
            test_entries[idx] = content
            if len(ENTRY_DELIMITER.join(test_entries)) > self._limit_for(target):
                return {"success": False, "error": "Replacement would exceed memory limit."}
            entries[idx] = content
            self._write_target(target)
        return self._success(target, "Entry replaced.")

    def remove(self, target: str, old_text: str) -> dict[str, Any]:
        target = self._normalize_target(target)
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}

        with file_lock(self._path_for(target)):
            self._reload_target(target)
            entries = self._entries_for(target)
            matches = [(idx, entry) for idx, entry in enumerate(entries) if old_text in entry]
            if not matches:
                return {"success": False, "error": f"No entry matched '{old_text}'."}
            unique = {entry for _, entry in matches}
            if len(unique) > 1:
                return {
                    "success": False,
                    "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                    "matches": [entry[:100] for _, entry in matches],
                }
            entries.pop(matches[0][0])
            self._write_target(target)
        return self._success(target, "Entry removed.")

    def format_snapshot(self, target: str) -> str:
        return self._snapshot.get(self._normalize_target(target), "")

    def live_entries(self, target: str) -> list[str]:
        return list(self._entries_for(self._normalize_target(target)))

    def _path_for(self, target: str) -> Path:
        return self.memory_dir / ("USER.md" if target == "user" else "MEMORY.md")

    def _reload_target(self, target: str) -> None:
        self._set_entries(target, list(dict.fromkeys(self._read_file(self._path_for(target)))))

    def _write_target(self, target: str) -> None:
        atomic_write_text(self._path_for(target), ENTRY_DELIMITER.join(self._entries_for(target)))

    def _entries_for(self, target: str) -> list[str]:
        return self.user_entries if target == "user" else self.memory_entries

    def _set_entries(self, target: str, entries: list[str]) -> None:
        if target == "user":
            self.user_entries = entries
        else:
            self.memory_entries = entries

    def _limit_for(self, target: str) -> int:
        return self.user_char_limit if target == "user" else self.memory_char_limit

    def _success(self, target: str, message: str) -> dict[str, Any]:
        entries = self._entries_for(target)
        used = len(ENTRY_DELIMITER.join(entries))
        limit = self._limit_for(target)
        return {
            "success": True,
            "target": target,
            "message": message,
            "entries": entries,
            "entry_count": len(entries),
            "usage": f"{used}/{limit} chars",
        }

    def _render_block(self, target: str, entries: list[str]) -> str:
        if not entries:
            return ""
        header = "USER PROFILE" if target == "user" else "KERO MEMORY"
        used = len(ENTRY_DELIMITER.join(entries))
        return f"## {header} [{used}/{self._limit_for(target)} chars]\n" + "\n".join(
            f"- {entry}" for entry in entries
        )

    @staticmethod
    def _read_file(path: Path) -> list[str]:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        return [entry.strip() for entry in raw.split(ENTRY_DELIMITER) if entry.strip()]

    @staticmethod
    def _normalize_target(target: str) -> str:
        if target not in {"memory", "user"}:
            raise ValueError("target must be 'memory' or 'user'")
        return target


class LongTermMemoryStore:
    """Append-friendly JSONL memory with lightweight local retrieval."""

    def __init__(self, path: Path, char_limit: int):
        self.path = path
        self.char_limit = char_limit

    def add(
        self,
        text: str,
        *,
        kind: str = "fact",
        source: str = "manual",
        importance: float = 0.5,
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        text = text.strip()
        if not text:
            raise ValueError("memory text cannot be empty")
        error = scan_memory_content(text)
        if error:
            raise ValueError(error)

        entry = MemoryEntry(
            text=text,
            kind=kind,
            source=source,
            importance=importance,
            tags=tags or [],
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path):
            entries = self.all()
            if any(existing.text == text for existing in entries):
                return next(existing for existing in entries if existing.text == text)
            entries.append(entry)
            self._write_all(self._prune(entries))
        return entry

    def all(self) -> list[MemoryEntry]:
        if not self.path.exists():
            return []
        entries: list[MemoryEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(MemoryEntry.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return entries

    def search(self, query: str, *, top_k: int, min_score: float) -> list[tuple[MemoryEntry, float]]:
        ranked: list[tuple[MemoryEntry, float]] = []
        for entry in self.all():
            score = best_score(query, entry.text, entry.created_at, entry.importance)
            if score >= min_score:
                ranked.append((entry, score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked[:top_k]

    def remove(self, substring: str) -> int:
        substring = substring.strip()
        if not substring:
            return 0
        with file_lock(self.path):
            entries = self.all()
            kept = [entry for entry in entries if substring not in entry.text]
            self._write_all(kept)
        return len(entries) - len(kept)

    def _prune(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        lines = [json.dumps(entry.to_dict(), ensure_ascii=False) for entry in entries]
        total = sum(len(line) + 1 for line in lines)
        if total <= self.char_limit:
            return entries
        ordered = sorted(entries, key=lambda item: (item.importance, item.created_at))
        while ordered and total > self.char_limit:
            removed = ordered.pop(0)
            total -= len(json.dumps(removed.to_dict(), ensure_ascii=False)) + 1
        return sorted(ordered, key=lambda item: item.created_at)

    def _write_all(self, entries: list[MemoryEntry]) -> None:
        text = "\n".join(json.dumps(entry.to_dict(), ensure_ascii=False) for entry in entries)
        if text:
            text += "\n"
        atomic_write_text(self.path, text)


class ProfileStore:
    DEFAULT_PROFILE: dict[str, Any] = {
        "user_name": "",
        "facts": [],
        "preferences": [],
        "communication_style": [],
        "emotional_baseline": "",
        "companion_strategy": "",
        "topics": [],
        "updated_at": "",
    }

    def __init__(self, path: Path):
        self.path = path
        self.data = dict(self.DEFAULT_PROFILE)

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data = {**self.DEFAULT_PROFILE, **loaded}
            except json.JSONDecodeError:
                self.data = dict(self.DEFAULT_PROFILE)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self.path,
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data, ensure_ascii=False))

    def merge(self, update: dict[str, Any]) -> None:
        changed = False
        if not isinstance(update, dict):
            return
        for key in ("user_name", "emotional_baseline", "companion_strategy"):
            value = str(update.get(key) or "").strip()
            if value and value != self.data.get(key):
                self.data[key] = value
                changed = True
        for key in ("facts", "preferences", "communication_style", "topics"):
            values = update.get(key) or []
            if isinstance(values, str):
                values = [values]
            current = [str(item).strip() for item in self.data.get(key, []) if str(item).strip()]
            for item in values:
                item = str(item).strip()
                if item and item not in current:
                    current.append(item)
                    changed = True
            self.data[key] = current[-40:]
        if changed:
            self.data["updated_at"] = utc_now()
            self.save()
