"""Command-line interface for ScoutCTX."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .brief import generate
from .config import initialize, load_settings
from .git import repository_root
from .render import render_json, render_markdown


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scoutctx",
        description="Build a task-focused, token-budgeted codebase brief for an AI coding agent.",
    )
    parser.add_argument("task", nargs="*", help="the coding task to scout for")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository directory (default: current directory)")
    parser.add_argument("--budget", type=int, help="approximate output token budget")
    parser.add_argument("--max-files", type=int, help="maximum selected files")
    parser.add_argument("--max-file-bytes", type=int, help="maximum bytes read from one file")
    parser.add_argument("--include", action="append", default=[], metavar="GLOB", help="only consider matching paths; repeatable")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="exclude matching paths; repeatable")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, metavar="PATH", help="write to a file instead of stdout")
    parser.add_argument("--no-git", action="store_true", help="scan the filesystem instead of using Git discovery and status")
    parser.add_argument("--no-redact", action="store_true", help="disable secret redaction (use with care)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _resolve_root(path: Path, use_git: bool) -> Path:
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"not a directory: {path}")
    git_root = repository_root(path) if use_git else None
    return git_root or path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "init":
        init_parser = argparse.ArgumentParser(prog="scoutctx init", description="Create a starter .scoutctx.toml")
        init_parser.add_argument("--root", type=Path, default=Path.cwd())
        args = init_parser.parse_args(argv[1:])
        try:
            root = _resolve_root(args.root, use_git=True)
            path = initialize(root)
        except (OSError, ValueError, FileExistsError) as exc:
            print(f"scoutctx: {exc}", file=sys.stderr)
            return 2
        print(f"Created {path}")
        return 0

    args = _parser().parse_args(argv)
    try:
        root = _resolve_root(args.root, use_git=not args.no_git)
        settings = load_settings(root)
        if args.budget is not None:
            if args.budget < 256:
                raise ValueError("--budget must be at least 256")
            settings.budget = args.budget
        if args.max_files is not None:
            if args.max_files < 1:
                raise ValueError("--max-files must be positive")
            settings.max_files = args.max_files
        if args.max_file_bytes is not None:
            if args.max_file_bytes < 1024:
                raise ValueError("--max-file-bytes must be at least 1024")
            settings.max_file_bytes = args.max_file_bytes
        settings.include.extend(args.include)
        settings.exclude.extend(args.exclude)
        if args.no_redact:
            settings.redact = False
        if args.output:
            resolved_output = args.output.expanduser().resolve()
            if resolved_output.is_relative_to(root):
                settings.exclude.append(resolved_output.relative_to(root).as_posix())

        task = " ".join(args.task).strip() or "Understand this codebase and identify the relevant architecture"
        brief = generate(root, task, settings, use_git=not args.no_git)
        output = render_json(brief) if args.format == "json" else render_markdown(brief)
        if args.output:
            args.output.expanduser().write_text(output, encoding="utf-8")
            print(
                f"Wrote {args.output} ({brief.stats.selected} files, ~{brief.stats.estimated_tokens:,} tokens)",
                file=sys.stderr,
            )
        else:
            sys.stdout.write(output)
    except (OSError, ValueError) as exc:
        print(f"scoutctx: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
