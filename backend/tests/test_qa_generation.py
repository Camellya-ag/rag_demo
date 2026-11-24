from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

from backend.app.services.qa_generation import (
    EvidenceAnchor,
    GenerationScope,
    GenerationScopeKind,
    GenerationUnit,
    QaGenerationNotConfirmed,
    QaGenerationRecord,
    QaGenerationService,
    build_evidence_anchor,
    cost_qa_generation,
    resolve_model_pricing,
    map_record_to_chunks,
    verify_record,
)
from backend.app.services.source_loader import SourceLoader
from backend.app.utils.pricing import Usage

SAMPLE_TEXT = """第 一 回 灵根育孕源流出 心性修持大道生
内育仙胞一日迸裂产一石卵，似圆球样大。
石卵见风化作一个石猴，目运两道金光。

花果山福地水帘洞洞天。
"""


class MockQaClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate_rows(self, *, unit: GenerationUnit, max_questions: int):
        self.calls += 1
        return [
            {
                "question": "孙悟空是怎么出生的？",
                "answer_summary": "从仙石迸裂出的石卵化生。",
                "evidence_quote": "内育仙胞一日迸裂产一石卵",
            },
            {
                "question": "洞门上刻着什么？",
                "answer_summary": "刻着花果山福地水帘洞洞天。",
                "evidence_quote": "花果山福地水帘洞洞天",
            },
        ][:max_questions], Usage(input_tokens=120, output_tokens=80, total_tokens=200, known=True)


class QaGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["XIYOU_QA_GEN_MODEL"] = "qwen-flash"
        os.environ["PRICE_QA_GEN_QWEN_FLASH_IN_PER_1K"] = "0.00005"
        os.environ["PRICE_QA_GEN_QWEN_FLASH_OUT_PER_1K"] = "0.0004"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source_path = Path(self.temp_dir.name) / "sample.txt"
        self.source_path.write_text(SAMPLE_TEXT, encoding="utf-8")
        self.output_path = Path(self.temp_dir.name) / "qa_pairs.jsonl"
        self.loader = SourceLoader(path=self.source_path)
        self.service = QaGenerationService(
            loader=self.loader,
            llm_client=MockQaClient(),
            output_path=self.output_path,
            model="qwen-flash",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_verify_and_map_chunk(self) -> None:
        record = QaGenerationRecord(
            id="q1",
            chapter=1,
            chapter_title="第一回",
            question="q",
            answer_summary="a",
            evidence=EvidenceAnchor(quote="内育仙胞一日迸裂产一石卵", start_line=0, end_line=0, start_char=0, end_char=0),
        )
        verified = verify_record(SAMPLE_TEXT, record)
        self.assertTrue(verified.verified)
        anchor = build_evidence_anchor(SAMPLE_TEXT, "花果山福地水帘洞洞天")
        self.assertIsNotNone(anchor)
        mapped = map_record_to_chunks(verified, self.loader)
        self.assertTrue(mapped.mapped_chunk_ids)

    def test_estimate_requires_no_confirm(self) -> None:
        estimate = self.service.estimate(
            GenerationScope(kind=GenerationScopeKind.CHAPTERS, chapter_ids=[1], questions_per_chapter=2)
        )
        self.assertEqual(estimate.units, 1)
        self.assertEqual(estimate.expected_questions, 2)
        self.assertEqual(estimate.model, "qwen-flash")
        self.assertFalse(estimate.cost.usage_known)
        self.assertIn("qwen-flash", estimate.cost.note)

    def test_model_pricing_bound_to_env(self) -> None:
        model, in_rate, out_rate = resolve_model_pricing("qwen-flash")
        self.assertEqual(model, "qwen-flash")
        self.assertEqual(in_rate, 0.00005)
        self.assertEqual(out_rate, 0.0004)
        cost = cost_qa_generation(1000, 1000, model="qwen-flash", in_known=True, out_known=True)
        self.assertAlmostEqual(cost.amount, 0.00045, places=6)
        self.assertTrue(cost.usage_known)

    def test_generate_requires_confirm(self) -> None:
        with self.assertRaises(QaGenerationNotConfirmed):
            self.service.generate(
                scope=GenerationScope(kind=GenerationScopeKind.CHAPTERS, chapter_ids=[1], questions_per_chapter=2),
                confirm=False,
            )

    def test_generate_mock_records(self) -> None:
        result = self.service.generate(
            scope=GenerationScope(kind=GenerationScopeKind.CHAPTERS, chapter_ids=[1], questions_per_chapter=2),
            confirm=True,
        )
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.verified_count, 2)
        self.assertTrue(all(row.mapped_chunk_ids for row in result.records))
        self.assertTrue(result.cost.usage_known)
        saved = self.service.persist(result.records)
        self.assertEqual(saved, 2)
        self.assertTrue(self.output_path.exists())

    def test_chunk_scope_generation(self) -> None:
        result = self.service.generate(
            scope=GenerationScope(kind=GenerationScopeKind.CHUNKS, chapter_ids=[1], questions_per_chunk=1, chunk_limit=1),
            confirm=True,
        )
        self.assertGreaterEqual(result.verified_count, 1)
        self.assertIsNotNone(result.records[0].origin_chunk_id)

    def test_cancel_stops_next_unit(self) -> None:
        cancel = threading.Event()
        cancel.set()
        result = self.service.generate(
            scope=GenerationScope(kind=GenerationScopeKind.CHAPTERS, chapter_ids=[1], questions_per_chapter=1),
            confirm=True,
            cancel_event=cancel,
        )
        self.assertTrue(result.cancelled)
        self.assertEqual(result.status, "cancelled")

    def test_full_book_generation_maps_chunks(self) -> None:
        result = self.service.generate(
            scope=GenerationScope(kind=GenerationScopeKind.FULL_BOOK, questions_per_chapter=1),
            confirm=True,
        )
        self.assertEqual(result.status, "succeeded")
        self.assertGreaterEqual(result.verified_count, 1)
        self.assertTrue(all(row.mapped_chunk_ids for row in result.records))


if __name__ == "__main__":
    unittest.main()
