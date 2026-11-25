from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from fastapi import FastAPI

from backend.app.api import routes as api_routes
from backend.app.ai.rag.state_store import StateStore


class StreamingSseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self._tmpdir = Path(temporary.name)
        self._state_path = self._tmpdir / "state.json"
        self._jobs_path = self._tmpdir / "jobs.json"
        self._state_patch = patch("backend.app.ai.rag.state_store.STATE_FILE", self._state_path)
        self._jobs_patch = patch("backend.app.ai.rag.state_store.JOBS_FILE", self._jobs_path)
        self._state_patch.start()
        self._jobs_patch.start()
        self.addCleanup(self._state_patch.stop)
        self.addCleanup(self._jobs_patch.stop)
        self._store = StateStore()
        self._store_patcher = patch("backend.app.api.routes.store", self._store)
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)

        self._app = FastAPI()
        self._app.include_router(api_routes.router)
        self._release = threading.Event()
        self._started = threading.Event()

        def fake_run(payload, emit, *, cancel_event=None):
            emit("rewrite", {"status": "done", "summary": "fake"})
            emit("token", {"type": "token", "text": "第一段"})
            self._started.set()
            if cancel_event:
                while not cancel_event.is_set() and not self._release.wait(0.05):
                    pass
            return {
                "text": "第一段第二段",
                "hits": [],
                "meta": {"trace_id": "trace_test", "latency": 1, "tokens": 2, "first_token_ms": 1},
                "trace": {"trace_id": "trace_test", "stages": {}},
            }

        self._fake_run = fake_run
        self._server = uvicorn.Server(uvicorn.Config(self._app, host="127.0.0.1", port=0, log_level="warning"))
        self._server_thread = threading.Thread(target=self._server.run, daemon=True)
        self._server_thread.start()
        deadline = time.time() + 10
        while time.time() < deadline and not getattr(self._server, "servers", None):
            time.sleep(0.05)
        self.port = list(self._server.servers[0].sockets)[0].getsockname()[1]

    def tearDown(self) -> None:
        self._release.set()
        self._server.should_exit = True
        if hasattr(self, "_server_thread"):
            self._server_thread.join(timeout=3)
        self.assertFalse(self._server_thread.is_alive(), "test server did not shut down")

    @patch("backend.app.api.routes.rag_chat_service.run")
    def test_token_arrives_before_run_completes(self, run_mock) -> None:
        run_mock.side_effect = self._fake_run
        marker = "第一段".encode("utf-8")
        with httpx.Client(timeout=10.0) as client:
            with client.stream(
                "POST",
                f"http://127.0.0.1:{self.port}/api/chat/query",
                json={"question": "测试", "settings": {"streaming": True}},
                headers={"Accept": "text/event-stream"},
            ) as resp:
                buf = b""
                for chunk in resp.iter_bytes():
                    buf += chunk
                    if marker in buf:
                        self.assertTrue(self._started.wait(timeout=2))
                        self._release.set()
                    if b"event: done" in buf:
                        break
                self.assertIn(marker, buf)
                self.assertIn(b"event: done", buf)

    @patch("backend.app.api.routes.rag_chat_service.run")
    def test_disconnect_cancels_and_clears_stop_registry(self, run_mock) -> None:
        request_id = "req_disconnect"

        def slow_run(payload, emit, *, cancel_event=None):
            emit("token", {"type": "token", "text": "A"})
            if cancel_event:
                while not cancel_event.is_set() and not self._release.wait(0.05):
                    pass
            return {"text": "A", "hits": [], "meta": {"trace_id": "t1"}, "trace": {"trace_id": "t1"}}

        run_mock.side_effect = slow_run
        with httpx.Client(timeout=10.0) as client:
            with client.stream(
                "POST",
                f"http://127.0.0.1:{self.port}/api/chat/query",
                json={"request_id": request_id, "question": "测试", "settings": {"streaming": True}},
                headers={"Accept": "text/event-stream"},
            ) as resp:
                first = next(resp.iter_bytes())
                self.assertIn(b"A", first)
        time.sleep(1.0)
        self.assertFalse(self._store.cancel_request(request_id))

    @patch("backend.app.api.routes.rag_chat_service.run")
    def test_queue_full_does_not_block_forever(self, run_mock) -> None:
        emitted = {"count": 0}

        def flood_run(payload, emit, *, cancel_event=None):
            for idx in range(20):
                emitted["count"] += 1
                emit("token", {"type": "token", "text": f"t{idx}"})
                if cancel_event and cancel_event.is_set():
                    break
            return {"text": "done", "hits": [], "meta": {"trace_id": "t2"}, "trace": {"trace_id": "t2"}}

        run_mock.side_effect = flood_run
        with httpx.Client(timeout=10.0) as client:
            with client.stream(
                "POST",
                f"http://127.0.0.1:{self.port}/api/chat/query",
                json={"question": "测试", "settings": {"streaming": True}},
                headers={"Accept": "text/event-stream"},
            ) as resp:
                body = b"".join(resp.iter_bytes())
        self.assertIn(b"event: done", body)
        self.assertGreaterEqual(emitted["count"], 1)

    @patch("backend.app.api.routes.rag_chat_service.run")
    def test_json_query_while_stop_available(self, run_mock) -> None:
        responses = []
        errors = []

        def blocked_run(_payload, _emit, *, cancel_event=None):
            self._started.set()
            while not cancel_event.is_set() and not self._release.wait(0.01):
                pass
            return {"text": "stopped", "hits": [], "meta": {"trace_id": "t-json"}, "trace": {}}

        def query():
            try:
                responses.append(httpx.post(
                    f"http://127.0.0.1:{self.port}/api/chat/query",
                    json={"request_id": "req_json", "question": "测试", "settings": {"streaming": False}},
                    headers={"Accept": "application/json"}, timeout=5,
                ))
            except Exception as exc:
                errors.append(exc)

        run_mock.side_effect = blocked_run
        worker = threading.Thread(target=query, daemon=True)
        worker.start()
        try:
            self.assertTrue(self._started.wait(2))
            stop = httpx.post(
                f"http://127.0.0.1:{self.port}/api/chat/stop", json={"request_id": "req_json"}, timeout=2,
            )
            self.assertEqual(stop.status_code, 200)
            self.assertTrue(stop.json()["ok"])
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive(), "JSON generation must stop without blocking the API loop")
            self.assertEqual(errors, [])
            self.assertEqual(responses[0].status_code, 200)
            self.assertFalse(self._store.cancel_request("req_json"))
        finally:
            self._release.set()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
