"""Task-aware ranking and excerpt selection."""

from __future__ import annotations

import math
from pathlib import PurePosixPath
import re

from .models import Candidate


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "it", "of", "on", "or", "that", "the", "this", "to", "with",
    "fix", "add", "make", "change", "update", "implement", "create", "please",
}
ANCHORS = {
    "agents.md": 5.0,
    "readme.md": 3.0,
    "pyproject.toml": 2.5,
    "package.json": 2.5,
    "cargo.toml": 2.5,
    "go.mod": 2.5,
    "dockerfile": 1.5,
    "makefile": 1.5,
}


def terms_for(task: str) -> list[str]:
    """Turn a natural-language task into stable search terms."""

    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", task)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*", expanded.lower())
    terms: list[str] = []
    for word in words:
        for part in re.split(r"[_.-]+", word):
            if len(part) >= 2 and part not in STOP_WORDS and part not in terms:
                terms.append(part)
    return terms[:24]


def rank(candidates: list[Candidate], task: str, changed: set[str]) -> list[Candidate]:
    """Rank files using explainable path, content, anchor, and Git signals."""

    terms = terms_for(task)
    for candidate in candidates:
        path_lower = candidate.path.lower()
        name = PurePosixPath(path_lower).name
        content_lower = candidate.content[:200_000].lower()
        score = ANCHORS.get(name, 0.0)
        reasons: list[str] = []

        path_hits = [term for term in terms if term in path_lower]
        if path_hits:
            score += 10.0 * len(path_hits)
            reasons.append("path: " + ", ".join(path_hits[:3]))

        content_hits: list[str] = []
        for term in terms:
            count = content_lower.count(term)
            if count:
                score += min(7.0, 1.5 + math.log2(count + 1))
                content_hits.append(term)
        if content_hits:
            reasons.append("content: " + ", ".join(content_hits[:3]))

        candidate.modified = candidate.path in changed
        if candidate.modified:
            score += 8.0
            reasons.insert(0, "changed in Git")

        if name in ANCHORS:
            reasons.append("project anchor")
        if "test" in terms and ("test" in name or "/tests/" in f"/{path_lower}/"):
            score += 5.0
            reasons.append("test file")

        # Prefer compact files when all other signals are equal; they often carry
        # high context density and leave room for another useful file.
        score += max(0.0, 1.0 - candidate.size / 100_000)
        candidate.score = round(score, 2)
        candidate.reasons = reasons or ["repository overview"]

    return sorted(candidates, key=lambda item: (-item.score, item.path.lower()))


def excerpt(content: str, terms: list[str], limit: int) -> tuple[str, bool]:
    """Select useful line windows from large files, bounded by *limit* chars."""

    if len(content) <= limit:
        return content.rstrip(), False
    if limit < 160:
        return content[:limit].rstrip(), True

    lines = content.splitlines()
    lowered = [line.lower() for line in lines]
    hits = [
        index
        for index, line in enumerate(lowered)
        if any(term in line for term in terms)
    ]
    if not hits:
        cut = content.rfind("\n", 0, limit - 24)
        cut = cut if cut > 0 else limit - 24
        return content[:cut].rstrip() + "\n… [truncated]", True

    ranges: list[tuple[int, int]] = []
    for hit in hits[:16]:
        start, end = max(0, hit - 6), min(len(lines), hit + 7)
        if ranges and start <= ranges[-1][1] + 2:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))

    chunks: list[str] = []
    used = 0
    for start, end in ranges:
        marker = f"… lines {start + 1}-{end} …\n" if start else ""
        chunk = marker + "\n".join(lines[start:end])
        if used + len(chunk) > limit - 24:
            room = limit - used - 40
            if room > 80:
                chunks.append(chunk[:room].rstrip())
            break
        chunks.append(chunk)
        used += len(chunk) + 2
    return "\n\n".join(chunks).rstrip() + "\n… [truncated]", True

