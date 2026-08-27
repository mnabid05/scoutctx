from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from scoutctx.cli import main


class CliTests(unittest.TestCase):
    def test_init_then_generate_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("print('hi')", encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(["init", "--root", str(root)]), 0)
                self.assertEqual(
                    main(["map app", "--root", str(root), "--output", str(root / "brief.md")]),
                    0,
                )

            self.assertTrue((root / ".scoutctx.toml").exists())
            self.assertIn("ScoutCTX brief", (root / "brief.md").read_text(encoding="utf-8"))

    def test_rejects_tiny_budget(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            code = main(["task", "--budget", "10"])
        self.assertEqual(code, 2)
        self.assertIn("at least 256", stderr.getvalue())

    def test_existing_output_is_not_fed_back_into_brief(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "custom-brief.md"
            output.write_text("SELF_FEED_MARKER", encoding="utf-8")

            with redirect_stderr(StringIO()):
                code = main(["find marker", "--root", str(root), "--output", str(output), "--no-git"])

            self.assertEqual(code, 0)
            self.assertNotIn("SELF_FEED_MARKER", output.read_text(encoding="utf-8"))

    def test_session_lifecycle_and_dry_run_are_available_from_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "worker.py").write_text("def cancel(): return True\n", encoding="utf-8")

            started_output = StringIO()
            with redirect_stdout(started_output), redirect_stderr(StringIO()):
                code = main(
                    [
                        "session",
                        "start",
                        "add cancellation",
                        "--root",
                        str(root),
                        "--no-worktree",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            session = json.loads(started_output.getvalue())

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "session",
                            "note",
                            session["id"],
                            "Preserve cancel behavior",
                            "--root",
                            str(root),
                        ]
                    ),
                    0,
                )

            context_path = root / "portable-context.json"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "session",
                            "context",
                            session["id"],
                            "--root",
                            str(root),
                            "--budget",
                            "512",
                            "--format",
                            "json",
                            "--output",
                            str(context_path),
                        ]
                    ),
                    0,
                )
            payload = json.loads(context_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["session"]["id"], session["id"])
            self.assertIn("Preserve cancel behavior", payload["session"]["notes"])

            plan_output = StringIO()
            with redirect_stdout(plan_output), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "session",
                            "run",
                            "--root",
                            str(root),
                            "--dry-run",
                            session["id"],
                            "--",
                            "any-agent",
                            "--context={context}",
                        ]
                    ),
                    0,
                )
            plan = json.loads(plan_output.getvalue())
            self.assertEqual(plan["harness"], "any-agent")
            self.assertIn("--context=", plan["command"][1])


if __name__ == "__main__":
    unittest.main()
