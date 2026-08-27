from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest

from scoutctx.scanner import discover_paths, scan


class ScannerTests(unittest.TestCase):
    def test_discovers_text_and_respects_ignores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('hello')", encoding="utf-8")
            (root / "debug.log").write_text("noise", encoding="utf-8")
            (root / "image.bin").write_bytes(b"hello\0world")
            (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
            (root / ".scoutctx" / "sessions").mkdir(parents=True)
            (root / ".scoutctx" / "sessions" / "context.md").write_text(
                "private session state", encoding="utf-8"
            )

            paths = discover_paths(root, use_git=False)
            candidates, _, stats = scan(root, max_file_bytes=4096, use_git=False)

            self.assertIn("src/app.py", paths)
            self.assertNotIn("debug.log", paths)
            self.assertFalse(any(path.startswith(".scoutctx/") for path in paths))
            self.assertEqual([item.path for item in candidates if item.path == "src/app.py"], ["src/app.py"])
            self.assertEqual(stats.skipped_binary, 1)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_skips_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.txt"
            target.write_text("inside", encoding="utf-8")
            (root / "link.txt").symlink_to(target)

            candidates, _, _ = scan(root, max_file_bytes=4096, use_git=False)

            self.assertEqual([item.path for item in candidates], ["target.txt"])


if __name__ == "__main__":
    unittest.main()
