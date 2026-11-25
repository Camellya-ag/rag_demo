from __future__ import annotations

import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.ai.rag.llm_client import LLMClient
from backend.app.ai.rag.state_store import StateStore


class PersistenceFailureAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_path = Path(temporary.name) / "state.json"
        self.jobs_path = Path(temporary.name) / "jobs.json"
        for name, value in (("STATE_FILE", self.state_path), ("JOBS_FILE", self.jobs_path)):
            patcher = patch(f"backend.app.ai.rag.state_store.{name}", value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = StateStore()
        self.store.update_state({"status": "ready", "active_collection": "good_index"})

    def test_backup_failure_cannot_split_memory_and_disk(self) -> None:
        original_write = Path.write_text

        def fail_backup(path, *args, **kwargs):
            if path == self.state_path.with_suffix(".json.bak"):
                raise OSError("controlled backup write failure")
            return original_write(path, *args, **kwargs)

        with patch.object(Path, "write_text", fail_backup):
            try:
                self.store.update_state({"status": "running"})
            except OSError:
                pass
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(self.store.get_state(), persisted)
        self.assertEqual(persisted["active_collection"], "good_index")

    def test_replace_failure_preserves_previous_state(self) -> None:
        before = self.store.get_state()
        original_replace = Path.replace

        def fail_replace(path, target):
            if Path(target) == self.state_path:
                raise OSError("controlled primary replace failure")
            return original_replace(path, target)

        with patch.object(Path, "replace", fail_replace):
            with self.assertRaises(OSError):
                self.store.update_state({"status": "running"})
        self.assertEqual(self.store.get_state(), before)
        self.assertEqual(json.loads(self.state_path.read_text(encoding="utf-8")), before)

    def test_corrupt_primary_recovers_valid_backup(self) -> None:
        before = self.store.get_state()
        self.state_path.write_text("{broken", encoding="utf-8")
        recovered = StateStore()
        self.assertEqual(recovered.get_state(), before)

    def test_initial_running_write_failure_finishes_job_and_keeps_index(self) -> None:
        from backend.app.ai.rag.indexing import IndexingService

        job = self.store.create_job(mode="rebuild")
        service = IndexingService()
        original_write = self.store._atomic_write
        failed = False

        def fail_first_running(path, payload):
            nonlocal failed
            if path == self.state_path and payload.get("status") == "running" and not failed:
                failed = True
                raise OSError("controlled initial status write failure")
            return original_write(path, payload)

        with patch("backend.app.ai.rag.indexing.store", self.store):
            with patch.object(self.store, "_atomic_write", side_effect=fail_first_running):
                with patch.object(service, "_select_chunks", side_effect=AssertionError("must not begin indexing")):
                    service._run_job(job["job_id"], "rebuild", "unused_new_index", "unused_version")
        self.assertTrue(failed)
        self.assertEqual(self.store.get_job(job["job_id"])["status"], "failed")
        self.assertEqual(self.store.get_state()["status"], "ready")
        self.assertEqual(self.store.get_state()["active_collection"], "good_index")

    def test_same_second_index_requests_receive_distinct_versions(self) -> None:
        from datetime import datetime
        from backend.app.ai.rag.indexing import IndexingService

        service = IndexingService()
        ids = [SimpleNamespace(hex=character * 32) for character in "1234"]
        with patch("backend.app.ai.rag.indexing.store", self.store):
            with patch.object(service, "estimate", return_value={}):
                with patch("backend.app.ai.rag.indexing.datetime") as clock:
                    clock.now.return_value = datetime(2026, 11, 25, 12, 0, 0)
                    with patch("backend.app.ai.rag.indexing.uuid.uuid4", side_effect=ids):
                        with patch("backend.app.ai.rag.indexing.threading.Thread"):
                            first = service.start("rebuild", True)["job"]
                            second = service.start("rebuild", True)["job"]
        self.assertNotEqual(first["version"], second["version"])
        self.assertNotEqual(first["collection"], second["collection"])
        self.assertTrue(first["version"].startswith("v20261125120000_"))
        self.assertTrue(second["version"].startswith("v20261125120000_"))
        self.assertEqual(self.store.get_state()["active_collection"], "good_index")

    def test_queued_failure_preserves_index_published_by_previous_job(self) -> None:
        from backend.app.ai.rag.indexing import IndexingService
        from backend.app.ai.rag.qa_generation import GenerationResult
        from backend.app.utils.pricing import Cost, Usage

        service = IndexingService()
        first_in_chunk = threading.Event()
        second_at_lock = threading.Event()
        release_first = threading.Event()
        actual_lock = threading.Lock()
        errors: list[Exception] = []

        class ObservableLock:
            def __enter__(self):
                if threading.current_thread().name == "supervisor-job-B":
                    second_at_lock.set()
                actual_lock.acquire()

            def __exit__(self, *_args):
                actual_lock.release()

        service._worker_lock = ObservableLock()
        first = self.store.create_job(mode="rebuild")
        second = self.store.create_job(mode="rebuild")
        selections = 0

        def chunks(_mode):
            nonlocal selections
            selections += 1
            if selections != 1:
                raise RuntimeError("controlled failure of queued job B")
            first_in_chunk.set()
            if not release_first.wait(3):
                raise TimeoutError("test coordination deadline")
            return [SimpleNamespace(id="chunk", text="原文", chapter=1, tokens=2)]

        def run(job, collection, version):
            try:
                service._run_job(job["job_id"], "rebuild", collection, version)
            except Exception as exc:
                errors.append(exc)

        dependencies = ("milvus_repo", "embedding_client", "qa_generation_service", "qa_pair_store", "qa_milvus_index")
        with ExitStack() as stack:
            stack.enter_context(patch("backend.app.ai.rag.indexing.store", self.store))
            mocked = {name: stack.enter_context(patch(f"backend.app.ai.rag.indexing.{name}")) for name in dependencies}
            stack.enter_context(patch.object(service, "_select_chunks", side_effect=chunks))
            mocked["embedding_client"].embed.return_value = ([[0.1]], Usage(total_tokens=2, known=True))
            mocked["milvus_repo"].insert_chunks.return_value = 1
            mocked["qa_generation_service"].generate.return_value = GenerationResult(
                status="succeeded", records=[SimpleNamespace(id="qa")], verified_count=1,
                rejected_count=0, cost=Cost(0), message="offline generation",
            )
            workers = [
                threading.Thread(target=run, args=(first, "index_A", "version_A"), name="supervisor-job-A", daemon=True),
                threading.Thread(target=run, args=(second, "index_B", "version_B"), name="supervisor-job-B", daemon=True),
            ]
            try:
                workers[0].start()
                self.assertTrue(first_in_chunk.wait(2))
                workers[1].start()
                self.assertTrue(second_at_lock.wait(2))
                release_first.set()
                for worker in workers:
                    worker.join(3)
                self.assertTrue(all(not worker.is_alive() for worker in workers))
            finally:
                release_first.set()
                for worker in workers:
                    if worker.ident is not None:
                        worker.join(3)
        self.assertEqual(errors, [])
        self.assertEqual(self.store.get_job(first["job_id"])["status"], "succeeded", self.store.get_job(first["job_id"]))
        self.assertEqual(self.store.get_job(second["job_id"])["status"], "failed")
        self.assertEqual(self.store.get_state()["active_collection"], "index_A")
        self.assertEqual(self.store.get_state()["query_collection"], "index_A")
        self.assertEqual(self.store.get_state()["status"], "ready")


class CancellationAcceptanceTests(unittest.TestCase):
    def test_cancel_at_stream_end_preserves_stopped_trace_and_incurred_costs(self) -> None:
        from backend.app.ai.rag.rag_chat import RagChatService
        from backend.app.utils.pricing import Usage

        cancel = threading.Event()
        names = ("store", "llm_client", "rerank_client", "qa_pair_store", "milvus_repo", "embedding_client", "rewrite_query")
        with ExitStack() as stack:
            mocked = {name: stack.enter_context(patch(f"backend.app.ai.rag.rag_chat.{name}")) for name in names}
            mocked["store"].get_state.return_value = {"query_collection": "offline"}
            mocked["rewrite_query"].return_value = {"original": "question", "rewritten": "question", "keywords": []}
            mocked["embedding_client"].embed.return_value = ([[0.1]], Usage(input_tokens=8, total_tokens=8, known=True))
            row = {"id": "evidence", "rank": 1, "score": 0.9, "text": "原文证据", "chapter": 1, "tokens": 4}
            mocked["milvus_repo"].count.return_value = 1
            mocked["milvus_repo"].hybrid_search.return_value = ([row], [row], [row])
            mocked["milvus_repo"].rrf_fuse_channels.return_value = [row]
            mocked["qa_pair_store"].enabled = False
            mocked["rerank_client"].score.return_value = ([0.9], Usage(input_tokens=5, total_tokens=5, known=True))

            def answer(*_args, **_kwargs):
                yield "partial"
                cancel.set()

            mocked["llm_client"].stream_answer.side_effect = answer
            result = RagChatService().run({"question": "question"}, lambda *_args: None, cancel_event=cancel)
            self.assertTrue(result["trace"]["stopped"])
            self.assertEqual(result["trace"]["stages"]["generate"]["status"], "stopped")
            self.assertGreater(result["trace"]["costs"]["by_stage"]["embed"], 0)
            self.assertIsNone(result["trace"]["costs"]["total"])
            mocked["store"].save_trace.assert_called_once()

    def test_cancel_closes_blocked_provider_without_leaking_close_error(self) -> None:
        cancel = threading.Event()
        waiting = threading.Event()
        closed = threading.Event()
        errors: list[Exception] = []

        class BlockingProvider:
            def __iter__(self):
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="partial"))], usage=None
                )
                waiting.set()
                if not closed.wait(3):
                    raise TimeoutError("test cleanup deadline")
                raise RuntimeError("read interrupted by close")

            def close(self):
                closed.set()

        client = LLMClient()

        def consume():
            try:
                list(client.stream_answer("controlled prompt", cancel_event=cancel))
            except Exception as exc:
                errors.append(exc)

        with patch.object(client, "_chat", return_value=BlockingProvider()):
            worker = threading.Thread(target=consume, daemon=True)
            worker.start()
            try:
                self.assertTrue(waiting.wait(1), "provider never entered its blocking read")
                cancel.set()
                worker.join(1)
                self.assertTrue(closed.is_set(), "cancel must actively close the provider")
                self.assertFalse(worker.is_alive(), "cancel must release the blocked worker")
                self.assertEqual(errors, [], "intentional cancellation must not become an upstream failure")
            finally:
                cancel.set()
                closed.set()
                worker.join(3)


if __name__ == "__main__":
    unittest.main()
