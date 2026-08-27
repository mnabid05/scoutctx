from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scoutctx.harness import LaunchPlan, launch
from scoutctx.redact import REDACTED
from scoutctx.sessions import SessionManager


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )


def _repository(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "ScoutCTX Tests")
    _git(root, "config", "user.email", "tests@scoutctx.invalid")
    (root / "app.py").write_text("def model_context():\n    return True\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-q", "-m", "initial")


class HarnessTests(unittest.TestCase):
    def test_dry_run_expands_only_known_placeholders_without_recording(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root)
            manager = SessionManager(root)
            session = manager.start("Explain model context", worktree=False)

            plan = launch(
                manager,
                session.id,
                [
                    "any-model",
                    "--context={context}",
                    "{task}",
                    "{worktree}",
                    "{session}",
                    '{"literal": true}',
                ],
                dry_run=True,
                context_options={"budget": 500, "format": "json"},
                extra_env={"PROVIDER_API_KEY": "never-show-this"},
            )

            self.assertIsInstance(plan, LaunchPlan)
            self.assertEqual(plan.harness, "any-model")
            self.assertEqual(plan.command[1], f"--context={plan.context_file}")
            self.assertEqual(plan.command[2], session.task)
            self.assertEqual(plan.command[3], str(root.resolve()))
            self.assertEqual(plan.command[4], session.id)
            self.assertEqual(plan.command[5], '{"literal": true}')
            self.assertEqual(plan.cwd, root.resolve())
            self.assertEqual(plan.environment["SCOUTCTX_CONTEXT_FORMAT"], "json")
            self.assertEqual(plan.environment["SCOUTCTX_CONTEXT_FILE"], str(plan.context_file))
            self.assertNotIn("PROVIDER_API_KEY", plan.environment)
            self.assertNotIn("never-show-this", json.dumps(plan.to_dict()))
            self.assertEqual(manager.get(session.id).runs, [])
            self.assertTrue(plan.context_file.is_file())

    def test_launch_runs_argv_without_shell_and_passes_scoutctx_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _repository(root)
            helper = root / "capture.py"
            helper.write_text(
                """from __future__ import annotations
import json
import os
from pathlib import Path
import sys

keys = sorted(key for key in os.environ if key.startswith("SCOUTCTX_"))
Path("launch.json").write_text(json.dumps({
    "argv": sys.argv[1:],
    "cwd": str(Path.cwd()),
    "env": {key: os.environ[key] for key in keys},
    "extra": os.environ["HARNESS_TEST_VALUE"],
}), encoding="utf-8")
""",
                encoding="utf-8",
            )
            _git(root, "add", "capture.py")
            _git(root, "commit", "-q", "-m", "add harness")
            manager = SessionManager(root)
            session = manager.start("Give context to model")
            worktree = manager.working_directory(session)
            token = "sk-abcdefghijklmnopqrstuvwxyz123456"

            result = launch(
                manager,
                session.id,
                [
                    sys.executable,
                    "capture.py",
                    "{context}",
                    "{task}",
                    "{worktree}",
                    "{session}",
                    "literal; touch shell-was-used",
                    "--api-key",
                    token,
                ],
                context_options={"budget": 500},
                extra_env={"HARNESS_TEST_VALUE": "child-only"},
            )

            self.assertEqual(result.returncode, 0)
            payload = json.loads((worktree / "launch.json").read_text(encoding="utf-8"))
            context_file = Path(payload["argv"][0])
            self.assertTrue(context_file.is_file())
            self.assertEqual(payload["argv"][1:4], [session.task, str(worktree), session.id])
            self.assertEqual(payload["argv"][4], "literal; touch shell-was-used")
            self.assertEqual(payload["argv"][-1], token)
            self.assertFalse((worktree / "shell-was-used").exists())
            self.assertEqual(payload["cwd"], str(worktree))
            self.assertEqual(payload["extra"], "child-only")
            self.assertEqual(payload["env"]["SCOUTCTX_SESSION_ID"], session.id)
            self.assertEqual(payload["env"]["SCOUTCTX_CONTEXT_FILE"], str(context_file))
            self.assertEqual(payload["env"]["SCOUTCTX_CONTEXT_FORMAT"], "markdown")
            self.assertEqual(payload["env"]["SCOUTCTX_WORKTREE"], str(worktree))
            self.assertEqual(payload["env"]["SCOUTCTX_REPOSITORY"], root.name)

            recorded = manager.get(session.id)
            self.assertEqual(recorded.harnesses, [Path(sys.executable).name])
            self.assertEqual(recorded.runs[0][-1], REDACTED)
            self.assertEqual(recorded.runs[0][2:5], ["{context}", "{task}", "{worktree}"])
            self.assertNotIn(str(worktree), json.dumps(recorded.to_dict()))
            metadata = (manager.sessions_root / session.id / "session.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(token, metadata)
            self.assertNotIn("HARNESS_TEST_VALUE", metadata)
            self.assertNotIn("child-only", metadata)

    def test_validates_commands_environment_and_archived_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(directory)
            session = manager.start("test harness", worktree=False)

            for command in ([], [""], "model", ["model", 1]):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    launch(manager, session.id, command, dry_run=True)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                launch(
                    manager,
                    session.id,
                    ["model"],
                    dry_run=True,
                    extra_env={"INVALID": 1},  # type: ignore[dict-item]
                )
            manager.archive(session.id)
            with self.assertRaises(ValueError):
                launch(manager, session.id, ["model"], dry_run=True)


if __name__ == "__main__":
    unittest.main()
