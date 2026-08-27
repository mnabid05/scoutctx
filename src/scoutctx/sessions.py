"""Persistent, harness-neutral agent sessions with optional Git worktrees."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Sequence

from .git import create_worktree, primary_worktree, repository_root
from .redact import REDACTED, redact_secrets


SESSION_SCHEMA_VERSION = "1"
STATE_DIRECTORY = ".scoutctx"
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


@dataclass(slots=True)
class Session:
    """Portable state shared by every harness used for one task."""

    id: str
    task: str
    repository: str
    status: str = "active"
    branch: str | None = None
    worktree: str | None = None
    harnesses: list[str] = field(default_factory=list)
    runs: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    schema_version: str = SESSION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _slug(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.lower())[:5]
    slug = "-".join(words)[:60].strip("-")
    return slug or "session"


class SessionManager:
    """Create and resume context sessions independently of any AI vendor."""

    def __init__(self, root: str | Path = ".") -> None:
        requested = Path(root).expanduser().resolve()
        if not requested.is_dir():
            raise ValueError(f"not a directory: {requested}")
        self.repository_root = repository_root(requested)
        self.root = primary_worktree(requested) or requested
        self.state_root = self.root / STATE_DIRECTORY
        self.sessions_root = self.state_root / "sessions"
        self.worktrees_root = self.state_root / "worktrees"

    def _session_directory(self, session_id: str) -> Path:
        if not _SAFE_ID.fullmatch(session_id):
            raise ValueError("session id may contain only lowercase letters, numbers, and hyphens")
        return self.sessions_root / session_id

    def _write(self, session: Session) -> None:
        directory = self._session_directory(session.id)
        directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary = directory / "session.json.tmp"
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(directory / "session.json")

    def start(self, task: str, *, worktree: bool = True) -> Session:
        """Start a session and optionally isolate it in a new Git worktree."""

        task = task.strip()
        if not task:
            raise ValueError("task must not be empty")
        task, _ = redact_secrets(task)
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        base = _slug(task)
        directory: Path | None = None
        session_id = ""
        for counter in range(1, 1_000):
            candidate = f"{base}-{counter:02d}"
            candidate_directory = self._session_directory(candidate)
            try:
                candidate_directory.mkdir()
            except FileExistsError:
                continue
            session_id, directory = candidate, candidate_directory
            break
        if directory is None:
            raise RuntimeError("could not allocate a unique session id")

        branch: str | None = None
        relative_worktree: str | None = None
        if worktree:
            if self.repository_root is None:
                directory.rmdir()
                raise ValueError("worktree sessions require a Git repository; pass worktree=False")
            self.worktrees_root.mkdir(parents=True, exist_ok=True)
            destination = (self.worktrees_root / session_id).resolve()
            if not destination.is_relative_to(self.state_root.resolve()):
                directory.rmdir()
                raise ValueError("unsafe worktree destination")
            branch = f"scoutctx/{session_id}"
            try:
                create_worktree(self.root, destination, branch)
            except Exception:
                directory.rmdir()
                raise
            relative_worktree = destination.relative_to(self.root).as_posix()

        session = Session(
            id=session_id,
            task=task,
            repository=self.root.name,
            branch=branch,
            worktree=relative_worktree,
        )
        self._write(session)
        return session

    def get(self, session_id: str) -> Session:
        """Load one session and validate its persisted shape."""

        path = self._session_directory(session_id) / "session.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(f"unknown session: {session_id}") from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read session {session_id}: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != SESSION_SCHEMA_VERSION:
            raise ValueError(f"unsupported session data: {session_id}")
        try:
            session = Session(**data)
        except TypeError as exc:
            raise ValueError(f"invalid session data: {session_id}") from exc
        if (
            session.id != session_id
            or session.status not in {"active", "archived"}
            or not isinstance(session.task, str)
            or not isinstance(session.repository, str)
            or not isinstance(session.harnesses, list)
            or not all(isinstance(item, str) for item in session.harnesses)
            or not isinstance(session.runs, list)
            or not all(
                isinstance(run, list) and all(isinstance(part, str) for part in run)
                for run in session.runs
            )
            or not isinstance(session.notes, list)
            or not all(isinstance(item, str) for item in session.notes)
        ):
            raise ValueError(f"invalid session data: {session_id}")
        return session

    def list(self, *, include_archived: bool = False) -> list[Session]:
        """List sessions in deterministic identifier order."""

        if not self.sessions_root.exists():
            return []
        sessions: list[Session] = []
        for path in sorted(self.sessions_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir() or not _SAFE_ID.fullmatch(path.name):
                continue
            try:
                session = self.get(path.name)
            except (KeyError, ValueError):
                continue
            if include_archived or session.status != "archived":
                sessions.append(session)
        return sessions

    def working_directory(self, session: Session) -> Path:
        """Return the safe repository or linked-worktree directory for a session."""

        if session.worktree is None:
            return self.root
        path = (self.root / session.worktree).resolve()
        if not path.is_relative_to(self.state_root.resolve()) or not path.is_dir():
            raise ValueError(f"session worktree is missing or unsafe: {session.id}")
        return path

    def note(self, session_id: str, text: str) -> Session:
        """Add durable knowledge that will follow the session across harnesses."""

        text = text.strip()
        if not text:
            raise ValueError("note must not be empty")
        session = self.get(session_id)
        safe_text, _ = redact_secrets(text)
        session.notes.append(safe_text)
        self._write(session)
        return session

    def record_run(self, session_id: str, command: Sequence[str]) -> Session:
        """Record a harness invocation without storing credentials or environment."""

        if (
            isinstance(command, (str, bytes))
            or not command
            or not all(isinstance(part, str) for part in command)
            or not command[0].strip()
        ):
            raise ValueError("harness command must not be empty")
        safe_command: list[str] = []
        redact_next = False
        sensitive_option = re.compile(
            r"^--?(?:api[-_]?key|token|secret|password|passwd|client[-_]?secret)$",
            re.IGNORECASE,
        )
        sensitive_assignment = re.compile(
            r"^(?P<name>--?[a-z0-9_-]*(?:api[-_]?key|token|secret|password|passwd)[a-z0-9_-]*)=.+$",
            re.IGNORECASE,
        )
        for part in command:
            value = str(part)
            if redact_next:
                safe_command.append(REDACTED)
                redact_next = False
                continue
            assignment = sensitive_assignment.match(value)
            if assignment:
                safe_command.append(f"{assignment.group('name')}={REDACTED}")
                continue
            redacted, _ = redact_secrets(value)
            safe_command.append(redacted)
            redact_next = bool(sensitive_option.fullmatch(value))

        session = self.get(session_id)
        executable = Path(command[0]).name
        if executable not in session.harnesses:
            session.harnesses.append(executable)
        session.runs.append(safe_command)
        self._write(session)
        return session

    def archive(self, session_id: str) -> Session:
        """Hide a completed session without deleting its accumulated context."""

        session = self.get(session_id)
        session.status = "archived"
        self._write(session)
        return session

    def context(self, session_id: str, **options: object):
        """Build and persist a context snapshot enriched with session continuity."""

        from .framework import ContextResult, build_context

        session = self.get(session_id)
        result = build_context(session.task, root=self.working_directory(session), **options)
        continuity = [
            "# Session continuity",
            "",
            f"> **Session:** `{session.id}` · **Status:** {session.status}",
            f"> **Harness history:** {', '.join(session.harnesses) if session.harnesses else 'none yet'}",
            "",
            "## Durable task",
            "",
            session.task,
        ]
        if session.notes:
            continuity.extend(["", "## Shared notes", "", *[f"- {note}" for note in session.notes]])
        if result.format == "json":
            payload = json.loads(result.content)
            payload["session"] = {
                "id": session.id,
                "status": session.status,
                "harnesses": list(session.harnesses),
                "notes": list(session.notes),
            }
            content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        else:
            continuity.extend(["", "---", "", result.content])
            content = "\n".join(continuity).rstrip() + "\n"
        metadata = dict(result.metadata)
        metadata.update(
            {
                "session_id": session.id,
                "status": session.status,
                "harnesses": list(session.harnesses),
                "estimated_tokens": (len(content) + 3) // 4,
            }
        )
        enriched = ContextResult(content=content, format=result.format, metadata=metadata)
        suffix = "json" if result.format == "json" else "md"
        snapshot = self._session_directory(session.id) / f"context.{suffix}"
        snapshot.write_text(enriched.content, encoding="utf-8")
        return enriched
