from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from typing import Any

from backend.app.config import (
    QA_PAIRS_ENABLED,
    QA_PAIRS_FILE,
    QA_PAIRS_FIXTURE,
    QA_PAIRS_JSONL,
    QA_PAIR_MAX,
)
from backend.app.services.source_loader import source_loader
from backend.app.services.state_store import store
from backend.app.utils.text import snippet

_TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


@dataclass
class EvidenceAnchor:
    quote: str
    start_line: int
    end_line: int
    start_char: int
    end_char: int


@dataclass
class QaPairRecord:
    id: str
    chapter: int
    chapter_title: str
    question: str
    answer_summary: str
    evidence: EvidenceAnchor
    verified: bool = True


class QAPairStore:
    def __init__(self) -> None:
        self.enabled = QA_PAIRS_ENABLED
        self.max_items = QA_PAIR_MAX
        self._records: list[QaPairRecord] = []
        self.reload()

    def _ensure_jsonl(self) -> None:
        QA_PAIRS_JSONL.parent.mkdir(parents=True, exist_ok=True)
        if QA_PAIRS_JSONL.exists():
            return
        if QA_PAIRS_FIXTURE.exists():
            shutil.copyfile(QA_PAIRS_FIXTURE, QA_PAIRS_JSONL)
            return
        legacy = QA_PAIRS_FILE
        if legacy.exists():
            try:
                payload = json.loads(legacy.read_text(encoding="utf-8"))
                rows = payload.get("items", [])
                with QA_PAIRS_JSONL.open("w", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def reload(self) -> None:
        self._records = []
        if not self.enabled:
            return
        self._ensure_jsonl()
        if not QA_PAIRS_JSONL.exists():
            return
        for line in QA_PAIRS_JSONL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = row.get("evidence") or {}
            self._records.append(
                QaPairRecord(
                    id=str(row.get("id")),
                    chapter=int(row.get("chapter") or 0),
                    chapter_title=str(row.get("chapter_title") or ""),
                    question=str(row.get("question") or ""),
                    answer_summary=str(row.get("answer_summary") or row.get("answer") or ""),
                    evidence=EvidenceAnchor(
                        quote=str(ev.get("quote") or ""),
                        start_line=int(ev.get("start_line") or 0),
                        end_line=int(ev.get("end_line") or 0),
                        start_char=int(ev.get("start_char") or 0),
                        end_char=int(ev.get("end_char") or 0),
                    ),
                    verified=bool(row.get("verified", True)),
                )
            )
            if len(self._records) >= self.max_items:
                break

    def status(self) -> dict[str, Any]:
        verified = sum(1 for r in self._records if r.verified)
        state = store.get_state()
        query_mode = state.get("query_mode", "none")
        active_version = state.get("active_version")
        active_collection = state.get("active_collection")
        query_collection = state.get("query_collection")
        production_version = state.get("production_version")
        sample_version = state.get("sample_version")
        is_fixture_loaded = len(self._records) > 0 and active_collection is None and query_mode in {"none", "dev_sample"}
        if active_collection and state.get("qa_pair_count"):
            scope = "production" if query_mode == "production" else "indexed"
            status = "ready"
        elif query_mode == "dev_sample":
            scope = "dev_sample"
            status = "ready" if self._records else "empty"
        elif is_fixture_loaded:
            scope = "fixture"
            status = "fixture_only"
        else:
            scope = "unindexed"
            status = "empty"
        if scope == "production":
            note = "全书正式问答对，命中映射原文参与召回"
        elif scope == "dev_sample":
            note = "开发样本索引，未替换生产 collection"
        elif status == "fixture_only":
            note = "无活动索引时本地 sample jsonl，不代表全书入库"
        else:
            note = "问答对未加载或索引未就绪"
        return {
            "enabled": self.enabled,
            "loaded": len(self._records),
            "verified": verified,
            "max": self.max_items,
            "source": QA_PAIRS_JSONL.name,
            "status": status,
            "scope": scope,
            "query_mode": query_mode,
            "active_version": active_version,
            "production_version": production_version,
            "sample_version": sample_version,
            "query_collection": query_collection,
            "active_collection": active_collection,
            "note": note,
        }

    @staticmethod
    def _tokens(text: str) -> set[str]:
        parts = _TOKEN_RE.findall(text.lower())
        bag: set[str] = set(parts)
        for part in parts:
            if len(part) >= 2:
                for i in range(len(part) - 1):
                    bag.add(part[i : i + 2])
        return bag

    @staticmethod
    def _score(query: str, candidate: str) -> float:
        q = QAPairStore._tokens(query)
        c = QAPairStore._tokens(candidate)
        if not q or not c:
            return 0.0
        inter = len(q & c)
        if inter == 0:
            return 0.0
        return inter / len(q)

    def recall(self, original: str, rewritten: str, limit: int = 5) -> list[dict[str, Any]]:
        if not self.enabled or not self._records:
            return []
        query = f"{original} {rewritten}".strip()
        ranked: list[tuple[float, QaPairRecord]] = []
        for record in [r for r in self._records if r.verified]:
            score = self._score(query, record.question)
            if score <= 0:
                score = max(score, self._score(query, record.answer_summary) * 0.55)
            if score > 0:
                ranked.append((score, record))
        ranked.sort(key=lambda x: x[0], reverse=True)

        rows: list[dict[str, Any]] = []
        for rank, (score, record) in enumerate(ranked[:limit], 1):
            mapped_chunk_ids = source_loader.find_chunk_ids_for_range(record.evidence.start_char, record.evidence.end_char)
            rows.append({
                "id": record.id,
                "rank": rank,
                "score": round(score, 4),
                "scoreText": f"{score:.3f}",
                "question": record.question,
                "answer_preview": snippet(record.answer_summary, 48),
                "mapped_chunk_ids": mapped_chunk_ids,
                "channel": "qa_pair",
                "evidence_quote": record.evidence.quote,
            })
        return rows

    def build_chunk_channel(self, collection: str, qa_hits: list[dict[str, Any]], milvus_repo, limit: int) -> list[dict[str, Any]]:
        score_by_chunk: dict[str, dict[str, Any]] = {}
        for hit in qa_hits:
            for cid in hit.get("mapped_chunk_ids") or []:
                score_by_chunk[cid] = hit
        ordered: list[tuple[int, str]] = []
        seen: set[str] = set()
        for hit in qa_hits:
            for cid in hit.get("mapped_chunk_ids") or []:
                if cid in seen:
                    continue
                seen.add(cid)
                ordered.append((hit.get("rank") or 999, cid))
        ordered.sort(key=lambda x: x[0])
        channel: list[dict[str, Any]] = []
        for idx, (_, cid) in enumerate(ordered[:limit], 1):
            row = milvus_repo.get_chunk(collection, cid)
            if not row:
                continue
            src = score_by_chunk.get(cid, {})
            item = milvus_repo._format_hit(row, idx, float(src.get("score", 0.0)))
            item["qa_pair_hit"] = True
            item["matched_question"] = src.get("question")
            channel.append(item)
        return channel


qa_pair_store = QAPairStore()
