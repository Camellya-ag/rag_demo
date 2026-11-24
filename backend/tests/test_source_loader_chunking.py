from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.ai.rag.source_loader import SourceLoader
from backend.app.utils.text import chunk_region_spans

SOURCE_FILE = Path(__file__).resolve().parents[2] / "wmk" / "docs" / "西游记.txt"


class SourceLoaderChunkingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loader = SourceLoader()

    @unittest.skipUnless(SOURCE_FILE.exists(), "missing source file")
    def test_chunk_text_matches_original_spans(self) -> None:
        full = self.loader.read_text()
        chunks = self.loader.chunk(chapter_limit=2, chunk_size=512, overlap=64)
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertEqual(chunk.text, full[chunk.start_char:chunk.end_char])
            self.assertLessEqual(len(chunk.text), 512)

    @unittest.skipUnless(SOURCE_FILE.exists(), "missing source file")
    def test_overlap_and_no_cross_chapter_bleed(self) -> None:
        full = self.loader.read_text()
        chunks = self.loader.chunk(chapter_limit=2, chunk_size=512, overlap=64)
        by_chapter: dict[int, list] = {}
        for c in chunks:
            by_chapter.setdefault(c.chapter, []).append(c)
        for chapter, items in by_chapter.items():
            span = next(s for s in self.loader.chapter_spans(full) if s[0] == chapter)
            _, chapter_start, chapter_end, title = span
            self.assertEqual(items[0].chapter_title, title)
            for idx in range(1, len(items)):
                prev, cur = items[idx - 1], items[idx]
                expected_overlap = min(64, prev.end_char - prev.start_char)
                self.assertEqual(cur.start_char, max(chapter_start, prev.end_char - expected_overlap))
                overlap_len = prev.end_char - cur.start_char
                self.assertGreaterEqual(overlap_len, 0)
                self.assertLessEqual(overlap_len, 64)
                if overlap_len:
                    self.assertEqual(
                        full[cur.start_char : cur.start_char + overlap_len],
                        full[prev.end_char - overlap_len : prev.end_char],
                    )
        if 2 in by_chapter and 1 in by_chapter:
            self.assertGreater(by_chapter[2][0].start_char, by_chapter[1][-1].end_char - 64)

    @unittest.skipUnless(SOURCE_FILE.exists(), "missing source file")
    def test_full_book_coverage_and_chunk_count(self) -> None:
        full = self.loader.read_text()
        spans = self.loader.chapter_spans(full)
        covered_chapters = spans[: min(3, len(spans))]
        for chapter, start, end, _title in covered_chapters:
            chapter_chunks = [
                (start_char, end_char)
                for start_char, end_char in chunk_region_spans(
                    full, start, end, chunk_size=512, overlap=64
                )
            ]
            covered = [0] * (end - start)
            for chunk_start, chunk_end in chapter_chunks:
                for i in range(chunk_start, chunk_end):
                    covered[i - start] = 1
            self.assertEqual(sum(covered), end - start, f"chapter {chapter} not fully covered")
        full_chunks = self.loader.chunk(chunk_size=512, overlap=64)
        self.assertGreater(len(full_chunks), 100)
        self.assertEqual(full_chunks[0].id, "c-000001")
        for chunk in full_chunks[:50]:
            self.assertEqual(chunk.text, full[chunk.start_char:chunk.end_char])

    def test_long_sentence_char_window(self) -> None:
        sentence = "甲" * 1200
        text = f"前言。{sentence}。后缀"
        start = text.index(sentence)
        end = start + len(sentence)
        spans = chunk_region_spans(text, start, end, chunk_size=512, overlap=64)
        self.assertGreater(len(spans), 1)
        for s, e in spans:
            self.assertEqual(text[s:e], sentence[s - start:e - start])
            self.assertLessEqual(e - s, 512)


if __name__ == "__main__":
    unittest.main()
