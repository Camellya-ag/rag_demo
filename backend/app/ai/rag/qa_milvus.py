"""问答对 Milvus 混合索引：dense(question) + BM25。"""
from __future__ import annotations

import json
from typing import Any

from backend.app.ai.rag.embedding_client import embedding_client
from backend.app.ai.rag.milvus_repo import milvus_repo


def qa_collection_for_chunk_collection(chunk_collection: str) -> str:
    base = (chunk_collection or "").strip()
    if not base:
        return ""
    return f"{base}_qa"


class QaMilvusIndex:
    @staticmethod
    def ensure_index(chunk_collection: str, records: list[dict[str, Any]]) -> str | None:
        """为当前原文 collection 构建/刷新问答 Milvus 集合；无记录则返回 None。"""
        if not chunk_collection or not records:
            return None
        qa_collection = qa_collection_for_chunk_collection(chunk_collection)
        questions = [str(r.get("question") or "").strip() for r in records]
        questions = [q for q in questions if q]
        if not questions:
            milvus_repo.drop_collection(qa_collection)
            return None
        vectors, _ = embedding_client.embed(questions)
        rows: list[dict[str, Any]] = []
        for rec, vec in zip(records, vectors):
            q = str(rec.get("question") or "").strip()
            if not q:
                continue
            ans = str(rec.get("answer_summary") or "")
            evidence = rec.get("evidence") or {}
            mapped = rec.get("mapped_chunk_ids") or []
            if isinstance(mapped, str):
                mapped = [x for x in mapped.split(",") if x]
            rows.append(
                {
                    "qa_id": str(rec.get("id")),
                    "question": q,
                    "answer_summary": ans,
                    "text": f"{q}\n{ans}".strip(),
                    "evidence_quote": str(evidence.get("quote") or ""),
                    "mapped_chunk_ids": ",".join(mapped),
                    "chapter": int(rec.get("chapter") or 0),
                    "dense_vector": vec,
                }
            )
        if not rows:
            milvus_repo.drop_collection(qa_collection)
            return None
        milvus_repo.drop_collection(qa_collection)
        milvus_repo.insert_qa_pairs(qa_collection, rows)
        return qa_collection

    @staticmethod
    def hybrid_recall(
        qa_collection: str | None,
        dense_vector: list[float],
        sparse_queries: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not qa_collection or milvus_repo.count(qa_collection) <= 0:
            return []
        _, _, fused = milvus_repo.hybrid_search_qa(qa_collection, dense_vector, sparse_queries, limit)
        rows: list[dict[str, Any]] = []
        for row in fused:
            mapped_raw = row.get("mapped_chunk_ids") or ""
            mapped = [x.strip() for x in str(mapped_raw).split(",") if x.strip()]
            rows.append(
                {
                    "id": row.get("id"),
                    "rank": row.get("rank"),
                    "score": row.get("score"),
                    "scoreText": row.get("scoreText"),
                    "question": row.get("question", ""),
                    "answer_preview": (row.get("answer_summary") or "")[:48],
                    "mapped_chunk_ids": mapped,
                    "channel": "qa_pair",
                    "evidence_quote": row.get("evidence_quote", ""),
                    "milvus_qa": True,
                }
            )
        return rows

    @staticmethod
    def load_records_from_path(path) -> list[dict[str, Any]]:
        import pathlib

        p = pathlib.Path(path)
        if not p.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


qa_milvus_index = QaMilvusIndex()
