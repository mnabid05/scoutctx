from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scoutctx.redact import REDACTED
from scoutctx.sessions import SessionManager


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repository(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "ScoutCTX Tests")
    _git(root, "config", "user.email", "tests@scoutctx.invalid")
    (root / "app.py").write_text("def improve_ranking():\n    return True\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-q", "-m", "initial")


class SessionManagerTests(unittest.TestCase):
    def test_default_start_creates_deterministic_isolated_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root)
            manager = SessionManager(root)

            first = manager.start("Improve ranking!!!")
            second = manager.start("Improve ranking!!!")

            self.assertEqual(first.id, "improve-ranking-01")
            self.assertEqual(second.id, "improve-ranking-02")
            self.assertEqual(first.branch, "scoutctx/improve-ranking-01")
            self.assertEqual(first.worktree, ".scoutctx/worktrees/improve-ranking-01")
            first_root = manager.working_directory(first)
            second_root = manager.working_directory(second)
            self.assertTrue((first_root / ".git").is_file())
            self.assertTrue((first_root / "app.py").is_file())
            self.assertNotEqual(first_root, second_root)

            # Opening ScoutCTX from a linked worktree still finds shared state.
            linked_manager = SessionManager(first_root)
            self.assertEqual(linked_manager.root, root.resolve())
            self.assertEqual(linked_manager.get(second.id), second)

    def test_lifecycle_persists_notes_context_and_archives_without_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root)
            manager = SessionManager(root)
            session = manager.start("Improve ranking", worktree=False)

            updated = manager.note(
                session.id,
                "keep it deterministic\nAPI_TOKEN=abcdefghijklmnopqrstuvwxyz",
            )
            self.assertIn("keep it deterministic", updated.notes[0])
            self.assertIn(REDACTED, updated.notes[0])
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", updated.notes[0])

            markdown = manager.context(session.id, budget=500)
            self.assertEqual(markdown.format, "markdown")
            self.assertIn("# Session continuity", markdown.content)
            self.assertIn("keep it deterministic", markdown.content)
            self.assertTrue((manager.sessions_root / session.id / "context.md").is_file())

            json_result = manager.context(session.id, budget=500, format="json")
            payload = json.loads(json_result.content)
            self.assertEqual(payload["session"]["id"], session.id)
            self.assertEqual(payload["session"]["notes"], updated.notes)

            session_directory = manager.sessions_root / session.id
            archived = manager.archive(session.id)
            self.assertEqual(archived.status, "archived")
            self.assertTrue(session_directory.is_dir())
            self.assertEqual(manager.list(), [])
            self.assertEqual(manager.list(include_archived=True), [archived])

    def test_rejects_unsafe_ids_and_requires_git_for_default_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(directory)

            with self.assertRaises(ValueError):
                manager.start("a task")
            session = manager.start("a task", worktree=False)
            self.assertEqual(session.id, "a-task-01")
            with self.assertRaises(ValueError):
                manager.get("../session")
            with self.assertRaises(KeyError):
                manager.get("missing-01")
            with self.assertRaises(ValueError):
                manager.note(session.id, "   ")

    def test_redacts_secrets_from_recorded_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(directory)
            session = manager.start("use provider", worktree=False)

            manager.record_run(
                session.id,
                ["provider", "--api-key", "sk-abcdefghijklmnopqrstuvwxyz123456", "--token=value"],
            )
            loaded = manager.get(session.id)

            self.assertEqual(loaded.harnesses, ["provider"])
            self.assertEqual(
                loaded.runs,
                [["provider", "--api-key", REDACTED, f"--token={REDACTED}"]],
            )
            persisted = (manager.sessions_root / session.id / "session.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", persisted)


if __name__ == "__main__":
    unittest.main()
