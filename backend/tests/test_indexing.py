from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.app.config import SOURCE_FILE
from backend.app.services.indexing import IndexingService
from backend.app.services.qa_generation import GenerationResult
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
        with patch("backend.app.services.indexing.source_loader.chunk", return_value=[fake_chunk] * 3):
            with patch("backend.app.services.indexing.qa_generation_service.estimate", return_value=qa_estimate):
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

    @patch("backend.app.services.indexing.store")
    @patch("backend.app.services.indexing.qa_generation_service")
    @patch("backend.app.services.indexing.embedding_client")
    @patch("backend.app.services.indexing.milvus_repo")
    @patch("backend.app.services.indexing.qa_pair_store")
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
        milvus.drop_collection.assert_called_once_with("new_coll")
        qa_gen.persist.assert_not_called()
        qa_gen.write_version_snapshot.assert_not_called()
        qa_store.sync_with_state.assert_not_called()
        rollback = state_store.update_state.call_args[0][0]
        self.assertEqual(rollback["active_collection"], "old_coll")
        job_args = state_store.update_job.call_args_list[-1]
        self.assertEqual(job_args[0][0], "job_x")
        self.assertEqual(job_args[1]["status"], "failed")

    @patch("backend.app.services.indexing.store")
    @patch("backend.app.services.indexing.qa_generation_service")
    @patch("backend.app.services.indexing.embedding_client")
    @patch("backend.app.services.indexing.milvus_repo")
    @patch("backend.app.services.indexing.qa_pair_store")
    def test_run_job_publishes_qa_after_success(self, qa_store, milvus, embedding, qa_gen, state_store) -> None:
        from backend.app.services.qa_generation import QaGenerationRecord, EvidenceAnchor

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


if __name__ == "__main__":
    unittest.main()
