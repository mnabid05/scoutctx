"""Dependency-free MCP server for exposing ScoutCTX over standard I/O.

The transport deliberately uses one JSON-RPC message per line.  This keeps the
adapter useful in small environments without adding an MCP SDK dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import sys
from typing import Any, TextIO

from . import __version__


JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSION = "2025-11-25"
# Kept as a descriptive alias for callers that imported the first adapter
# draft.  PROTOCOL_VERSION is the canonical public name.
MCP_PROTOCOL_VERSION = PROTOCOL_VERSION
TOOL_NAME = "scout_context"
SESSION_TOOL_NAME = "scout_session_context"

TOOL_DEFINITION: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Build a focused, token-budgeted, secret-redacted context package "
        "for an AI coding task."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "minLength": 1,
                "description": "The coding task the context should support.",
            },
            "root": {
                "type": "string",
                "description": "Repository directory; defaults to the server root.",
            },
            "budget": {
                "type": "integer",
                "minimum": 256,
                "description": "Approximate maximum output token count.",
            },
            "max_files": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum number of repository files to include.",
            },
            "format": {
                "type": "string",
                "enum": ["markdown", "json"],
                "description": "Rendered context format.",
            },
        },
        "required": ["task"],
        "additionalProperties": False,
    },
    "outputSchema": {
        "type": "object",
        "properties": {"metadata": {"type": "object"}},
        "required": ["metadata"],
        "additionalProperties": False,
    },
}

SESSION_TOOL_DEFINITION: dict[str, Any] = {
    "name": SESSION_TOOL_NAME,
    "description": (
        "Rebuild context for a persistent ScoutCTX session, including its "
        "durable task, notes, harness history, and current worktree."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "minLength": 1,
                "description": "The ScoutCTX session identifier.",
            },
            "budget": {
                "type": "integer",
                "minimum": 256,
                "description": "Approximate maximum output token count.",
            },
            "max_files": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum number of repository files to include.",
            },
            "format": {
                "type": "string",
                "enum": ["markdown", "json"],
                "description": "Rendered context format.",
            },
        },
        "required": ["session_id"],
        "additionalProperties": False,
    },
    "outputSchema": TOOL_DEFINITION["outputSchema"],
}


class _RequestError(Exception):
    """A JSON-RPC error safe to return to an MCP client."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _response(request_id: Any, *, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _validate_arguments(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise _RequestError(-32602, "tools/call arguments must be an object")

    allowed = {"task", "root", "budget", "max_files", "format"}
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise _RequestError(-32602, f"unknown tool argument: {unknown[0]}")

    task = arguments.get("task")
    if not isinstance(task, str) or not task.strip():
        raise _RequestError(-32602, "task must be a non-empty string")

    root = arguments.get("root")
    if root is not None and (not isinstance(root, str) or not root.strip()):
        raise _RequestError(-32602, "root must be a non-empty string")

    budget = arguments.get("budget")
    if budget is not None and (
        isinstance(budget, bool) or not isinstance(budget, int) or budget < 256
    ):
        raise _RequestError(-32602, "budget must be an integer of at least 256")

    max_files = arguments.get("max_files")
    if max_files is not None and (
        isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1
    ):
        raise _RequestError(-32602, "max_files must be a positive integer")

    output_format = arguments.get("format", "markdown")
    if output_format not in {"markdown", "json"}:
        raise _RequestError(-32602, "format must be 'markdown' or 'json'")

    return {
        "task": task.strip(),
        "root": root,
        "budget": budget,
        "max_files": max_files,
        "format": output_format,
    }


