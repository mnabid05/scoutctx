"""Command-line interface for the ScoutCTX context plane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .config import initialize
from .framework import ContextResult, build_context
from .git import primary_worktree
from .sessions import Session, SessionManager


_COMMANDS = {"build", "session", "serve", "mcp", "init"}


def _add_context_options(parser: argparse.ArgumentParser, *, output: bool = True) -> None:
    parser.add_argument("--budget", type=int, help="approximate output token budget")
    parser.add_argument("--max-files", type=int, help="maximum selected files")
    parser.add_argument("--max-file-bytes", type=int, help="maximum bytes read from one file")
    parser.add_argument("--include", action="append", default=[], metavar="GLOB", help="only consider matching paths; repeatable")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="exclude matching paths; repeatable")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--no-git", action="store_true", help="scan the filesystem without Git discovery or status")
    parser.add_argument("--no-redact", action="store_true", help="disable secret redaction (use with care)")
    if output:
        parser.add_argument("--output", type=Path, metavar="PATH", help="write context to a file instead of stdout")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scoutctx",
        description="A vendor-neutral context plane for AI coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build focused context for a task")
    build.add_argument("task", nargs="*", help="the task the context should support")
    build.add_argument("--root", type=Path, default=Path.cwd(), help="repository directory")
    _add_context_options(build)

    session = subparsers.add_parser("session", help="manage portable multi-harness sessions")
    session_commands = session.add_subparsers(dest="session_command", required=True)

    start = session_commands.add_parser("start", help="start an isolated context session")
    start.add_argument("task", nargs="+", help="durable task for the session")
    start.add_argument("--root", type=Path, default=Path.cwd())
    start.add_argument("--no-worktree", action="store_true", help="reuse the current worktree")
    start.add_argument("--json", action="store_true", help="print machine-readable session data")

    listing = session_commands.add_parser("list", help="list context sessions")
    listing.add_argument("--root", type=Path, default=Path.cwd())
    listing.add_argument("--all", action="store_true", help="include archived sessions")
    listing.add_argument("--json", action="store_true")

    show = session_commands.add_parser("show", help="show one session")
    show.add_argument("session_id")
    show.add_argument("--root", type=Path, default=Path.cwd())
    show.add_argument("--json", action="store_true")

    context = session_commands.add_parser("context", help="build context with session continuity")
    context.add_argument("session_id")
    context.add_argument("--root", type=Path, default=Path.cwd())
    context.add_argument("--output", type=Path, metavar="PATH")
    _add_context_options(context, output=False)

    note = session_commands.add_parser("note", help="add knowledge shared across harnesses")
    note.add_argument("session_id")
    note.add_argument("text", nargs="+")
    note.add_argument("--root", type=Path, default=Path.cwd())

    run = session_commands.add_parser("run", help="launch any agent harness inside a session")
    run.add_argument("session_id")
    run.add_argument("--root", type=Path, default=Path.cwd())
    run.add_argument("--dry-run", action="store_true", help="build context and show the launch without executing it")
    run.add_argument("--budget", type=int)
    run.add_argument("command_argv", nargs=argparse.REMAINDER, metavar="COMMAND")

    archive = session_commands.add_parser("archive", help="archive a session without deleting it")
    archive.add_argument("session_id")
    archive.add_argument("--root", type=Path, default=Path.cwd())

    serve = subparsers.add_parser("serve", help="serve the context API over local HTTP")
    serve.add_argument("--root", type=Path, default=Path.cwd())
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    mcp = subparsers.add_parser("mcp", help="serve the scout_context MCP tool over stdio")
    mcp.add_argument("--root", type=Path, default=Path.cwd())

    init = subparsers.add_parser("init", help="create a starter .scoutctx.toml")
    init.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def _normalize_argv(argv: list[str]) -> list[str]:
    """Keep the original ``scoutctx TASK`` shorthand alongside subcommands."""

    if not argv:
        return ["build"]
    first = argv[0]
    if first in _COMMANDS or first in {"-h", "--help", "--version"}:
        return argv
    return ["build", *argv]


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _context_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "budget": args.budget,
        "max_files": args.max_files,
        "max_file_bytes": args.max_file_bytes,
        "format": args.format,
        "include": args.include,
        "exclude": args.exclude,
        "use_git": not args.no_git,
        "redact": False if args.no_redact else None,
    }


def _write_result(result: ContextResult, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(result.content)
        return
    destination = output.expanduser()
    destination.write_text(result.content, encoding="utf-8")
    selected = result.metadata.get("selected_files", [])
    selected_count = len(selected) if isinstance(selected, list) else 0
    estimated = result.metadata.get("estimated_tokens", 0)
    print(f"Wrote {destination} ({selected_count} files, ~{estimated:,} tokens)", file=sys.stderr)


def _session_summary(session: Session) -> str:
    worktree = session.worktree or "shared"
    harnesses = ",".join(session.harnesses) or "-"
    return f"{session.id}\t{session.status}\t{worktree}\t{harnesses}\t{session.task}"


def _run_build(args: argparse.Namespace) -> int:
    task = " ".join(args.task).strip() or "Understand this codebase and its architecture"
    options = _context_options(args)
    if args.output:
        resolved_root = args.root.expanduser().resolve()
        resolved_output = args.output.expanduser().resolve()
        if resolved_output.is_relative_to(resolved_root):
            options["exclude"] = [*options["exclude"], resolved_output.relative_to(resolved_root).as_posix()]
    result = build_context(task, root=args.root, **options)
    _write_result(result, args.output)
    return 0


def _run_session(args: argparse.Namespace) -> int:
    manager = SessionManager(args.root)
    command = args.session_command
    if command == "start":
        session = manager.start(" ".join(args.task), worktree=not args.no_worktree)
        print(json.dumps(session.to_dict(), indent=2, sort_keys=True) if args.json else _session_summary(session))
        return 0
    if command == "list":
        sessions = manager.list(include_archived=args.all)
        if args.json:
            print(json.dumps([session.to_dict() for session in sessions], indent=2, sort_keys=True))
        else:
            print("ID\tSTATUS\tWORKTREE\tHARNESSES\tTASK")
            for session in sessions:
                print(_session_summary(session))
        return 0
    if command == "show":
        session = manager.get(args.session_id)
        print(json.dumps(session.to_dict(), indent=2, sort_keys=True) if args.json else _session_summary(session))
        return 0
    if command == "context":
        result = manager.context(args.session_id, **_context_options(args))
        _write_result(result, args.output)
        return 0
    if command == "note":
        session = manager.note(args.session_id, " ".join(args.text))
        print(f"Added shared note to {session.id}")
        return 0
    if command == "run":
        from .harness import LaunchPlan, launch

        argv = list(args.command_argv)
        if argv and argv[0] == "--":
            argv.pop(0)
        context_options = {"budget": args.budget} if args.budget is not None else None
        outcome = launch(manager, args.session_id, argv, dry_run=args.dry_run, context_options=context_options)
        if isinstance(outcome, LaunchPlan):
            print(json.dumps(outcome.to_dict(), indent=2, sort_keys=True))
            return 0
        return outcome.returncode
    if command == "archive":
        session = manager.archive(args.session_id)
        print(f"Archived {session.id}; its context and worktree were preserved")
        return 0
    raise ValueError(f"unknown session command: {command}")


def main(argv: list[str] | None = None) -> int:
    parsed_argv = _normalize_argv(list(sys.argv[1:] if argv is None else argv))
    args = _parser().parse_args(parsed_argv)
    try:
        if args.command == "build":
            return _run_build(args)
        if args.command == "session":
            return _run_session(args)
        if args.command == "serve":
            from .http import serve

            print(f"ScoutCTX context API listening on http://{args.host}:{args.port}", file=sys.stderr)
            serve(host=args.host, port=args.port, root=args.root)
            return 0
        if args.command == "mcp":
            from .mcp import serve

            serve(root=args.root)
            return 0
        if args.command == "init":
            requested = args.root.expanduser().resolve()
            if not requested.is_dir():
                raise ValueError(f"not a directory: {requested}")
            root = primary_worktree(requested) or requested
            print(f"Created {initialize(root)}")
            return 0
        raise ValueError(f"unknown command: {args.command}")
    except KeyboardInterrupt:
        return 130
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        print(f"scoutctx: {_error_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
