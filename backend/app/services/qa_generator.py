from __future__ import annotations

import json
import os
import re
from pathlib import Path

from openai import OpenAI

from backend.app.config import LLM_MODEL_DEFAULT, QA_PAIRS_JSONL, QA_QUESTIONS_PER_CHAPTER, SOURCE_FILE
from backend.app.services.qa_pairs import EvidenceAnchor, QaPairRecord
from backend.app.services.source_loader import source_loader
from backend.app.utils.pricing import Cost, Usage, cost_llm
from backend.app.utils.text import estimate_tokens, snippet

OUTPUT_SCHEMA_HINT = {
    "items": [
        {
            "question": "...",
            "answer_summary": "...",
            "evidence_quote": "...",
        }
    ]
}


class QAGenerator:
    def __init__(self) -> None:
        key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
        if not key:
            raise RuntimeError("missing_api_key")
        self.client = OpenAI(api_key=key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = LLM_MODEL_DEFAULT
        self.source_text = source_loader.read_text()

    def _estimate_chapter_tokens(self, body: str) -> tuple[int, int]:
        used = body[:12000]
        input_tokens = estimate_tokens(used) + 450
        output_tokens = estimate_tokens(json.dumps(OUTPUT_SCHEMA_HINT, ensure_ascii=False)) * QA_QUESTIONS_PER_CHAPTER
        return input_tokens, output_tokens

    def estimate(self, chapters: int | None = None) -> tuple[int, Cost]:
        meta = source_loader.meta()
        chapter_rows = source_loader.split_chapters(meta.text)
        if chapters:
            chapter_rows = chapter_rows[:chapters]
        elif meta.chapters:
            chapter_rows = chapter_rows
        input_tokens = 0
        output_tokens = 0
        for _, _, body in chapter_rows:
            in_t, out_t = self._estimate_chapter_tokens(body)
            input_tokens += in_t
            output_tokens += out_t
        qa_count = len(chapter_rows) * QA_QUESTIONS_PER_CHAPTER
        cost = cost_llm(input_tokens, output_tokens, False, False)
        cost.note = "按章节批量生成问答对的估算费用"
        return qa_count, cost

    def _build_anchor(self, quote: str) -> EvidenceAnchor | None:
        quote = (quote or "").strip()
        if not quote:
            return None
        pos = self.source_text.find(quote)
        if pos < 0:
            return None
        start = pos
        end = pos + len(quote)
        start_line = self.source_text.count("\n", 0, start) + 1
        end_line = self.source_text.count("\n", 0, max(0, end - 1)) + 1
        return EvidenceAnchor(quote=quote, start_line=start_line, end_line=end_line, start_char=start, end_char=end)

    def generate_for_chapters(self, chapter_nos: list[int], questions_per_chapter: int = QA_QUESTIONS_PER_CHAPTER) -> tuple[list[QaPairRecord], Cost]:
        meta = source_loader.meta()
        chapter_map = {c[0]: c for c in source_loader.split_chapters(meta.text)}
        usage = Usage()
        records: list[QaPairRecord] = []
        for chapter_no in chapter_nos:
            chapter = chapter_map.get(chapter_no)
            if not chapter:
                continue
            _, title, body = chapter
            prompt = (
                "你是《西游记》章节问答整理助手。基于给定章节原文，仅生成可用于检索召回的白话问句，"
                "并给出对应的原文短引文。不要编造原文里没有的内容。\n"
                f"章节：第{chapter_no}回 {title}\n"
                f"原文：\n{body[:12000]}\n\n"
                f"请输出 JSON，字段为 items，每项包含 question/answer_summary/evidence_quote，数量={questions_per_chapter}。"
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            content = response.choices[0].message.content or "{}"
            m = re.search(r"\{.*\}", content, re.S)
            payload = json.loads(m.group(0) if m else content)
            u = getattr(response, "usage", None)
            if u:
                usage.input_tokens = (usage.input_tokens or 0) + int(getattr(u, "prompt_tokens", 0) or 0)
                usage.output_tokens = (usage.output_tokens or 0) + int(getattr(u, "completion_tokens", 0) or 0)
                usage.total_tokens = (usage.total_tokens or 0) + int(getattr(u, "total_tokens", 0) or 0)
                usage.known = True
            for idx, row in enumerate(payload.get("items", [])[:questions_per_chapter], start=1):
                anchor = self._build_anchor(str(row.get("evidence_quote") or ""))
                if anchor is None:
                    continue
                records.append(
                    QaPairRecord(
                        id=f"q{chapter_no:02d}-{idx:02d}",
                        chapter=chapter_no,
                        chapter_title=title,
                        question=str(row.get("question") or "").strip(),
                        answer_summary=snippet(str(row.get("answer_summary") or ""), 120),
                        evidence=anchor,
                        verified=True,
                    )
                )
        cost = cost_llm(usage.input_tokens or 0, usage.output_tokens or 0, usage.known, usage.known)
        return records, cost

    def persist(self, records: list[QaPairRecord], append: bool = True) -> int:
        QA_PAIRS_JSONL.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, dict] = {}
        if append and QA_PAIRS_JSONL.exists():
            for line in QA_PAIRS_JSONL.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                existing[str(row.get("id"))] = row
        for row in records:
            existing[row.id] = {
                "id": row.id,
                "chapter": row.chapter,
                "chapter_title": row.chapter_title,
                "question": row.question,
                "answer_summary": row.answer_summary,
                "evidence": {
                    "quote": row.evidence.quote,
                    "start_line": row.evidence.start_line,
                    "end_line": row.evidence.end_line,
                    "start_char": row.evidence.start_char,
                    "end_char": row.evidence.end_char,
                },
                "verified": row.verified,
            }
        with QA_PAIRS_JSONL.open("w", encoding="utf-8") as fh:
            for row in existing.values():
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(records)


qa_generator = QAGenerator()
