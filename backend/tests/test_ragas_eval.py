from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from backend.app.ai.rag.evaluation import EvalQuestion
from backend.app.ai.rag.ragas_eval import (
    aggregate_ragas_summary,
    build_hf_dataset,
    contexts_from_hits,
    merge_ragas_scores,
)


class RagasEvalTests(unittest.TestCase):
    def test_contexts_from_hits_prefers_chunk_text(self) -> None:
        hits = [{"text": "outer", "chunk": {"text": "inner chunk"}}]
        self.assertEqual(contexts_from_hits(hits), ["inner chunk"])

    def test_build_hf_dataset_skips_missing_reference(self) -> None:
        q = EvalQuestion(id="q1", question="Q?", expected_chapters=[], must_keywords=[], tags=[], reference_answer="")
        q2 = EvalQuestion(id="q2", question="Q2?", expected_chapters=[], must_keywords=[], tags=[], reference_answer="gt")
        rows = [
            {"id": "q1", "answer_text": "a1", "hits": []},
            {"id": "q2", "answer_text": "a2", "hits": [{"chunk": {"text": "ctx"}}]},
        ]
        dataset, indices = build_hf_dataset(rows, {q.id: q, q2.id: q2})
        self.assertIsNotNone(dataset)
        self.assertEqual(len(indices), 1)
        self.assertEqual(dataset["ground_truth"][0], "gt")

    def test_aggregate_ragas_summary(self) -> None:
        rows = [
            {"ragas": {"faithfulness": 1.0, "skipped": False}},
            {"ragas": {"faithfulness": 0.5, "skipped": False}},
            {"ragas": {"skipped": True}},
        ]
        summary = aggregate_ragas_summary(rows, ["faithfulness"])
        self.assertEqual(summary["faithfulness_mean"], 0.75)
        self.assertEqual(summary["faithfulness_count"], 2)
        self.assertEqual(summary["evaluated_cases"], 2)
        self.assertEqual(summary["skipped_cases"], 1)

    @patch("backend.app.ai.rag.ragas_eval._execute_ragas_subprocess")
    def test_merge_ragas_scores_mocked(self, mock_exec) -> None:
        mock_exec.return_value = (
            {"rows": [{"faithfulness": 0.9, "answer_relevancy": 0.8}], "package_scores": {"faithfulness": 0.9}},
            "qwen-flash",
            "text-embedding-v4",
        )

        questions = [
            EvalQuestion(
                id="q1",
                question="测试",
                expected_chapters=[1],
                must_keywords=[],
                tags=[],
                reference_answer="参考答案",
            )
        ]
        rows = [
            {
                "id": "q1",
                "answer_text": "模型回答",
                "hits": [{"chunk": {"text": "检索片段"}}],
            }
        ]
        updated, summary, meta = merge_ragas_scores(rows, questions, metric_names=["faithfulness", "answer_relevancy"])
        self.assertTrue(meta.get("ragas_enabled"))
        self.assertEqual(updated[0]["ragas"]["faithfulness"], 0.9)
        self.assertEqual(summary["faithfulness_mean"], 0.9)


if __name__ == "__main__":
    unittest.main()