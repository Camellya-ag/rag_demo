from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest.mock import patch

from backend.app.config import SOURCE_FILE
from backend.app.ai.rag.indexing import IndexingService
from backend.app.ai.rag.qa_generation import GenerationResult
from backend.app.utils.pricing import Cost


class IndexingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IndexingService()

    def test_estimate_returns_three_stages(self) -> None:
        fake_chunk = type("Chunk", (), {"tokens": 12, "chapter": 1})()
        qa_estimate = type(
            "Estimate",
            (),
            {
                "units": 10,
                "expected_questions": 30,
                "cost": Cost(amount=1.23, usage_known=False),
            },
        )()
        with patch("backend.app.ai.rag.indexing.source_loader.chunk", return_value=[fake_chunk] * 3):
            with patch("backend.app.ai.rag.indexing.qa_generation_service.estimate", return_value=qa_estimate):
                payload = self.service.estimate("initial")
        self.assertEqual(len(payload["stages"]), 3)
        keys = {stage["key"] for stage in payload["stages"]}
        self.assertSetEqual(keys, {"chunk_embed", "qa_generate", "qa_embed"})
        self.assertFalse(payload["total_cost_known"])
        self.assertIsNotNone(payload["total_cost"])

    def test_start_requires_confirmation_for_initial(self) -> None:
        with self.assertRaises(ValueError):
            self.service.start("initial", confirmed=False)

    @unittest.skipUnless(SOURCE_FILE.exists(), "缺少全书源文件")
    def test_estimate_initial_with_real_source_loader(self) -> None:
        payload = self.service.estimate("initial")
        self.assertEqual(payload["mode"], "initial")
        self.assertGreater(payload["chunk_count"], 100)
        self.assertGreater(payload["qa_pair_count"], 0)
        self.assertEqual(len(payload["stages"]), 3)
        self.assertTrue(payload["requires_confirmation"])
        # 持久化一份快照供人工核对（测试内不写文件到 repo 根，仅断言）
        _ = json.dumps({"chunk_count": payload["chunk_count"], "qa_pair_count": payload["qa_pair_count"]})

    @patch("backend.app.ai.rag.indexing.store")
    @patch("backend.app.ai.rag.indexing.qa_generation_service")
    @patch("backend.app.ai.rag.indexing.embedding_client")
    @patch("backend.app.ai.rag.indexing.milvus_repo")
    @patch("backend.app.ai.rag.indexing.qa_pair_store")
    def test_run_job_rollback_on_failure(self, qa_store, milvus, embedding, qa_gen, state_store) -> None:
        fake_chunk = type(
            "Chunk",
            (),
            {"id": "c-001", "text": "abc", "chapter": 1, "chapter_title": "第一回", "tokens": 3, "source": "x"},
        )()
        state_store.get_state.return_value = {
            "active_collection": "old_coll",
            "active_version": "v_old",
            "status": "ready",
        }
        embedding.embed.return_value = ([[0.1, 0.2]], type("Usage", (), {"total_tokens": 10, "known": True})())
        milvus.insert_chunks.return_value = 1
        qa_gen.generate.return_value = GenerationResult(
            status="failed",
            records=[],
            verified_count=0,
            rejected_count=0,
            cost=Cost(amount=None, usage_known=False),
            message="mock failed",
        )
        with patch.object(self.service, "_select_chunks", return_value=[fake_chunk]):
            self.service._run_job("job_x", "rebuild", "new_coll", "v_new")
        milvus.drop_collection.assert_any_call("new_coll")
        milvus.drop_collection.assert_any_call("new_coll_qa")
        qa_gen.persist.assert_not_called()
        qa_gen.write_version_snapshot.assert_not_called()
        qa_store.sync_with_state.assert_not_called()
        rollback = state_store.update_state.call_args[0][0]
        self.assertEqual(rollback["active_collection"], "old_coll")
        job_args = state_store.update_job.call_args_list[-1]
        self.assertEqual(job_args[0][0], "job_x")
        self.assertEqual(job_args[1]["status"], "failed")

    @patch("backend.app.ai.rag.indexing.qa_generation_service")
    @patch("backend.app.ai.rag.indexing.store")
    def test_run_job_failure_restores_ready_state(self, state_store, qa_gen) -> None:
        state_store.get_state.return_value = {
            "active_collection": "good_coll",
            "active_version": "v_good",
            "status": "ready",
            "query_collection": "good_coll",
            "query_mode": "production",
            "chunk_count": 12,
        }
        with patch.object(self.service, "_select_chunks", side_effect=RuntimeError("boom")):
            self.service._run_job("job_fail", "rebuild", "new_coll", "v_new")
        restored = state_store.update_state.call_args[0][0]
        self.assertEqual(restored["active_collection"], "good_coll")
        self.assertEqual(restored["status"], "ready")

    @patch("backend.app.ai.rag.indexing.store")
    @patch("backend.app.ai.rag.indexing.qa_generation_service")
    @patch("backend.app.ai.rag.indexing.embedding_client")
    @patch("backend.app.ai.rag.indexing.milvus_repo")
    @patch("backend.app.ai.rag.indexing.qa_pair_store")
    def test_run_job_publishes_qa_after_success(self, qa_store, milvus, embedding, qa_gen, state_store) -> None:
        from backend.app.ai.rag.qa_generation import QaGenerationRecord, EvidenceAnchor

        fake_chunk = type(
            "Chunk",
            (),
            {"id": "c-001", "text": "abc", "chapter": 1, "chapter_title": "第一回", "tokens": 3, "source": "x"},
        )()
        state_store.get_state.return_value = {
            "active_collection": "old_coll",
            "active_version": "v_old",
            "status": "ready",
        }
        embedding.embed.return_value = ([[0.1, 0.2]], type("Usage", (), {"total_tokens": 10, "known": True})())
        milvus.insert_chunks.return_value = 1
        record = QaGenerationRecord(
            id="qa-1",
            chapter=1,
            chapter_title="第一回",
            question="谁",
            answer_summary="summary",
            evidence=EvidenceAnchor(quote="abc", start_line=1, end_line=1, start_char=0, end_char=3),
            mapped_chunk_ids=["c-001"],
            verified=True,
        )
        qa_gen.generate.return_value = GenerationResult(
            status="succeeded",
            records=[record],
            verified_count=1,
            rejected_count=0,
            cost=Cost(amount=0.1, usage_known=True),
            message="ok",
        )
        with patch.object(self.service, "_select_chunks", return_value=[fake_chunk]):
            self.service._run_job("job_ok", "rebuild", "new_coll", "v_new")
        qa_gen.persist.assert_not_called()
        qa_gen.publish_production_records.assert_called_once_with([record])
        write_calls = [c for c in qa_gen.mock_calls if c[0] == "write_version_snapshot"]
        self.assertEqual(len(write_calls), 1)
        update_call = state_store.update_state.call_args
        self.assertIsNotNone(update_call)
        qa_gen.write_version_snapshot.assert_called_once_with("v_new", [record])
        qa_store.sync_with_state.assert_called_once()
        state_patch = state_store.update_state.call_args[0][0]
        self.assertEqual(state_patch["active_collection"], "new_coll")

    @patch("backend.app.ai.rag.indexing.datetime")
    @patch("backend.app.ai.rag.indexing.uuid.uuid4")
    def test_start_generates_unique_version_per_second(self, uuid_mock, dt_mock) -> None:
        dt_mock.now.return_value = datetime(2026, 11, 25, 12, 30, 45)
        uuid_mock.return_value = type("UUID", (), {"hex": "abcd1111efgh2222"})()
        with patch("backend.app.ai.rag.indexing.store") as state_store:
            state_store.create_job.return_value = {"job_id": "job_1"}
            with patch("backend.app.ai.rag.indexing.threading.Thread") as thread_mock:
                thread_mock.return_value.start = lambda: None
                out = self.service.start("rebuild", confirmed=True)
        self.assertEqual(out["job"]["job_id"], "job_1")
        create_args = state_store.create_job.call_args.kwargs
        self.assertEqual(create_args["version"], "v20261125123045_abcd")
        self.assertEqual(create_args["collection"], "xiyou_rag_v20261125123045_abcd")

    @patch("backend.app.ai.rag.indexing.store")
    def test_start_queues_second_job_without_publishing_previous_index(self, state_store) -> None:
        state_store.create_job.side_effect = [
            {"job_id": "job_a", "version": "v_a", "collection": "good_coll"},
            {"job_id": "job_b", "version": "v_b", "collection": "bad_coll"},
        ]
        with patch("backend.app.ai.rag.indexing.threading.Thread") as thread_mock:
            thread_mock.return_value.start = lambda: None
            first = self.service.start("rebuild", confirmed=True)
            second = self.service.start("rebuild", confirmed=True)
        self.assertEqual(first["job"]["job_id"], "job_a")
        self.assertEqual(second["job"]["job_id"], "job_b")
        self.assertEqual(state_store.create_job.call_count, 2)
        self.assertEqual(thread_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
