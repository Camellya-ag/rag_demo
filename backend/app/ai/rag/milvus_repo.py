from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pymilvus import AnnSearchRequest, DataType, Function, FunctionType, MilvusClient

from backend.app.config import EMBEDDING_DIM, MILVUS_URI, RRF_K

if TYPE_CHECKING:
    from backend.app.ai.rag.source_loader import SourceChunk

MILVUS_DATABASE = "rag_demo"


def _snippet(text: str, limit: int = 28) -> str:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}…"


class MilvusRepo:
    def __init__(self) -> None:
        self.database = MILVUS_DATABASE
        self._ensure_database()
        self.client = MilvusClient(uri=MILVUS_URI, db_name=self.database)

    def _ensure_database(self) -> None:
        admin = MilvusClient(uri=MILVUS_URI)
        if self.database not in admin.list_databases():
            admin.create_database(self.database)

    def ensure_collection(self, name: str) -> None:
        if self.client.has_collection(name):
            return
        schema = self.client.create_schema()
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=32)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=4096, enable_analyzer=True, analyzer_params={"type": "chinese"}, enable_match=True)
        schema.add_field(field_name="chapter", datatype=DataType.INT64)
        schema.add_field(field_name="chapter_title", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="tokens", datatype=DataType.INT64)
        schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(Function(name="text_bm25", input_field_names=["text"], output_field_names=["sparse_vector"], function_type=FunctionType.BM25))
        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="dense_vector", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
        self.client.create_collection(collection_name=name, schema=schema, index_params=index_params)

    def ensure_qa_collection(self, name: str) -> None:
        if self.client.has_collection(name):
            return
        schema = self.client.create_schema()
        schema.add_field(field_name="qa_id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(field_name="question", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="answer_summary", datatype=DataType.VARCHAR, max_length=2048)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=4096, enable_analyzer=True, analyzer_params={"type": "chinese"}, enable_match=True)
        schema.add_field(field_name="evidence_quote", datatype=DataType.VARCHAR, max_length=2048)
        schema.add_field(field_name="mapped_chunk_ids", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="chapter", datatype=DataType.INT64)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(Function(name="text_bm25", input_field_names=["text"], output_field_names=["sparse_vector"], function_type=FunctionType.BM25))
        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="dense_vector", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
        self.client.create_collection(collection_name=name, schema=schema, index_params=index_params)

    def insert_qa_pairs(self, collection: str, rows: list[dict[str, Any]]) -> int:
        self.ensure_qa_collection(collection)
        payload = [dict(row) for row in rows]
        self.client.insert(collection_name=collection, data=payload)
        self.client.flush(collection_name=collection)
        self.client.load_collection(collection_name=collection)
        return len(payload)

    def drop_collection(self, name: str) -> None:
        if self.client.has_collection(name):
            self.client.drop_collection(name)

    def insert_chunks(self, collection: str, chunks: list[SourceChunk], vectors: list[list[float]]) -> int:
        self.ensure_collection(collection)
        rows = []
        for chunk, vector in zip(chunks, vectors):
            rows.append({
                "chunk_id": chunk.id,
                "text": chunk.text,
                "chapter": chunk.chapter,
                "chapter_title": chunk.chapter_title,
                "tokens": chunk.tokens,
                "source": chunk.source,
                "dense_vector": vector,
            })
        self.client.insert(collection_name=collection, data=rows)
        self.client.flush(collection_name=collection)
        self.client.load_collection(collection_name=collection)
        return len(rows)

    def count(self, collection: str) -> int:
        if not self.client.has_collection(collection):
            return 0
        stats = self.client.get_collection_stats(collection)
        return int(stats.get("row_count", 0))

    def get_chunk(self, collection: str, chunk_id: str) -> dict[str, Any] | None:
        if not self.client.has_collection(collection):
            return None
        rows = self.client.query(collection_name=collection, filter=f'chunk_id == "{chunk_id}"', output_fields=["chunk_id", "text", "chapter", "chapter_title", "tokens", "source"], limit=1)
        return rows[0] if rows else None

    def _format_hit(self, row: dict[str, Any], rank: int, score: float) -> dict[str, Any]:
        chapter = int(row.get("chapter", 0) or 0)
        return {
            "id": row.get("chunk_id"),
            "rank": rank,
            "score": float(score),
            "scoreText": f"{float(score):.3f}",
            "chapter": chapter,
            "chapterLabel": f"第 {chapter} 回" if chapter else "未知回目",
            "snippet": _snippet(row.get("text", "")),
            "tokens": int(row.get("tokens", 0) or 0),
            "text": row.get("text", ""),
            "chapter_title": row.get("chapter_title", ""),
            "source": row.get("source", "西游记.txt"),
        }

    def _format_qa_hit(self, row: dict[str, Any], rank: int, score: float) -> dict[str, Any]:
        return {
            "id": row.get("qa_id"),
            "rank": rank,
            "score": float(score),
            "scoreText": f"{float(score):.3f}",
            "question": row.get("question", ""),
            "answer_summary": row.get("answer_summary", ""),
            "evidence_quote": row.get("evidence_quote", ""),
            "mapped_chunk_ids": [x.strip() for x in str(row.get("mapped_chunk_ids") or "").split(",") if x.strip()],
            "chapter": int(row.get("chapter", 0) or 0),
            "text": row.get("text", ""),
        }

    def dense_search(self, collection: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
        results = self.client.search(collection_name=collection, data=[vector], anns_field="dense_vector", limit=limit, output_fields=["chunk_id", "text", "chapter", "chapter_title", "tokens", "source"])
        rows = []
        for rank, hit in enumerate(results[0] if results else [], 1):
            entity = hit.get("entity", {})
            rows.append(self._format_hit(entity, rank, hit.get("distance", 0.0)))
        return rows

    def dense_search_qa(self, collection: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
        if not self.client.has_collection(collection):
            return []
        results = self.client.search(
            collection_name=collection,
            data=[vector],
            anns_field="dense_vector",
            limit=limit,
            output_fields=["qa_id", "question", "answer_summary", "text", "evidence_quote", "mapped_chunk_ids", "chapter"],
        )
        rows = []
        for rank, hit in enumerate(results[0] if results else [], 1):
            entity = hit.get("entity", {})
            rows.append(self._format_qa_hit(entity, rank, hit.get("distance", 0.0)))
        return rows

    def sparse_search(self, collection: str, query: str, limit: int) -> list[dict[str, Any]]:
        results = self.client.search(collection_name=collection, data=[query], anns_field="sparse_vector", limit=limit, output_fields=["chunk_id", "text", "chapter", "chapter_title", "tokens", "source"], search_params={"metric_type": "BM25"})
        rows = []
        for rank, hit in enumerate(results[0] if results else [], 1):
            entity = hit.get("entity", {})
            rows.append(self._format_hit(entity, rank, hit.get("distance", 0.0)))
        return rows

    def sparse_search_qa(self, collection: str, query: str, limit: int) -> list[dict[str, Any]]:
        if not self.client.has_collection(collection):
            return []
        results = self.client.search(
            collection_name=collection,
            data=[query],
            anns_field="sparse_vector",
            limit=limit,
            output_fields=["qa_id", "question", "answer_summary", "text", "evidence_quote", "mapped_chunk_ids", "chapter"],
            search_params={"metric_type": "BM25"},
        )
        rows = []
        for rank, hit in enumerate(results[0] if results else [], 1):
            entity = hit.get("entity", {})
            rows.append(self._format_qa_hit(entity, rank, hit.get("distance", 0.0)))
        return rows

    def hybrid_search_qa(self, collection: str, dense_vector: list[float], sparse_queries: list[str], limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        dense = self.dense_search_qa(collection, dense_vector, limit)
        sparse_merged: dict[str, dict[str, Any]] = {}
        for q in sparse_queries:
            q = str(q or "").strip()
            if not q:
                continue
            for row in self.sparse_search_qa(collection, q, limit):
                prev = sparse_merged.get(row["id"])
                if not prev or row["score"] > prev["score"]:
                    sparse_merged[row["id"]] = row
        sparse = sorted(sparse_merged.values(), key=lambda x: x["score"], reverse=True)[:limit]
        for i, row in enumerate(sparse, 1):
            row["rank"] = i
        fused = self.rrf_fuse_channels([dense, sparse])
        return dense, sparse, fused

    def hybrid_search(
        self,
        collection: str,
        dense_vector: list[float],
        sparse_queries: list[str],
        limit: int,
        *,
        sparse_hits: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        dense = self.dense_search(collection, dense_vector, limit)
        if sparse_hits is not None:
            sparse = list(sparse_hits)
        else:
            sparse_merged: dict[str, dict[str, Any]] = {}
            for q in sparse_queries:
                q = str(q or "").strip()
                if not q:
                    continue
                for row in self.sparse_search(collection, q, limit):
                    prev = sparse_merged.get(row["id"])
                    if not prev or row["score"] > prev["score"]:
                        sparse_merged[row["id"]] = row
            sparse = sorted(sparse_merged.values(), key=lambda x: x["score"], reverse=True)[:limit]
            for i, row in enumerate(sparse, 1):
                row["rank"] = i
        fused = self.rrf_fuse(dense, sparse)
        return dense, sparse, fused

    @staticmethod
    def normalize_rrf_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将 RRF 分归一化到 [0,1]，用于 rerank 失败降级。"""
        if not rows:
            return []
        scores = [float(r.get("score") or 0) for r in rows]
        lo, hi = min(scores), max(scores)
        out = []
        for row in rows:
            raw = float(row.get("score") or 0)
            norm = 1.0 if hi == lo else (raw - lo) / (hi - lo)
            item = dict(row)
            item["rerankScore"] = round(norm, 6)
            item["rerankText"] = f"{norm:.3f}"
            item["rerank_degraded"] = True
            out.append(item)
        out.sort(key=lambda x: x.get("rerankScore", 0), reverse=True)
        for i, row in enumerate(out, 1):
            row["rerankRank"] = i
        return out

    def rrf_fuse(self, dense: list[dict[str, Any]], sparse: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.rrf_fuse_channels([dense, sparse])

    def rrf_fuse_channels(self, channels: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        maps: list[dict[str, dict[str, Any]]] = []
        for channel in channels:
            maps.append({item["id"]: item for item in channel})
        ids: set[str] = set()
        for m in maps:
            ids.update(m.keys())
        rows = []
        for cid in ids:
            ranks = []
            base = None
            for idx, channel_map in enumerate(maps):
                hit = channel_map.get(cid)
                if not hit:
                    continue
                ranks.append((idx, hit["rank"]))
                base = base or hit
            score = 0.0
            for _, rank in ranks:
                score += 1.0 / (RRF_K + rank)
            if not base:
                continue
            rows.append({**base, "score": round(score, 6), "scoreText": f"{score:.4f}", "rrf_ranks": ranks})
        rows.sort(key=lambda x: x["score"], reverse=True)
        for i, row in enumerate(rows, 1):
            row["rank"] = i
        return rows

    def _legacy_rrf_fuse(self, dense: list[dict[str, Any]], sparse: list[dict[str, Any]]) -> list[dict[str, Any]]:
        dense_map = {item["id"]: item for item in dense}
        sparse_map = {item["id"]: item for item in sparse}
        ids = set(dense_map) | set(sparse_map)
        rows = []
        for cid in ids:
            dense_hit = dense_map.get(cid)
            sparse_hit = sparse_map.get(cid)
            dense_rank = dense_hit["rank"] if dense_hit else None
            sparse_rank = sparse_hit["rank"] if sparse_hit else None
            score = 0.0
            if dense_rank:
                score += 1.0 / (RRF_K + dense_rank)
            if sparse_rank:
                score += 1.0 / (RRF_K + sparse_rank)
            base = dense_hit or sparse_hit
            rows.append({
                **base,
                "denseRank": dense_rank,
                "sparseRank": sparse_rank,
                "denseScore": dense_hit["score"] if dense_hit else None,
                "score": round(score, 6),
                "scoreText": f"{score:.4f}",
            })
        rows.sort(key=lambda x: x["score"], reverse=True)
        for i, row in enumerate(rows, 1):
            row["rank"] = i
        return rows


milvus_repo = MilvusRepo()
