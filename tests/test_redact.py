from __future__ import annotations

import unittest

from scoutctx.redact import REDACTED, redact_secrets


class RedactionTests(unittest.TestCase):
    def test_redacts_assignments_and_known_token_shapes(self) -> None:
        source = "\n".join(
            [
                "API_KEY='super-secret-value'",
                "password: hunter2",
                "safe_value = hello",
                "github_pat_abcdefghijklmnopqrstuvwxyz123456",
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            ]
        )

        redacted, count = redact_secrets(source)

        self.assertNotIn("super-secret-value", redacted)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("github_pat_abcdefghijklmnopqrstuvwxyz123456", redacted)
        self.assertIn("safe_value = hello", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertEqual(redacted.count(REDACTED), 4)
        self.assertEqual(count, 4)

    def test_redacts_private_key_block(self) -> None:
        source = "before\n-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----\nafter"
        redacted, count = redact_secrets(source)
        self.assertEqual(redacted, f"before\n{REDACTED}\nafter")
        self.assertEqual(count, 1)

    def test_does_not_redact_detector_source_code(self) -> None:
        source = '_PRIVATE_KEY = re.compile(\n    r"PRIVATE KEY"\n)'
        redacted, count = redact_secrets(source)
        self.assertEqual(redacted, source)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
