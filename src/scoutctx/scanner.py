"""Fast, local-only repository discovery and text loading."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from .git import tracked_and_untracked
from .models import Candidate, ScanStats


DEFAULT_EXCLUDES = (
    ".git/**",
    ".hg/**",
    ".svn/**",
    ".venv/**",
    "venv/**",
    "node_modules/**",
    "vendor/**",
    "dist/**",
    "build/**",
    "target/**",
    "coverage/**",
    ".next/**",
    ".turbo/**",
    "__pycache__/**",
    "*.pyc",
    "*.lock",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.pdf",
    "*.zip",
    "*.gz",
    "*.woff*",
    "*.ttf",
)


def _matches(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    normalized = path[2:] if path.startswith("./") else path
    for raw in patterns:
        pattern = raw.strip().lstrip("/")
        if not pattern or pattern.startswith("#"):
            continue
        if pattern.endswith("/"):
            pattern += "**"
        if (
            fnmatch(normalized, pattern)
            or fnmatch(normalized, f"**/{pattern}")
            or fnmatch(Path(normalized).name, pattern)
        ):
            return True
    return False


def _ignore_file_patterns(root: Path, names: tuple[str, ...]) -> list[str]:
    patterns: list[str] = []
    for name in names:
        path = root / name
        try:
            patterns.extend(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            continue
    # Negated gitignore patterns need a full gitignore engine. Git handles them
    # for repositories; outside Git we keep them rather than excluding too much.
    return [pattern for pattern in patterns if not pattern.strip().startswith("!")]


def discover_paths(
    root: Path,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    use_git: bool = True,
) -> list[str]:
    """Discover candidate files deterministically, with Git as the fast path."""

    root = root.resolve()
    paths = tracked_and_untracked(root) if use_git else None
    using_git_paths = paths is not None
    if not using_git_paths:
        paths = [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()]

    include = include or []
    ignore_names = (".scoutctxignore",) if using_git_paths else (".gitignore", ".scoutctxignore")
    excludes = [*DEFAULT_EXCLUDES, *_ignore_file_patterns(root, ignore_names), *(exclude or [])]
    selected = {
        path.replace("\\", "/")
        for path in paths
        if not _matches(path, excludes) and (not include or _matches(path, include))
    }
    return sorted(selected, key=lambda value: (value.count("/"), value.lower()))


def scan(
    root: Path,
    *,
    max_file_bytes: int,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    use_git: bool = True,
) -> tuple[list[Candidate], list[str], ScanStats]:
    """Read UTF-8-ish text files without loading unbounded data into memory."""

    root = root.resolve()
    paths = discover_paths(root, include=include, exclude=exclude, use_git=use_git)
    stats = ScanStats(discovered=len(paths))
    candidates: list[Candidate] = []

    for relative in paths:
        path = root / relative
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            size = path.stat().st_size
            with path.open("rb") as handle:
                raw = handle.read(max_file_bytes + 1)
        except OSError:
            continue

        if b"\0" in raw[:8192]:
            stats.skipped_binary += 1
            continue

        truncated = len(raw) > max_file_bytes
        if truncated:
            raw = raw[:max_file_bytes]
            stats.skipped_large += 1
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = raw.decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                stats.skipped_binary += 1
                continue

        replacement_ratio = content.count("\ufffd") / max(1, len(content))
        if replacement_ratio > 0.01:
            stats.skipped_binary += 1
            continue
        candidates.append(Candidate(relative, content, size, truncated=truncated))

    stats.readable = len(candidates)
    return candidates, paths, stats
