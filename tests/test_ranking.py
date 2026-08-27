from __future__ import annotations

import unittest

from scoutctx.models import Candidate
from scoutctx.ranking import excerpt, rank, terms_for


class RankingTests(unittest.TestCase):
    def test_terms_are_deduplicated_and_noise_is_removed(self) -> None:
        self.assertEqual(terms_for("Fix the flaky auth-token auth test"), ["flaky", "auth", "token", "test"])

    def test_path_and_git_signals_rank_relevant_file_first(self) -> None:
        files = [
            Candidate("docs/overview.md", "authentication authentication", 100),
            Candidate("src/auth/token.py", "def issue(): pass", 100),
            Candidate("src/unrelated.py", "pass", 10),
        ]
        ranked = rank(files, "repair auth token", {"src/auth/token.py"})
        self.assertEqual(ranked[0].path, "src/auth/token.py")
        self.assertIn("changed in Git", ranked[0].reasons)

    def test_excerpt_centers_task_matches(self) -> None:
        content = "\n".join(f"line {index}" for index in range(50)) + "\nAUTH_FAILURE\n" + "\n".join(
            f"tail {index}" for index in range(50)
        )
        result, truncated = excerpt(content, ["auth_failure"], 300)
        self.assertTrue(truncated)
        self.assertIn("AUTH_FAILURE", result)
        self.assertNotIn("line 0\n", result)


if __name__ == "__main__":
    unittest.main()

