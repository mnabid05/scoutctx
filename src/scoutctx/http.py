"""Dependency-free HTTP adapter for the ScoutCTX context framework."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import framework


MAX_REQUEST_BYTES = 1024 * 1024
_REQUEST_FIELDS = {"task", "root", "budget", "max_files", "format"}


class _ContextHandler(BaseHTTPRequestHandler):
    """Serve the small, local ScoutCTX HTTP API."""

    configured_root: Path = Path.cwd().resolve()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress the standard per-request stderr log."""

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_error(self, status: int, message: str) -> None:
        self._write_json(status, {"error": message})

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if urlsplit(self.path).path == "/health":
            self._write_json(200, {"status": "ok", "service": "scoutctx"})
            return
        self._write_error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if urlsplit(self.path).path != "/v1/context":
            self._write_error(404, "not found")
            return

        try:
            payload = self._read_payload()
            task, options = self._validate_payload(payload)
            result = framework.build_context(task, **options)
        except _RequestTooLarge as exc:
            self._write_error(413, str(exc))
            return
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._write_error(400, f"invalid JSON: {exc}")
            return
        except (TypeError, ValueError, OSError) as exc:
            self._write_error(400, str(exc))
            return

        self._write_json(200, result.to_dict())

    def _read_payload(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length header is required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer") from exc
        if length < 0:
            raise ValueError("Content-Length cannot be negative")
        if length > MAX_REQUEST_BYTES:
            raise _RequestTooLarge(f"request body exceeds {MAX_REQUEST_BYTES} bytes")

        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def _validate_payload(self, payload: Any) -> tuple[str, dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")

        unknown = sorted(set(payload) - _REQUEST_FIELDS)
        if unknown:
            raise ValueError(f"unknown field: {unknown[0]}")

        task = payload.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")

        validators: dict[str, type] = {
            "root": str,
            "budget": int,
            "max_files": int,
            "format": str,
        }
        options: dict[str, Any] = {}
        for name, expected_type in validators.items():
            if name not in payload:
                continue
            value = payload[name]
            if not isinstance(value, expected_type) or expected_type is int and isinstance(value, bool):
                raise ValueError(f"{name} must be {expected_type.__name__}")
            options[name] = value

        boundary = self.configured_root
        requested = Path(options.pop("root")) if "root" in options else boundary
        if not requested.is_absolute():
            requested = boundary / requested
        requested = requested.expanduser().resolve()
        if not requested.is_relative_to(boundary):
            raise ValueError("root must remain beneath the configured server root")
        options["root"] = requested
        return task.strip(), options


class _RequestTooLarge(ValueError):
    """Signal that the declared request body exceeds the HTTP API limit."""


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    root: str | Path | None = None,
) -> ThreadingHTTPServer:
    """Create a configured ScoutCTX HTTP server without starting it."""

    configured_root = Path(root if root is not None else Path.cwd()).expanduser().resolve()
    if not configured_root.is_dir():
        raise ValueError(f"not a directory: {configured_root}")

    class ContextHandler(_ContextHandler):
        pass

    ContextHandler.configured_root = configured_root
    return ThreadingHTTPServer((host, port), ContextHandler)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    root: str | Path | None = None,
) -> None:
    """Run the ScoutCTX HTTP adapter until interrupted."""

    server = create_server(host=host, port=port, root=root)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