def _validate_session_arguments(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise _RequestError(-32602, "tools/call arguments must be an object")
    allowed = {"session_id", "budget", "max_files", "format"}
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise _RequestError(-32602, f"unknown tool argument: {unknown[0]}")

    session_id = arguments.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise _RequestError(-32602, "session_id must be a non-empty string")
    budget = arguments.get("budget")
    if budget is not None and (
        isinstance(budget, bool) or not isinstance(budget, int) or budget < 256
    ):
        raise _RequestError(-32602, "budget must be an integer of at least 256")
    max_files = arguments.get("max_files")
    if max_files is not None and (
        isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1
    ):
        raise _RequestError(-32602, "max_files must be a positive integer")
    output_format = arguments.get("format", "markdown")
    if output_format not in {"markdown", "json"}:
        raise _RequestError(-32602, "format must be 'markdown' or 'json'")
    return {
        "session_id": session_id.strip(),
        "budget": budget,
        "max_files": max_files,
        "format": output_format,
    }


def _confined_root(requested: str | Path | None, server_root: str | Path | None) -> Path:
    """Resolve a tool root without allowing calls outside the server boundary."""

    boundary = Path(server_root if server_root is not None else Path.cwd()).expanduser().resolve()
    if not boundary.is_dir():
        raise ValueError(f"server root is not a directory: {boundary}")
    candidate = Path(requested) if requested is not None else boundary
    if not candidate.is_absolute():
        candidate = boundary / candidate
    candidate = candidate.expanduser().resolve()
    if not candidate.is_relative_to(boundary):
        raise ValueError("root must remain beneath the configured server root")
    return candidate


def _tool_error(message: str) -> dict[str, Any]:
    """Return an MCP-level tool failure rather than terminating the server."""

    return {
        "resultType": "complete",
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _call_tool(params: Any, server_root: str | Path | None) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise _RequestError(-32602, "tools/call params must be an object")
    name = params.get("name")
    if name not in {TOOL_NAME, SESSION_TOOL_NAME}:
        raise _RequestError(-32602, f"unknown tool: {name!r}")

    if name == SESSION_TOOL_NAME:
        arguments = _validate_session_arguments(params.get("arguments", {}))
    else:
        arguments = _validate_arguments(params.get("arguments", {}))

    try:
        call_root = _confined_root(None, server_root)
        if name == SESSION_TOOL_NAME:
            from .sessions import SessionManager

            session_id = arguments.pop("session_id")
            context = SessionManager(call_root).context(session_id, **arguments)
        else:
            # Imported lazily so importing this transport remains cheap and so
            # the core can evolve independently of the protocol adapter.
            from .framework import build_context

            call_root = _confined_root(arguments.pop("root"), server_root)
            context = build_context(root=call_root, **arguments)
        metadata = context.metadata
        if not isinstance(metadata, Mapping):
            raise TypeError("context metadata must be a mapping")
        if not isinstance(context.content, str):
            raise TypeError("context content must be a string")
        # Exercise the public serialization contract here.  In addition to
        # catching incomplete framework implementations, this guarantees the
        # result is JSON-safe before it reaches the transport writer.
        json.dumps(context.to_dict(), ensure_ascii=False)
        return {
            "resultType": "complete",
            "content": [{"type": "text", "text": context.content}],
            "structuredContent": {"metadata": dict(metadata)},
            "isError": False,
        }
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return _tool_error(f"ScoutCTX could not build context: {exc}")
    except Exception:
        # A malformed repository or extension must never take down a long-lived
        # MCP process.  Avoid exposing implementation details to the client.
        return _tool_error("ScoutCTX could not build context due to an internal error")


def _dispatch(message: Any, server_root: str | Path | None) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request")

    request_id = message.get("id")
    is_notification = "id" not in message
    if message.get("jsonrpc") != JSONRPC_VERSION or not isinstance(message.get("method"), str):
        if is_notification:
            return None
        return _error(request_id, -32600, "Invalid Request")

    method = message["method"]
    params = message.get("params", {})
    if method == "notifications/initialized":
        return None
    if is_notification:
        return None

    try:
        if method == "server/discover":
            if not isinstance(params, dict):
                raise _RequestError(-32602, "server/discover params must be an object")
            return _response(
                request_id,
                result={
                    "resultType": "complete",
                    "supportedVersions": [PROTOCOL_VERSION],
                    "capabilities": {"tools": {}},
                    "_meta": {
                        "io.modelcontextprotocol/serverInfo": {
                            "name": "scoutctx",
                            "version": __version__,
                        }
                    },
                    "instructions": (
                        "Call scout_context with a coding task to receive focused, "
                        "redacted repository context."
                    ),
                    "ttlMs": 300_000,
                    "cacheScope": "public",
                },
            )
        if method == "initialize":
            if not isinstance(params, dict):
                raise _RequestError(-32602, "initialize params must be an object")
            requested_version = params.get("protocolVersion", LEGACY_PROTOCOL_VERSION)
            if not isinstance(requested_version, str):
                raise _RequestError(-32602, "protocolVersion must be a string")
            return _response(
                request_id,
                result={
                    "protocolVersion": requested_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "scoutctx", "version": __version__},
                },
            )
        if method == "tools/list":
            if not isinstance(params, dict):
                raise _RequestError(-32602, "tools/list params must be an object")
            return _response(
                request_id,
                result={
                    "resultType": "complete",
                    "tools": [TOOL_DEFINITION, SESSION_TOOL_DEFINITION],
                    "ttlMs": 300_000,
                    "cacheScope": "public",
                },
            )
        if method == "tools/call":
            return _response(request_id, result=_call_tool(params, server_root))
        raise _RequestError(-32601, "Method not found")
    except _RequestError as exc:
        return _error(request_id, exc.code, exc.message)


def serve(
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    root: str | Path | None = None,
) -> None:
    """Serve line-delimited MCP JSON-RPC messages until the input reaches EOF."""

    source = input_stream if input_stream is not None else sys.stdin
    destination = output_stream if output_stream is not None else sys.stdout

    for line in source:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            reply = _error(None, -32700, "Parse error")
        else:
            reply = _dispatch(message, root)
        if reply is not None:
            destination.write(json.dumps(reply, ensure_ascii=False, separators=(",", ":")) + "\n")
            destination.flush()


def main() -> int:
    """Run the ScoutCTX MCP server on standard input and output."""

    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
