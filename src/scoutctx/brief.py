"""Public brief-generation pipeline."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from .config import Settings
from .git import changed_files
from .models import Brief, BriefFile
from .ranking import excerpt, rank, terms_for
from .redact import redact_secrets
from .scanner import scan


def _bounded_paths(paths: list[str], budget: int, priority: list[str] | None = None) -> tuple[list[str], int]:
    """Choose a path sample that represents every top-level area."""

    groups: dict[str, deque[str]] = {}
    for path in paths:
        key = path.split("/", 1)[0] if "/" in path else ""
        groups.setdefault(key, deque()).append(path)

    queue: list[str] = []
    seen: set[str] = set()
    for path in priority or []:
        if path in paths and path not in seen:
            queue.append(path)
            seen.add(path)
    while groups:
        empty: list[str] = []
        for key in sorted(groups):
            group = groups[key]
            while group and group[0] in seen:
                group.popleft()
            if group:
                path = group.popleft()
                queue.append(path)
                seen.add(path)
            if not group:
                empty.append(key)
        for key in empty:
            groups.pop(key, None)

    selected: list[str] = []
    cost = 0
    for path in queue:
        path_cost = len(path) + path.count("/") * 4 + 8
        if selected and cost + path_cost > budget:
            break
        selected.append(path)
        cost += path_cost
    return selected, cost


def generate(
    root: Path,
    task: str,
    settings: Settings,
    *,
    use_git: bool = True,
) -> Brief:
    """Scan *root* and produce a focused brief within an approximate token budget."""

    root = root.resolve()
    candidates, full_repository_map, stats = scan(
        root,
        max_file_bytes=settings.max_file_bytes,
        include=settings.include,
        exclude=settings.exclude,
        use_git=use_git,
    )
    changed = changed_files(root).intersection(full_repository_map) if use_git else set()
    stats.changed = len(changed)
    ranked = rank(candidates, task, changed)
    terms = terms_for(task)

    # Reserve room for metadata and the repository map, then distribute the
    # remaining character budget across several high-signal files.
    char_budget = settings.budget * 4
    map_budget = min(2_400, max(120, char_budget // 8))
    repository_map, map_cost = _bounded_paths(
        full_repository_map,
        map_budget,
        priority=[candidate.path for candidate in ranked[:8]],
    )
    changed_budget = min(1_200, max(80, char_budget // 10))
    visible_changed, changed_cost = _bounded_paths(sorted(changed), changed_budget)
    remaining = max(0, char_budget - map_cost - changed_cost - 500)
    selected: list[BriefFile] = []

    for candidate in ranked[: settings.max_files]:
        if remaining < 180:
            break
        files_left = max(1, min(8, settings.max_files - len(selected)))
        fair_share = max(180, remaining // files_left)
        per_file_limit = min(len(candidate.content), max(300, fair_share), 24_000)
        per_file_limit = min(per_file_limit, max(80, remaining - 100))
        content, excerpted = excerpt(candidate.content, terms, per_file_limit)
        if settings.redact:
            content, _ = redact_secrets(content)
        selected.append(
            BriefFile(
                path=candidate.path,
                content=content,
                score=candidate.score,
                reasons=candidate.reasons,
                truncated=candidate.truncated or excerpted,
            )
        )
        remaining -= len(content) + len(candidate.path) + 100

    stats.selected = len(selected)
    return Brief(
        task=task,
        root_name=root.name,
        budget=settings.budget,
        files=selected,
        repository_map=repository_map,
        changed_files=sorted(visible_changed),
        stats=stats,
        redacted=settings.redact,
    )
