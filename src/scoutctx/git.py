"""Thin, failure-tolerant Git helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def repository_root(path: Path) -> Path | None:
    result = _run(path, "rev-parse", "--show-toplevel")
    if not result or result.returncode != 0:
        return None
    try:
        return Path(result.stdout.decode("utf-8").strip()).resolve()
    except UnicodeDecodeError:
        return None


def tracked_and_untracked(root: Path) -> list[str] | None:
    """Return Git-visible files, respecting standard ignore rules."""

    result = _run(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if not result or result.returncode != 0:
        return None
    return [item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item]


def changed_files(root: Path) -> set[str]:
    result = _run(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if not result or result.returncode != 0:
        return set()

    changed: set[str] = set()
    records = [item for item in result.stdout.split(b"\0") if item]
    index = 0
    while index < len(records):
        record = records[index].decode("utf-8", errors="surrogateescape")
        if len(record) >= 4:
            status, path = record[:2], record[3:]
            changed.add(path)
            if "R" in status or "C" in status:
                index += 1
        index += 1
    return changed
