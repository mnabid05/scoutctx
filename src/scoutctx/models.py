"""Small, serializable data models shared across ScoutCTX."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Candidate:
    """A readable repository file and the signals used to rank it."""

    path: str
    content: str
    size: int
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    modified: bool = False
    truncated: bool = False


@dataclass(slots=True)
class BriefFile:
    """A file excerpt selected for the final brief."""

    path: str
    content: str
    score: float
    reasons: list[str]
    truncated: bool = False


@dataclass(slots=True)
class ScanStats:
    """Summary counts for a repository scan."""

    discovered: int = 0
    readable: int = 0
    skipped_binary: int = 0
    skipped_large: int = 0
    changed: int = 0
    selected: int = 0
    estimated_tokens: int = 0


@dataclass(slots=True)
class Brief:
    """The complete result returned by the ScoutCTX pipeline."""

    task: str
    root_name: str
    budget: int
    files: list[BriefFile]
    repository_map: list[str]
    changed_files: list[str]
    stats: ScanStats
    redacted: bool = True
