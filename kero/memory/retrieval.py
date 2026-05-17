from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable


WORD_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)


def tokens(text: str) -> list[str]:
    base = [m.group(0).lower() for m in WORD_RE.finditer(text)]
    compact_cjk = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    bigrams = [compact_cjk[i : i + 2] for i in range(max(0, len(compact_cjk) - 1))]
    return [item for item in base + bigrams if item.strip()]


def lexical_score(query: str, text: str) -> float:
    q = set(tokens(query))
    t = set(tokens(text))
    if not q or not t:
        return 0.0
    return len(q & t) / max(len(q), 1)


def hashed_vector(text: str, dim: int = 256) -> dict[int, float]:
    counts: Counter[int] = Counter()
    for token in tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1 if digest[4] % 2 == 0 else -1
        counts[index] += sign
    norm = math.sqrt(sum(v * v for v in counts.values()))
    if norm == 0:
        return {}
    return {idx: value / norm for idx, value in counts.items()}


def cosine_sparse(left: dict[int, float], right: dict[int, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(idx, 0.0) for idx, value in left.items())


def recency_score(created_at: str | None, half_life_days: float = 60.0) -> float:
    created = parse_time(created_at)
    age_days = max(
        0.0,
        (datetime.now(timezone.utc) - created).total_seconds() / 86400.0,
    )
    if half_life_days <= 0:
        return 0.0
    return 0.5 ** (age_days / half_life_days)


def best_score(query: str, text: str, created_at: str | None, importance: float) -> float:
    q_vec = hashed_vector(query)
    t_vec = hashed_vector(text)
    semantic = max(0.0, cosine_sparse(q_vec, t_vec))
    lexical = lexical_score(query, text)
    recency = recency_score(created_at)
    importance = max(0.0, min(1.0, importance))
    return 0.50 * semantic + 0.30 * lexical + 0.12 * importance + 0.08 * recency


def compact_lines(lines: Iterable[str], limit: int) -> list[str]:
    output: list[str] = []
    used = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        needed = len(line) + 1
        if output and used + needed > limit:
            break
        if not output and needed > limit:
            output.append(line[:limit])
            break
        output.append(line)
        used += needed
    return output
