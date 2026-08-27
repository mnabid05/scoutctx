"""Pluggable sources of institutional context for ScoutCTX.

Providers deliberately have a very small contract: they receive an immutable
request and return context documents.  The registry adds deterministic
ordering and failure isolation so provider implementations do not need to
coordinate with one another.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
import math
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ContextRequest:
    """The task and repository boundary supplied to every context provider."""

    task: str
    root: Path
    budget: int

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or not self.task.strip():
            raise ValueError("task must be a non-empty string")
        if isinstance(self.budget, bool) or not isinstance(self.budget, int) or self.budget <= 0:
            raise ValueError("budget must be a positive integer")
        root = Path(self.root).expanduser().resolve()
        object.__setattr__(self, "root", root)


@dataclass(frozen=True, slots=True)
class ContextDocument:
    """A self-contained piece of context returned by a provider."""

    id: str
    content: str
    source: str
    weight: float = 0.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("document id must be a non-empty string")
        if not isinstance(self.content, str):
            raise TypeError("document content must be a string")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("document source must be a non-empty string")
        if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)):
            raise TypeError("document weight must be a number")
        if not math.isfinite(float(self.weight)):
            raise ValueError("document weight must be finite")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("document metadata must be a mapping")

        # Provider-owned dictionaries must not be able to mutate a document
        # after it has entered the registry.
        object.__setattr__(self, "weight", float(self.weight))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@runtime_checkable
class ContextProvider(Protocol):
    """Structural interface implemented by context sources."""

    def collect(self, request: ContextRequest) -> Iterable[ContextDocument]:
        """Return documents relevant to ``request``."""


@dataclass(frozen=True, slots=True)
class ProviderDiagnostic:
    """A non-fatal problem encountered while collecting provider context."""

    provider: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """The successful documents and non-fatal diagnostics from a collection."""

    documents: tuple[ContextDocument, ...]
    diagnostics: tuple[ProviderDiagnostic, ...] = ()


class StaticProvider:
    """Return a fixed set of documents for every request."""

    def __init__(self, documents: Iterable[ContextDocument]) -> None:
        self._documents = tuple(documents)

    def collect(self, request: ContextRequest) -> tuple[ContextDocument, ...]:
        """Return the configured documents without inspecting the repository."""

        del request
        return self._documents


class DirectoryProvider:
    """Load bounded text documents from a directory beneath the request root.

    ``max_bytes`` limits each file read. ``max_total_bytes`` and ``max_files``
    bound the provider as a whole. Files larger than the per-file or remaining
    total allowance are returned as truncated documents.
    """

    def __init__(
        self,
        directory: str | Path = ".",
        *,
        globs: Sequence[str] = ("**/*",),
        max_bytes: int = 64 * 1024,
        max_total_bytes: int = 1024 * 1024,
        max_files: int = 256,
        source: str = "directory",
        weight: float = 0.0,
    ) -> None:
        if not globs or any(not isinstance(pattern, str) or not pattern for pattern in globs):
            raise ValueError("globs must contain at least one non-empty pattern")
        for pattern in globs:
            pure = PurePosixPath(pattern.replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError("glob patterns must be relative and may not contain '..'")
        for name, value in (
            ("max_bytes", max_bytes),
            ("max_total_bytes", max_total_bytes),
            ("max_files", max_files),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise TypeError("weight must be a number")
        if not math.isfinite(float(weight)):
            raise ValueError("weight must be finite")

        self.directory = Path(directory)
        self.globs = tuple(globs)
        self.max_bytes = max_bytes
        self.max_total_bytes = max_total_bytes
        self.max_files = max_files
        self.source = source
        self.weight = float(weight)

    def _base_directory(self, request: ContextRequest) -> Path:
        root = request.root.resolve()
        configured = self.directory.expanduser()
        candidate = configured if configured.is_absolute() else root / configured
        absolute_candidate = candidate.absolute()
        try:
            relative_parts = absolute_candidate.relative_to(root).parts
        except ValueError as exc:
            raise ValueError("provider directory must remain beneath the request root") from exc
        current = root
        for part in relative_parts:
            current /= part
            if current.is_symlink():
                raise ValueError("provider directory may not contain symlinks")
        base = candidate.resolve()
        if not base.is_relative_to(root):
            raise ValueError("provider directory must remain beneath the request root")
        if not base.is_dir():
            raise ValueError("provider directory does not exist or is not a directory")
        return base

    def _discover(self, base: Path) -> list[Path]:
        discovered: set[Path] = set()
        for pattern in self.globs:
            try:
                discovered.update(path for path in base.glob(pattern) if path.is_file())
            except (OSError, ValueError):
                continue
        return sorted(
            discovered,
            key=lambda path: (
                path.relative_to(base).as_posix().casefold(),
                path.relative_to(base).as_posix(),
            ),
        )

    @staticmethod
    def _decode(raw: bytes) -> str | None:
        if b"\0" in raw[:8192]:
            return None
        content = raw.decode("utf-8", errors="replace")
        if content.count("\ufffd") / max(1, len(content)) > 0.01:
            return None
        return content

    def collect(self, request: ContextRequest) -> tuple[ContextDocument, ...]:
        """Read matching text files without following links or escaping root."""

        root = request.root.resolve()
        base = self._base_directory(request)
        documents: list[ContextDocument] = []
        consumed = 0

        for path in self._discover(base):
            if len(documents) >= self.max_files or consumed >= self.max_total_bytes:
                break
            try:
                relative_parts = path.relative_to(base).parts
                current = base
                has_symlink = False
                for part in relative_parts:
                    current /= part
                    if current.is_symlink():
                        has_symlink = True
                        break
                if has_symlink:
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(root) or not resolved.is_relative_to(base):
                    continue
                size = path.stat().st_size
                allowance = min(self.max_bytes, self.max_total_bytes - consumed)
                with path.open("rb") as handle:
                    raw = handle.read(allowance + 1)
            except OSError:
                continue

            truncated = len(raw) > allowance
            bounded = raw[:allowance]
            content = self._decode(bounded)
            if content is None:
                continue

            relative = resolved.relative_to(root).as_posix()
            consumed += len(bounded)
            documents.append(
                ContextDocument(
                    id=f"{self.source}:{relative}",
                    content=content,
                    source=self.source,
                    weight=self.weight,
                    metadata={
                        "path": relative,
                        "size": size,
                        "truncated": truncated,
                    },
                )
            )
        return tuple(documents)


class ProviderRegistry:
    """Collect from named providers with deterministic, isolated failures."""

    def __init__(
        self,
        providers: Mapping[str, ContextProvider]
        | Iterable[tuple[str, ContextProvider]] = (),
    ) -> None:
        self._providers: dict[str, ContextProvider] = {}
        entries = providers.items() if isinstance(providers, Mapping) else providers
        for name, provider in entries:
            self.register(name, provider)

    def register(self, name: str, provider: ContextProvider) -> None:
        """Register ``provider`` under a unique stable name."""

        if not isinstance(name, str) or not name.strip():
            raise ValueError("provider name must be a non-empty string")
        if name in self._providers:
            raise ValueError(f"provider already registered: {name}")
        if not isinstance(provider, ContextProvider):
            raise TypeError("provider must implement collect(request)")
        self._providers[name] = provider

    def collect(self, request: ContextRequest) -> ProviderResult:
        """Collect every provider, retaining successes when another one fails."""

        documents: list[ContextDocument] = []
        diagnostics: list[ProviderDiagnostic] = []
        seen_ids: dict[str, str] = {}

        for name in sorted(self._providers, key=lambda value: (value.casefold(), value)):
            provider = self._providers[name]
            try:
                supplied = tuple(provider.collect(request))
            except Exception as error:  # A plugin must not take down its peers.
                diagnostics.append(
                    ProviderDiagnostic(name, "provider_error", f"{type(error).__name__}: {error}")
                )
                continue

            for document in supplied:
                if not isinstance(document, ContextDocument):
                    diagnostics.append(
                        ProviderDiagnostic(
                            name,
                            "invalid_document",
                            "provider returned an object that is not a ContextDocument",
                        )
                    )
                    continue
                previous = seen_ids.get(document.id)
                if previous is not None:
                    diagnostics.append(
                        ProviderDiagnostic(
                            name,
                            "duplicate_document_id",
                            f"document id {document.id!r} was already supplied by {previous!r}",
                        )
                    )
                    continue
                seen_ids[document.id] = name
                documents.append(document)

        documents.sort(
            key=lambda item: (
                -item.weight,
                item.source.casefold(),
                item.source,
                item.id.casefold(),
                item.id,
            )
        )
        return ProviderResult(tuple(documents), tuple(diagnostics))
