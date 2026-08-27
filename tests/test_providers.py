from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from scoutctx.providers import (
    ContextDocument,
    ContextRequest,
    DirectoryProvider,
    ProviderRegistry,
    StaticProvider,
)


class ProviderModelTests(unittest.TestCase):
    def test_request_normalizes_root_and_document_copies_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata = {"team": "search"}
            request = ContextRequest("improve ranking", Path(directory) / ".", 1000)
            document = ContextDocument("handbook", "Use BM25.", "wiki", metadata=metadata)
            metadata["team"] = "changed"

            self.assertEqual(request.root, Path(directory).resolve())
            self.assertEqual(document.metadata["team"], "search")
            with self.assertRaises(TypeError):
                document.metadata["new"] = "value"  # type: ignore[index]

    def test_rejects_invalid_request_and_document_values(self) -> None:
        with self.assertRaises(ValueError):
            ContextRequest("", Path.cwd(), 1000)
        with self.assertRaises(ValueError):
            ContextRequest("task", Path.cwd(), 0)
        with self.assertRaises(ValueError):
            ContextDocument("id", "content", "source", weight=float("nan"))


class DirectoryProviderTests(unittest.TestCase):
    def test_collects_matching_text_deterministically_and_truncates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "knowledge").mkdir()
            (root / "knowledge" / "z.md").write_text("z" * 20, encoding="utf-8")
            (root / "knowledge" / "A.md").write_text("alpha", encoding="utf-8")
            (root / "knowledge" / "ignore.txt").write_text("ignored", encoding="utf-8")
            (root / "knowledge" / "binary.md").write_bytes(b"abc\0def")
            request = ContextRequest("task", root, 1000)
            provider = DirectoryProvider(
                "knowledge",
                globs=("*.md",),
                max_bytes=8,
                max_total_bytes=100,
                source="handbook",
                weight=2,
            )

            documents = provider.collect(request)

            self.assertEqual(
                [document.id for document in documents],
                ["handbook:knowledge/A.md", "handbook:knowledge/z.md"],
            )
            self.assertEqual(documents[1].content, "z" * 8)
            self.assertEqual(
                dict(documents[1].metadata),
                {"path": "knowledge/z.md", "size": 20, "truncated": True},
            )

    def test_stays_beneath_request_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = ContextRequest("task", root, 1000)
            provider = DirectoryProvider("../outside")

            with self.assertRaisesRegex(ValueError, "beneath the request root"):
                provider.collect(request)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_ignores_symlinked_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real.md").write_text("real", encoding="utf-8")
            (root / "link.md").symlink_to(root / "real.md")
            provider = DirectoryProvider(globs=("*.md",))

            documents = provider.collect(ContextRequest("task", root, 1000))

            self.assertEqual([document.id for document in documents], ["directory:real.md"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlinked_provider_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "knowledge").mkdir()
            (root / "knowledge" / "policy.md").write_text("policy", encoding="utf-8")
            (root / "linked-knowledge").symlink_to(root / "knowledge", target_is_directory=True)

            provider = DirectoryProvider("linked-knowledge", globs=("*.md",))

            with self.assertRaisesRegex(ValueError, "may not contain symlinks"):
                provider.collect(ContextRequest("task", root, 1000))


class ProviderRegistryTests(unittest.TestCase):
    def test_orders_documents_by_weight_source_and_id(self) -> None:
        registry = ProviderRegistry(
            {
                "z-provider": StaticProvider(
                    [ContextDocument("z", "z", "wiki", weight=1)]
                ),
                "a-provider": StaticProvider(
                    [
                        ContextDocument("b", "b", "runbook", weight=2),
                        ContextDocument("a", "a", "runbook", weight=2),
                    ]
                ),
            }
        )

        result = registry.collect(ContextRequest("task", Path.cwd(), 1000))

        self.assertEqual([document.id for document in result.documents], ["a", "b", "z"])
        self.assertEqual(result.diagnostics, ())

    def test_isolates_errors_and_rejects_duplicate_ids(self) -> None:
        class BrokenProvider:
            def collect(self, request: ContextRequest) -> tuple[ContextDocument, ...]:
                del request
                raise RuntimeError("offline")

        registry = ProviderRegistry(
            [
                ("primary", StaticProvider([ContextDocument("rules", "one", "wiki")])),
                ("duplicate", StaticProvider([ContextDocument("rules", "two", "drive")])),
                ("broken", BrokenProvider()),
            ]
        )

        result = registry.collect(ContextRequest("task", Path.cwd(), 1000))

        self.assertEqual(len(result.documents), 1)
        # Provider names are evaluated in sorted order, so the deterministic
        # first document wins regardless of registration order.
        self.assertEqual(result.documents[0].content, "two")
        self.assertEqual(
            [(item.provider, item.code) for item in result.diagnostics],
            [("broken", "provider_error"), ("primary", "duplicate_document_id")],
        )

    def test_rejects_duplicate_provider_names(self) -> None:
        registry = ProviderRegistry()
        registry.register("static", StaticProvider([]))

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("static", StaticProvider([]))


if __name__ == "__main__":
    unittest.main()
