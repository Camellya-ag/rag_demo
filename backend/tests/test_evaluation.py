from __future__ import annotations

import unittest

from backend.app.ai.rag.evaluation import (
    EvalQuestion,
    aggregate_scores,
    load_eval_questions,
    passes_thresholds,
    score_case,
)
from backend.app.utils.text import ensure_answer_citations


class EvaluationTests(unittest.TestCase):
    def test_load_dataset(self) -> None:
        questions = load_eval_questions()
        self.assertGreaterEqual(len(questions), 20)
        self.assertTrue(all(isinstance(q, EvalQuestion) for q in questions))

    def test_score_case_chapter_and_citation(self) -> None:
        item = EvalQuestion(
            id="t1",
            question="孙悟空是怎么出生的？",
            expected_chapters=[1],
            must_keywords=["仙石"],
            tags=["test"],
        )
        row = score_case(
            item,
            hits=[{"chapter": 1, "chunk": {"text": "山顶有一块仙石"}}],
            answer="花果山有仙石迸裂，生出石猴。[1]",
        )
        self.assertTrue(row["retrieval_ok"])
        self.assertTrue(row["citation_ok"])

    def test_aggregate_and_threshold(self) -> None:
        rows = [
            {"error": None, "retrieval_ok": True, "citation_ok": True, "has_answer": True},
            {"error": None, "retrieval_ok": True, "citation_ok": False, "has_answer": True},
            {"error": None, "retrieval_ok": False, "citation_ok": True, "has_answer": True},
            {"error": None, "retrieval_ok": True, "citation_ok": True, "has_answer": True},
        ]
        summary = aggregate_scores(rows)
        self.assertEqual(summary["total"], 4)
        ok, failures = passes_thresholds(summary, {"retrieval_hit_rate": 0.7, "citation_rate": 0.5, "min_answer_rate": 0.8, "max_error_rate": 0.05})
        self.assertTrue(ok, failures)

    def test_ensure_answer_citations(self) -> None:
        self.assertEqual(ensure_answer_citations("孙悟空生于仙石。", 2), "孙悟空生于仙石。 [1]")
        self.assertEqual(ensure_answer_citations("已有依据[1]", 2), "已有依据[1]")
        self.assertEqual(ensure_answer_citations("洞门刻着字。[n]", 2), "洞门刻着字。[1]")
        self.assertEqual(ensure_answer_citations("无命中", 0), "无命中")


if __name__ == "__main__":
    unittest.main()
