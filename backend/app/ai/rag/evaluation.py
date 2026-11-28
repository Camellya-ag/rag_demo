from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.config import ROOT

DEFAULT_EVAL_PATH = ROOT / "backend" / "data" / "eval" / "eval_questions.json"
OFFLINE_REGRESSIONS_PATH = ROOT / "backend" / "data" / "eval" / "eval_offline_regressions.json"
CITATION_RE = re.compile(r"[\[【](\d+)[\]】]")

DEFAULT_THRESHOLDS = {
    "retrieval_hit_rate": 0.75,
    "citation_rate": 0.70,
    "min_answer_rate": 0.80,
    "max_error_rate": 0.05,
}


@dataclass
class EvalQuestion:
    id: str
    question: str
    expected_chapters: list[int]
    must_keywords: list[str]
    tags: list[str]
    reference_answer: str = ""

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "EvalQuestion":
        return cls(
            id=str(row.get("id") or "").strip(),
            question=str(row.get("question") or "").strip(),
            expected_chapters=[int(x) for x in (row.get("expected_chapters") or [])],
            must_keywords=[str(x).strip() for x in (row.get("must_keywords") or []) if str(x).strip()],
            tags=[str(x).strip() for x in (row.get("tags") or []) if str(x).strip()],
            reference_answer=str(row.get("reference_answer") or "").strip(),
        )


def load_eval_questions(path: Path | None = None) -> list[EvalQuestion]:
    target = path or DEFAULT_EVAL_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    rows = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("评测集格式错误：需要 questions 数组")
    return [EvalQuestion.from_dict(row) for row in rows if row.get("question")]


def load_offline_regressions(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or OFFLINE_REGRESSIONS_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    rows = payload.get("cases") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("离线回归集格式错误：需要 cases 数组")
    return rows


def _retrieval_text(hits: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for hit in hits or []:
        chunk = hit.get("chunk") if isinstance(hit.get("chunk"), dict) else {}
        parts.append(str(hit.get("text") or ""))
        parts.append(str(chunk.get("text") or ""))
        parts.append(str(chunk.get("chapter_title") or ""))
    return "\n".join(parts)


def _citation_status(answer: str, hit_count: int) -> dict[str, bool]:
    refs = [int(n) for n in CITATION_RE.findall(answer or "")]
    in_range = bool(refs) and hit_count > 0 and all(1 <= n <= hit_count for n in refs)
    return {
        "citation_present": bool(refs),
        "citation_in_range": in_range,
        "citation_ok": in_range,
    }


def score_case(item: EvalQuestion, *, hits: list[dict[str, Any]], answer: str, error: str | None = None) -> dict[str, Any]:
    hit_chapters = []
    for hit in hits or []:
        chapter = hit.get("chapter")
        if chapter is None and isinstance(hit.get("chunk"), dict):
            chapter = hit["chunk"].get("chapter")
        if chapter is not None:
            try:
                hit_chapters.append(int(chapter))
            except (TypeError, ValueError):
                pass

    retrieval_blob = _retrieval_text(hits)
    chapter_ok = bool(item.expected_chapters) and any(ch in hit_chapters for ch in item.expected_chapters)
    keyword_ok = bool(item.must_keywords) and any(kw in retrieval_blob for kw in item.must_keywords)
    retrieval_scored = bool(item.expected_chapters or item.must_keywords)
    if retrieval_scored:
        retrieval_ok = bool(hits) and (chapter_ok or keyword_ok)
    else:
        retrieval_ok = None
    citation = _citation_status(answer, len(hits or []))
    has_answer = bool((answer or "").strip()) and "无法据此作答" not in (answer or "")

    return {
        "id": item.id,
        "question": item.question,
        "tags": item.tags,
        "error": error,
        "retrieval_ok": retrieval_ok,
        "retrieval_scored": retrieval_scored,
        "chapter_ok": chapter_ok,
        "keyword_ok": keyword_ok,
        "citation_ok": citation["citation_ok"],
        "citation_present": citation["citation_present"],
        "citation_in_range": citation["citation_in_range"],
        "has_answer": has_answer,
        "answer_text": answer or "",
        "hit_count": len(hits or []),
        "hit_chapters": sorted(set(hit_chapters)),
        "expected_chapters": item.expected_chapters,
        "must_keywords": item.must_keywords,
    }


def aggregate_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if total == 0:
        return {"total": 0, "retrieval_hit_rate": 0.0, "citation_rate": 0.0, "answer_rate": 0.0, "error_rate": 1.0}
    errors = sum(1 for r in rows if r.get("error"))
    scored_rows = [r for r in rows if r.get("retrieval_scored")]
    retrieval_hits = sum(1 for r in scored_rows if r.get("retrieval_ok"))
    citations = sum(1 for r in rows if r.get("citation_ok"))
    answers = sum(1 for r in rows if r.get("has_answer"))
    return {
        "total": total,
        "retrieval_hit_rate": round(retrieval_hits / max(len(scored_rows), 1), 4),
        "citation_rate": round(citations / total, 4),
        "answer_rate": round(answers / total, 4),
        "error_rate": round(errors / total, 4),
    }


def passes_thresholds(summary: dict[str, Any], thresholds: dict[str, float] | None = None) -> tuple[bool, list[str]]:
    rules = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    failures: list[str] = []
    if summary.get("retrieval_hit_rate", 0) < rules["retrieval_hit_rate"]:
        failures.append(f"retrieval_hit_rate {summary.get('retrieval_hit_rate')} < {rules['retrieval_hit_rate']}")
    if summary.get("citation_rate", 0) < rules["citation_rate"]:
        failures.append(f"citation_rate {summary.get('citation_rate')} < {rules['citation_rate']}")
    if summary.get("answer_rate", 0) < rules["min_answer_rate"]:
        failures.append(f"answer_rate {summary.get('answer_rate')} < {rules['min_answer_rate']}")
    if summary.get("error_rate", 0) > rules["max_error_rate"]:
        failures.append(f"error_rate {summary.get('error_rate')} > {rules['max_error_rate']}")
    return not failures, failures

