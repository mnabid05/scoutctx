"""Launch any command-line AI harness with portable ScoutCTX context.

Harnesses receive a context file and session details through both explicit
placeholders and a small, documented set of environment variables.  Commands
are always executed as an argument vector; no shell is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Mapping, Sequence

from .sessions import SessionManager


_PLACEHOLDERS = ("context", "task", "worktree", "session")


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """A fully expanded, inspectable harness invocation.

    ``environment`` contains only ScoutCTX-owned variables.  The inherited
    process environment and caller-provided overrides are deliberately omitted
    so dry-run output cannot accidentally expose credentials.
    """

    session_id: str
    harness: str
    command: tuple[str, ...]
    cwd: Path
    context_file: Path
    environment: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable plan without inherited environment data."""

        return {
            "session_id": self.session_id,
            "harness": self.harness,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "context_file": str(self.context_file),
            "environment": dict(self.environment),
        }


def _validate_command(command: Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)) or not command:
        raise ValueError("harness command must be a non-empty sequence of strings")
    if not all(isinstance(part, str) for part in command):
        raise ValueError("harness command must contain only strings")
    if not command[0].strip() or "\x00" in "".join(command):
        raise ValueError("harness command contains an invalid argument")
    return tuple(command)


def _substitute(command: Sequence[str], values: Mapping[str, str]) -> tuple[str, ...]:
    """Replace ScoutCTX placeholders while leaving unrelated braces literal."""

    expanded: list[str] = []
    for argument in command:
        for name in _PLACEHOLDERS:
            argument = argument.replace("{" + name + "}", values[name])
        expanded.append(argument)
    return tuple(expanded)


def _context_file(manager: SessionManager, session_id: str, format: str) -> Path:
    suffix = "json" if format == "json" else "md"
    return (manager.sessions_root / session_id / f"context.{suffix}").resolve()


def launch(
    manager: SessionManager,
    session_id: str,
    command: Sequence[str],
    *,
    dry_run: bool = False,
    context_options: Mapping[str, object] | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> LaunchPlan | subprocess.CompletedProcess[bytes]:
    """Build session context and launch a model harness.

    The supported argument placeholders are ``{context}``, ``{task}``,
    ``{worktree}``, and ``{session}``.  A dry run still creates the deterministic
    context snapshot needed to make its plan accurate, but does not execute or
    record the command.
    """

    argv = _validate_command(command)
    if extra_env is not None and not all(
        isinstance(key, str) and isinstance(value, str) for key, value in extra_env.items()
    ):
        raise ValueError("extra_env must map strings to strings")
    session = manager.get(session_id)
    if session.status == "archived":
        raise ValueError(f"cannot launch an archived session: {session_id}")
    worktree = manager.working_directory(session).resolve()

    options = dict(context_options or {})
    result = manager.context(session_id, **options)
    context_file = _context_file(manager, session_id, result.format)
    if not context_file.is_file():
        raise RuntimeError(f"context snapshot was not created: {context_file}")

    values = {
        "context": str(context_file),
        "task": session.task,
        "worktree": str(worktree),
        "session": session.id,
    }
    expanded = _substitute(argv, values)
    harness = Path(expanded[0]).name
    scoutctx_environment = {
        "SCOUTCTX_SESSION_ID": session.id,
        "SCOUTCTX_TASK": session.task,
        "SCOUTCTX_CONTEXT_FILE": str(context_file),
        "SCOUTCTX_CONTEXT_FORMAT": result.format,
        "SCOUTCTX_WORKTREE": str(worktree),
        "SCOUTCTX_REPOSITORY": session.repository,
    }
    plan = LaunchPlan(
        session_id=session.id,
        harness=harness,
        command=expanded,
        cwd=worktree,
        context_file=context_file,
        environment=scoutctx_environment,
    )
    if dry_run:
        return plan

    environment = os.environ.copy()
    if extra_env is not None:
        environment.update(extra_env)
    environment.update(scoutctx_environment)

    # Persist the portable command template rather than expanded absolute
    # machine paths. The child still receives the fully expanded invocation.
    manager.record_run(session_id, argv)
    return subprocess.run(
        list(expanded),
        cwd=worktree,
        env=environment,
        check=False,
        shell=False,
    )


launch_harness = launch

__all__ = ["LaunchPlan", "launch", "launch_harness"]
