"""Framework-neutral Python API for producing ScoutCTX context.

The objects in this module deliberately expose plain strings and dictionaries so
the result can be passed to any model SDK, orchestration library, or transport.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any, Sequence

from .brief import generate
from .config import load_settings
from .providers import ContextProvider, ContextRequest, ProviderRegistry
from .ranking import excerpt, terms_for
from .redact import redact_secrets
from .render import render_json, render_markdown


_FORMATS = {"json", "markdown"}


@dataclass(frozen=True, slots=True)
class ContextResult:
    """Rendered context and deterministic metadata suitable for model SDKs."""

    content: str
    format: str
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        # A defensive copy prevents a caller retaining the input mapping from
        # changing a frozen result after construction.
        object.__setattr__(self, "metadata", deepcopy(self.metadata))

    def to_dict(self) -> dict[str, object]:
        """Return a versioned, JSON-serializable representation of the result."""

        return {
            "schema_version": "1",
            "content": self.content,
            "format": self.format,
            "metadata": deepcopy(self.metadata),
        }


def _validate_patterns(patterns: Sequence[str], name: str) -> list[str]:
    if isinstance(patterns, (str, bytes)) or not all(isinstance(item, str) for item in patterns):
        raise ValueError(f"{name} must be a sequence of strings")
    return list(patterns)


def build_context(
    task: str,
    *,
    root: str | Path = ".",
    budget: int | None = None,
    max_files: int | None = None,
    max_file_bytes: int | None = None,
    format: str = "markdown",
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    use_git: bool = True,
    redact: bool | None = None,
    providers: ProviderRegistry | Mapping[str, ContextProvider] | Iterable[tuple[str, ContextProvider]] | None = None,
) -> ContextResult:
    """Build portable context for *task* without coupling to a model provider.

    Project configuration is loaded from ``.scoutctx.toml`` first. Explicit
    scalar options replace configured values, while include and exclude
    patterns extend the configured filters in the same way as the CLI.
    """

    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    normalized_task = task.strip()

    root_path = Path(root).expanduser()
    if not root_path.exists():
        raise ValueError(f"root does not exist: {root_path}")
    if not root_path.is_dir():
        raise ValueError(f"root is not a directory: {root_path}")
    root_path = root_path.resolve()

    if format not in _FORMATS:
        raise ValueError("format must be 'markdown' or 'json'")
    if budget is not None and (
        isinstance(budget, bool) or not isinstance(budget, int) or budget < 256
    ):
        raise ValueError("budget must be at least 256")
    if max_files is not None and (
        isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1
    ):
        raise ValueError("max_files must be positive")
    if max_file_bytes is not None and (
        isinstance(max_file_bytes, bool)
        or not isinstance(max_file_bytes, int)
        or max_file_bytes < 1024
    ):
        raise ValueError("max_file_bytes must be at least 1024")
    if not isinstance(use_git, bool):
        raise ValueError("use_git must be a boolean")
    if redact is not None and not isinstance(redact, bool):
        raise ValueError("redact must be a boolean or None")

    extra_include = _validate_patterns(include, "include")
    extra_exclude = _validate_patterns(exclude, "exclude")

    settings = load_settings(root_path)
    if budget is not None:
        settings.budget = budget
    if max_files is not None:
        settings.max_files = max_files
    if max_file_bytes is not None:
        settings.max_file_bytes = max_file_bytes
    if redact is not None:
        settings.redact = redact
    settings.include.extend(extra_include)
    settings.exclude.extend(extra_exclude)

    configured_budget = settings.budget
    provider_result = None
    if providers is not None:
        registry = providers if isinstance(providers, ProviderRegistry) else ProviderRegistry(providers)
        provider_result = registry.collect(ContextRequest(normalized_task, root_path, configured_budget))
        if provider_result.documents:
            # Reserve up to one third of the complete budget for organizational
            # knowledge while preserving the core scanner's minimum budget.
            provider_tokens = min(configured_budget // 3, 4_000)
            settings.budget = max(256, configured_budget - provider_tokens)

    brief = generate(root_path, normalized_task, settings, use_git=use_git)
    brief.budget = configured_budget
    content = render_json(brief) if format == "json" else render_markdown(brief)

    provider_documents: list[dict[str, object]] = []
    if provider_result and provider_result.documents:
        allowance = min(configured_budget * 4 // 3, 16_000)
        task_terms = terms_for(normalized_task)
        used = 0
        for document in provider_result.documents[:32]:
            remaining = allowance - used
            if remaining < 160:
                break
            document_content, truncated = excerpt(document.content, task_terms, min(remaining, 6_000))
            if settings.redact:
                document_content, _ = redact_secrets(document_content)
            provider_documents.append(
                {
                    "id": document.id,
                    "source": document.source,
                    "content": document_content,
                    "weight": document.weight,
                    "truncated": truncated,
                }
            )
            used += len(document_content) + len(document.id) + len(document.source) + 100

        if format == "json":
            payload = json.loads(content)
            payload["provider_context"] = provider_documents
            content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        else:
            sections = ["", "## Connected knowledge", ""]
            for document in provider_documents:
                sections.extend(
                    [
                        f"### `{document['source']}:{document['id']}`",
                        "",
                        f"_Provider weight {document['weight']}_",
                        "",
                        "````text",
                        str(document["content"]),
                        "````",
                        "",
                    ]
                )
            content = content.rstrip() + "\n" + "\n".join(sections).rstrip() + "\n"

    estimated_tokens = (len(content) + 3) // 4
    metadata: dict[str, object] = {
        "task": brief.task,
        "root_name": brief.root_name,
        "budget": configured_budget,
        "selected_files": [file.path for file in brief.files],
        "estimated_tokens": estimated_tokens,
        "redacted": brief.redacted,
        "changed": brief.stats.changed,
        "discovered_files": brief.stats.discovered,
        "readable_files": brief.stats.readable,
        "provider_documents": [
            {"id": document["id"], "source": document["source"]}
            for document in provider_documents
        ],
        "provider_diagnostics": [
            {"provider": item.provider, "code": item.code}
            for item in (provider_result.diagnostics if provider_result else ())
        ],
    }
    return ContextResult(content=content, format=format, metadata=metadata)


class ScoutCTX:
    """Reusable context builder with defaults for one project or integration."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        budget: int | None = None,
        max_files: int | None = None,
        max_file_bytes: int | None = None,
        format: str = "markdown",
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        use_git: bool = True,
        redact: bool | None = None,
        providers: ProviderRegistry | Mapping[str, ContextProvider] | Iterable[tuple[str, ContextProvider]] | None = None,
    ) -> None:
        self._defaults: dict[str, Any] = {
            "root": root,
            "budget": budget,
            "max_files": max_files,
            "max_file_bytes": max_file_bytes,
            "format": format,
            "include": tuple(_validate_patterns(include, "include")),
            "exclude": tuple(_validate_patterns(exclude, "exclude")),
            "use_git": use_git,
            "redact": redact,
            "providers": providers,
        }

    def context(self, task: str, **overrides: Any) -> ContextResult:
        """Build context using this client's defaults and per-call overrides."""

        options = {**self._defaults, **overrides}
        return build_context(task, **options)


__all__ = ["ContextResult", "ScoutCTX", "build_context"]
