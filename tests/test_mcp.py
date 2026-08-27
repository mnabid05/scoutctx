from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scoutctx import mcp


@dataclass
class _ContextResult:
    content: str = "# Focused context\n\n`src/app.py`"
    metadata: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {"selected_files": 1, "format": "markdown"}

    def to_dict(self) -> dict[str, object]:
        return {"content": self.content, "metadata": self.metadata}


def _serve(*messages: object, root: str | Path | None = None) -> list[dict[str, object]]:
    incoming = StringIO("".join(json.dumps(message) + "\n" for message in messages))
    outgoing = StringIO()
    mcp.serve(incoming, outgoing, root=root)
    return [json.loads(line) for line in outgoing.getvalue().splitlines()]


class McpTests(unittest.TestCase):
    def test_legacy_initialize_echoes_requested_version_and_notification_is_silent(self) -> None:
        responses = _serve(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        self.assertEqual(len(responses), 1)
        result = responses[0]["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")
        self.assertEqual(result["serverInfo"]["name"], "scoutctx")
        self.assertEqual(result["capabilities"], {"tools": {}})

    def test_modern_server_discovery_is_stateless_and_cacheable(self) -> None:
        response = _serve(
            {
                "jsonrpc": "2.0",
                "id": "discover",
                "method": "server/discover",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            }
        )[0]

        result = response["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertEqual(result["supportedVersions"], [mcp.PROTOCOL_VERSION])
        self.assertEqual(result["capabilities"], {"tools": {}})
        self.assertEqual(result["ttlMs"], 300_000)
        self.assertEqual(result["cacheScope"], "public")
        self.assertEqual(result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "scoutctx")

    def test_tools_list_has_portable_context_schema(self) -> None:
        response = _serve({"jsonrpc": "2.0", "id": "tools", "method": "tools/list"})[0]

        tool = response["result"]["tools"][0]
        self.assertEqual(
            [item["name"] for item in response["result"]["tools"]],
            ["scout_context", "scout_session_context"],
        )
        self.assertEqual(tool["name"], "scout_context")
        schema = tool["inputSchema"]
        self.assertEqual(schema["required"], ["task"])
        self.assertEqual(schema["properties"]["format"]["enum"], ["markdown", "json"])
        self.assertEqual(schema["properties"]["budget"]["minimum"], 256)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(response["result"]["resultType"], "complete")
        self.assertEqual(response["result"]["ttlMs"], 300_000)
        self.assertEqual(response["result"]["cacheScope"], "public")

    @patch("scoutctx.framework.build_context")
    def test_tools_call_passes_all_arguments_and_returns_both_content_forms(self, build_context) -> None:
        build_context.return_value = _ContextResult()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            request = {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "scout_context",
                    "arguments": {
                        "task": "  fix auth  ",
                        "root": "project",
                        "budget": 1200,
                        "max_files": 8,
                        "format": "json",
                    },
                },
            }
            response = _serve(request, root=root)[0]

        build_context.assert_called_once_with(
            task="fix auth",
            root=project.resolve(),
            budget=1200,
            max_files=8,
            format="json",
        )
        result = response["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertEqual(result["content"], [{"type": "text", "text": _ContextResult().content}])
        self.assertEqual(result["structuredContent"], {"metadata": _ContextResult().metadata})
        self.assertFalse(result["isError"])

    @patch("scoutctx.framework.build_context")
    def test_tools_call_uses_server_defaults(self, build_context) -> None:
        build_context.return_value = _ContextResult()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _serve(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "scout_context", "arguments": {"task": "map code"}},
                },
                root=root,
            )

        build_context.assert_called_once_with(
            task="map code",
            root=root,
            budget=None,
            max_files=None,
            format="markdown",
        )

    @patch("scoutctx.framework.build_context")
    def test_modern_tool_call_needs_no_initialize_handshake(self, build_context) -> None:
        build_context.return_value = _ContextResult()

        response = _serve(
            {
                "jsonrpc": "2.0",
                "id": "modern-call",
                "method": "tools/call",
                "params": {
                    "name": "scout_context",
                    "arguments": {"task": "find the parser"},
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            }
        )[0]

        self.assertEqual(response["id"], "modern-call")
        self.assertFalse(response["result"]["isError"])
        build_context.assert_called_once()

    def test_real_context_result_does_not_expose_absolute_repository_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "parser.py").write_text("def parse(value): return value\n", encoding="utf-8")

            response = _serve(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "scout_context",
                        "arguments": {
                            "task": "find parser",
                            "budget": 512,
                        },
                    },
                },
                root=root,
            )[0]

            result = response["result"]
            self.assertFalse(result["isError"])
            self.assertIn("parser.py", result["content"][0]["text"])
            self.assertNotIn(str(root), json.dumps(result))

    def test_root_is_confined_and_session_context_is_portable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("def portable(): return True\n", encoding="utf-8")
            from scoutctx.sessions import SessionManager

            manager = SessionManager(root)
            session = manager.start("keep context portable", worktree=False)
            manager.note(session.id, "Preserve the public function.")

            escaped, session_response = _serve(
                {
                    "jsonrpc": "2.0",
                    "id": "escape",
                    "method": "tools/call",
                    "params": {
                        "name": "scout_context",
                        "arguments": {"task": "scan elsewhere", "root": ".."},
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": "session",
                    "method": "tools/call",
                    "params": {
                        "name": "scout_session_context",
                        "arguments": {"session_id": session.id, "budget": 512},
                    },
                },
                root=root,
            )

            self.assertTrue(escaped["result"]["isError"])
            self.assertIn("configured server root", escaped["result"]["content"][0]["text"])
            self.assertFalse(session_response["result"]["isError"])
            self.assertIn("Preserve the public function", session_response["result"]["content"][0]["text"])

    @patch("scoutctx.framework.build_context")
    def test_expected_tool_failure_is_reported_without_stopping_server(self, build_context) -> None:
        build_context.side_effect = ValueError("budget is invalid")
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "scout_context", "arguments": {"task": "map code"}},
        }
        listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}

        responses = _serve(call, listing)

        self.assertTrue(responses[0]["result"]["isError"])
        self.assertIn("budget is invalid", responses[0]["result"]["content"][0]["text"])
        self.assertEqual(responses[1]["id"], 2)
        self.assertIn("tools", responses[1]["result"])

    @patch("scoutctx.framework.build_context")
    def test_unexpected_tool_failure_does_not_leak_details(self, build_context) -> None:
        build_context.side_effect = RuntimeError("secret implementation detail")
        response = _serve(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "scout_context", "arguments": {"task": "map code"}},
            }
        )[0]

        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertNotIn("secret implementation detail", result["content"][0]["text"])

    def test_protocol_and_validation_errors_are_json_rpc_errors(self) -> None:
        incoming = StringIO(
            "not-json\n"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "missing"})
            + "\n"
            + json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "scout_context", "arguments": {"task": ""}},
                }
            )
            + "\n"
        )
        outgoing = StringIO()

        mcp.serve(incoming, outgoing)

        responses = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual([response["error"]["code"] for response in responses], [-32700, -32601, -32602])
        self.assertEqual(responses[0]["id"], None)

    def test_unknown_and_malformed_arguments_are_rejected(self) -> None:
        invalid_arguments = [
            None,
            {"task": "ok", "extra": True},
            {"task": "ok", "root": ""},
            {"task": "ok", "budget": True},
            {"task": "ok", "budget": 255},
            {"task": "ok", "max_files": 0},
            {"task": "ok", "format": "xml"},
        ]
        messages = [
            {
                "jsonrpc": "2.0",
                "id": index,
                "method": "tools/call",
                "params": {"name": "scout_context", "arguments": arguments},
            }
            for index, arguments in enumerate(invalid_arguments)
        ]

        responses = _serve(*messages)

        self.assertEqual(len(responses), len(messages))
        self.assertTrue(all(response["error"]["code"] == -32602 for response in responses))

    def test_unknown_notifications_do_not_receive_replies(self) -> None:
        responses = _serve(
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}},
            {"jsonrpc": "1.0", "method": "broken-notification"},
        )
        self.assertEqual(responses, [])

    def test_each_reply_is_compact_line_delimited_json_and_flushed(self) -> None:
        class FlushCountingStream(StringIO):
            flushes = 0

            def flush(self) -> None:
                self.flushes += 1

        output = FlushCountingStream()
        mcp.serve(
            StringIO('{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n\n'),
            output,
        )

        self.assertEqual(output.flushes, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertNotIn(": ", output.getvalue())


if __name__ == "__main__":
    unittest.main()
