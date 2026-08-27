from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scoutctx.brief import generate
from scoutctx.config import Settings
from scoutctx.render import render_json, render_markdown


class BriefTests(unittest.TestCase):
    def test_generation_is_focused_redacted_and_budgeted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "auth.py").write_text(
                "API_KEY=abcdefghijklmnopqrstuvwxyz\n" + "def authenticate():\n    return True\n" * 100,
                encoding="utf-8",
            )
            (root / "colors.css").write_text("body { color: red; }", encoding="utf-8")
            settings = Settings(budget=800, max_files=2)

            brief = generate(root, "debug authentication API", settings, use_git=False)
            markdown = render_markdown(brief)

            self.assertEqual(brief.files[0].path, "auth.py")
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", markdown)
            self.assertIn("REDACTED_BY_SCOUTCTX", markdown)
            self.assertLessEqual(brief.stats.estimated_tokens, 900)

    def test_json_has_versioned_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.go").write_text("package main", encoding="utf-8")
            brief = generate(root, "understand main", Settings(budget=500), use_git=False)
            payload = json.loads(render_json(brief))
            self.assertEqual(payload["schema_version"], "1")
            self.assertEqual(payload["files"][0]["path"], "main.go")

    def test_large_repository_map_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(150):
                package = root / f"package_{index:03d}"
                package.mkdir()
                (package / "implementation_with_a_descriptive_name.py").write_text("value = 1\n", encoding="utf-8")

            brief = generate(root, "find implementation", Settings(budget=256), use_git=False)
            markdown = render_markdown(brief)

            self.assertIn("more files", markdown)
            self.assertLessEqual(brief.stats.estimated_tokens, 320)


if __name__ == "__main__":
    unittest.main()
