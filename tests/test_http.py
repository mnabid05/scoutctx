from __future__ import annotations

import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scoutctx.http import MAX_REQUEST_BYTES, create_server


class HttpAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "service.py").write_text(
            "def authenticate(token):\n    return bool(token)\n",
            encoding="utf-8",
        )
        self.server = create_server(port=0, root=self.root)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def _post(self, path: str, payload: object) -> tuple[int, dict[str, object]]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            with exc:
                return exc.code, json.load(exc)

    def test_health(self) -> None:
        with urlopen(self.base_url + "/health", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {"status": "ok", "service": "scoutctx"})

    def test_builds_context_using_configured_root(self) -> None:
        status, payload = self._post(
            "/v1/context",
            {"task": "inspect authentication", "budget": 512, "format": "markdown"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["metadata"]["task"], "inspect authentication")
        self.assertEqual(payload["format"], "markdown")
        self.assertIn("service.py", payload["content"])

    def test_rejects_invalid_input(self) -> None:
        status, payload = self._post("/v1/context", {"budget": 512})

        self.assertEqual(status, 400)
        self.assertIn("task", str(payload["error"]))

    def test_confines_requested_root_to_configured_boundary(self) -> None:
        status, payload = self._post(
            "/v1/context",
            {"task": "scan elsewhere", "root": "..", "budget": 512},
        )

        self.assertEqual(status, 400)
        self.assertIn("configured server root", str(payload["error"]))

    def test_unknown_path_is_not_found(self) -> None:
        status, payload = self._post("/not-an-endpoint", {"task": "anything"})

        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "not found"})

    def test_rejects_request_body_over_limit(self) -> None:
        request = Request(
            self.base_url + "/v1/context",
            data=b"{}",
            headers={"Content-Length": str(MAX_REQUEST_BYTES + 1)},
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)

        self.assertEqual(caught.exception.code, 413)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
