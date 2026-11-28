from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.ai.rag.evaluation import (
    EvalQuestion,
    aggregate_scores,
    load_eval_questions,
    load_offline_regressions,
    passes_thresholds,
    score_case,
)
from backend.app.ai.rag.rewrite import rewrite_query
from backend.app.ai.rag.llm_client import llm_client
from backend.app.utils.text import ensure_answer_citations


class EvaluationTests(unittest.TestCase):
    def test_load_dataset(self) -> None:
        questions = load_eval_questions()
        self.assertGreaterEqual(len(questions), 20)
        self.assertTrue(all(isinstance(q, EvalQuestion) for q in questions))
        self.assertTrue(all(q.reference_answer for q in questions))

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
            {"error": None, "retrieval_ok": True, "retrieval_scored": True, "citation_ok": True, "has_answer": True},
            {"error": None, "retrieval_ok": True, "retrieval_scored": True, "citation_ok": False, "has_answer": True},
            {"error": None, "retrieval_ok": False, "retrieval_scored": True, "citation_ok": True, "has_answer": True},
            {"error": None, "retrieval_ok": True, "retrieval_scored": True, "citation_ok": True, "has_answer": True},
        ]
        summary = aggregate_scores(rows)
        self.assertEqual(summary["total"], 4)
        ok, failures = passes_thresholds(summary, {"retrieval_hit_rate": 0.7, "citation_rate": 0.5, "min_answer_rate": 0.8, "max_error_rate": 0.05})
        self.assertTrue(ok, failures)

    def test_ensure_answer_citations(self) -> None:
        self.assertEqual(ensure_answer_citations("孙悟空生于仙石。", 2), "孙悟空生于仙石。")
        self.assertEqual(ensure_answer_citations("已有依据[1]", 2), "已有依据[1]")
        self.assertEqual(ensure_answer_citations("洞门刻着字。[n]", 2), "洞门刻着字。")
        self.assertEqual(ensure_answer_citations("无命中", 0), "无命中")

    def test_score_case_rejects_answer_only_keyword(self) -> None:
        item = EvalQuestion(
            id="neg1",
            question="测试",
            expected_chapters=[1],
            must_keywords=["仙石"],
            tags=["neg"],
        )
        row = score_case(item, hits=[], answer="提到了仙石[1]", error=None)
        self.assertFalse(row["retrieval_ok"])
        self.assertFalse(row["citation_ok"])

    def test_score_case_rejects_out_of_range_citation(self) -> None:
        item = EvalQuestion(id="neg2", question="测试", expected_chapters=[], must_keywords=[], tags=["neg"])
        row = score_case(
            item,
            hits=[{"chapter": 1, "chunk": {"text": "abc"}}, {"chapter": 2, "chunk": {"text": "def"}}],
            answer="引用越界[99]",
        )
        self.assertTrue(row["citation_present"])
        self.assertFalse(row["citation_in_range"])
        self.assertFalse(row["citation_ok"])

    def test_score_case_placeholder_citation_is_invalid(self) -> None:
        item = EvalQuestion(id="neg3", question="测试", expected_chapters=[], must_keywords=[], tags=["neg"])
        row = score_case(
            item,
            hits=[{"chapter": 1, "chunk": {"text": "abc"}}, {"chapter": 2, "chunk": {"text": "def"}}],
            answer="没有来源映射。[n]",
        )
        self.assertFalse(row["citation_ok"])

    def test_score_case_unscored_without_expectations(self) -> None:
        item = EvalQuestion(id="neg4", question="测试", expected_chapters=[], must_keywords=[], tags=["neg"])
        row = score_case(item, hits=[], answer="", error=None)
        self.assertIsNone(row["retrieval_ok"])
        self.assertFalse(row["retrieval_scored"])

    def test_offline_regression_fixture_executable(self) -> None:
        cases = load_offline_regressions()
        self.assertGreaterEqual(len(cases), 5)
        for case in cases:
            case_id = case["id"]
            inputs = case.get("inputs") or {}
            if "expected_scores" in case:
                row = score_case(
                    EvalQuestion.from_dict(case),
                    hits=inputs.get("hits") or [],
                    answer=str(inputs.get("answer") or ""),
                    error=inputs.get("error"),
                )
                expected = case["expected_scores"]
                for key, value in expected.items():
                    self.assertEqual(row.get(key), value, f"{case_id}:{key}")
            if "expected_rewrite" in case:
                response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content=inputs.get("llm_rewrite", case["question"])
                ))])
                with patch.object(llm_client, "_chat", return_value=response):
                    result = rewrite_query(case["question"], inputs.get("messages") or [])
                expected = case["expected_rewrite"]
                if "equals" in expected:
                    self.assertEqual(result["rewritten"], expected["equals"], case_id)
                for token in expected.get("contains") or []:
                    self.assertIn(token, result["rewritten"], case_id)
                for token in expected.get("excludes") or []:
                    self.assertNotIn(token, result["rewritten"], case_id)
                if "changed" in expected:
                    self.assertEqual(result["changed"], expected["changed"], case_id)
                if "ambiguous_reference" in expected:
                    self.assertEqual(result["ambiguous_reference"], expected["ambiguous_reference"], case_id)


if __name__ == "__main__":
    unittest.main()
