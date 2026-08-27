from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest

from scoutctx.framework import ContextResult, ScoutCTX, build_context
from scoutctx.providers import ContextDocument, StaticProvider


class FrameworkTests(unittest.TestCase):
    def test_builds_portable_markdown_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "auth.py").write_text(
                "API_KEY=abcdefghijklmnopqrstuvwxyz\ndef authenticate(): return True\n",
                encoding="utf-8",
            )

            result = build_context(
                "  repair authentication  ",
                root=root,
                budget=500,
                use_git=False,
            )

            self.assertIsInstance(result, ContextResult)
            self.assertEqual(result.format, "markdown")
            self.assertIn("ScoutCTX brief", result.content)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", result.content)
            self.assertEqual(result.metadata["task"], "repair authentication")
            self.assertEqual(result.metadata["root_name"], root.name)
            self.assertNotIn(str(root), json.dumps(result.metadata))
            self.assertEqual(result.metadata["budget"], 500)
            self.assertEqual(result.metadata["selected_files"], ["auth.py"])
            self.assertEqual(result.metadata["changed"], 0)
            self.assertEqual(result.metadata["discovered_files"], 1)
            self.assertEqual(result.metadata["readable_files"], 1)
            self.assertGreater(result.metadata["estimated_tokens"], 0)

    def test_result_has_versioned_defensive_dictionary(self) -> None:
        result = ContextResult("context", "markdown", {"selected_files": ["app.py"]})
        payload = result.to_dict()

        self.assertEqual(
            payload,
            {
                "schema_version": "1",
                "content": "context",
                "format": "markdown",
                "metadata": {"selected_files": ["app.py"]},
            },
        )
        payload["metadata"]["selected_files"].append("changed.py")
        self.assertEqual(result.metadata["selected_files"], ["app.py"])
        with self.assertRaises(FrozenInstanceError):
            result.content = "different"  # type: ignore[misc]

    def test_json_format_and_project_settings_with_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".scoutctx.toml").write_text(
                "[scoutctx]\nbudget = 300\nmax_files = 1\nredact = true\nexclude = ['ignored.py']\n",
                encoding="utf-8",
            )
            (root / "app.py").write_text("TOKEN=abcdefghijklmnopqrstuvwxyz", encoding="utf-8")
            (root / "ignored.py").write_text("ignored = True", encoding="utf-8")

            result = build_context(
                "inspect app",
                root=root,
                budget=600,
                max_files=2,
                format="json",
                use_git=False,
                redact=False,
            )
            content = json.loads(result.content)

            self.assertEqual(result.format, "json")
            self.assertEqual(result.metadata["budget"], 600)
            self.assertFalse(result.metadata["redacted"])
            self.assertIn("app.py", result.metadata["selected_files"])
            self.assertNotIn("ignored.py", result.metadata["selected_files"])
            self.assertEqual(content["schema_version"], "1")
            self.assertIn("abcdefghijklmnopqrstuvwxyz", result.content)

    def test_reusable_client_accepts_per_call_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text("def main(): pass\n" + "x" * 2_000, encoding="utf-8")
            client = ScoutCTX(root, budget=500, max_file_bytes=1024, use_git=False)

            result = client.context("find main", format="json", max_files=1)
            content = json.loads(result.content)

            self.assertEqual(result.format, "json")
            self.assertEqual(result.metadata["budget"], 500)
            self.assertEqual(result.metadata["selected_files"], ["main.py"])
            self.assertTrue(content["files"][0]["truncated"])

    def test_provider_context_is_budgeted_redacted_and_portable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "worker.py").write_text("def retry(): return True\n", encoding="utf-8")
            providers = {
                "handbook": StaticProvider(
                    [
                        ContextDocument(
                            id="retry-policy",
                            source="handbook",
                            weight=10,
                            content=(
                                "Retry ownership: platform team.\n"
                                "API_TOKEN=abcdefghijklmnopqrstuvwxyz\n"
                            ),
                        )
                    ]
                )
            }

            markdown = build_context(
                "change retry policy",
                root=root,
                budget=600,
                use_git=False,
                providers=providers,
            )
            structured = build_context(
                "change retry policy",
                root=root,
                budget=600,
                use_git=False,
                providers=providers,
                format="json",
            )

            self.assertIn("## Connected knowledge", markdown.content)
            self.assertIn("Retry ownership", markdown.content)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", markdown.content)
            self.assertEqual(
                markdown.metadata["provider_documents"],
                [{"id": "retry-policy", "source": "handbook"}],
            )
            payload = json.loads(structured.content)
            self.assertEqual(payload["provider_context"][0]["id"], "retry-policy")
            self.assertNotIn(str(root), json.dumps(structured.to_dict()))

    def test_validates_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file_path = root / "file.py"
            file_path.write_text("pass\n", encoding="utf-8")

            invalid_calls = (
                lambda: build_context("  ", root=root),
                lambda: build_context("task", root=root / "missing"),
                lambda: build_context("task", root=file_path),
                lambda: build_context("task", root=root, format="xml"),
                lambda: build_context("task", root=root, budget=255),
                lambda: build_context("task", root=root, max_files=0),
                lambda: build_context("task", root=root, max_file_bytes=1023),
                lambda: build_context("task", root=root, include="*.py"),
                lambda: build_context("task", root=root, budget=500.5),
                lambda: build_context("task", root=root, max_files=2.5),
                lambda: build_context("task", root=root, use_git="yes"),
                lambda: build_context("task", root=root, redact="no"),
            )
            for call in invalid_calls:
                with self.subTest(call=call), self.assertRaises(ValueError):
                    call()


if __name__ == "__main__":
    unittest.main()
