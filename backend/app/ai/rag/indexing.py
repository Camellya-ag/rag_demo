from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from backend.app.config import (
    ALLOW_DEV_SAMPLE_INDEX,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    QA_MILVUS_HYBRID,
    SAMPLE_CHAPTER_LIMIT,
    SAMPLE_CHUNK_LIMIT,
)
from backend.app.ai.rag.embedding_client import embedding_client
from backend.app.ai.rag.milvus_repo import milvus_repo
from backend.app.ai.rag.qa_generation import GenerationScope, GenerationScopeKind, qa_generation_service
from backend.app.ai.rag.qa_pairs import qa_pair_store
from backend.app.ai.rag.qa_milvus import qa_collection_for_chunk_collection, qa_milvus_index
from backend.app.ai.rag.source_loader import source_loader
from backend.app.ai.rag.state_store import store
from backend.app.utils.pricing import Cost, Usage, cost_embed, cost_unknown

PRODUCTION_MODES = {"initial", "rebuild"}
KNOWN_MODES = {"initial", "rebuild", "dev_sample"}
STAGE_LABELS = {
    "chunk_embed": "原文切片向量化",
    "qa_generate": "问答对生成",
    "qa_embed": "问答对向量化",
}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class IndexingService:
    def __init__(self) -> None:
        self._worker_lock = threading.Lock()

    def _select_chunks(self, mode: str):
        if mode == "dev_sample":
            return source_loader.chunk(
                chapter_limit=SAMPLE_CHAPTER_LIMIT,
                chunk_limit=SAMPLE_CHUNK_LIMIT,
                chunk_size=CHUNK_SIZE,
                overlap=CHUNK_OVERLAP,
            )
        return source_loader.chunk(chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)

    @staticmethod
    def _validate_mode(mode: str) -> str:
        normalized = (mode or "rebuild").strip()
        if normalized not in KNOWN_MODES:
            raise ValueError(f"不支持的索引模式：{normalized}")
        if normalized == "dev_sample" and not ALLOW_DEV_SAMPLE_INDEX:
            raise ValueError("开发样本索引已关闭，正式用户请使用 initial/rebuild")
        return normalized

    def _qa_scope(self, mode: str) -> GenerationScope:
        if mode == "dev_sample":
            return GenerationScope(
                kind=GenerationScopeKind.CHAPTERS,
                chapter_limit=SAMPLE_CHAPTER_LIMIT,
            )
        return GenerationScope(kind=GenerationScopeKind.FULL_BOOK)

    def _estimate_qa(self, mode: str) -> tuple[int, Cost]:
        estimate = qa_generation_service.estimate(self._qa_scope(mode))
        if estimate.units <= 0:
            return 0, cost_unknown("问答对生成费用暂不可估算")
        return estimate.expected_questions, estimate.cost

    @staticmethod
    def _estimate_qa_embed(qa_pair_count: int) -> Cost:
        if qa_pair_count <= 0:
            return cost_unknown("未生成问答对，无法估算 qa_embed")
        if not QA_MILVUS_HYBRID:
            return Cost(amount=0.0, usage_known=True, note="问答对映射为本地锚点，不计付费向量化")
        est_tokens = qa_pair_count * 24
        return cost_embed(est_tokens, Usage(total_tokens=est_tokens, known=False))

    @staticmethod
    def _stage_payload(key: str, cost: Cost, usage: str) -> dict:
        return {
            "key": key,
            "label": STAGE_LABELS.get(key, key),
            "cost": cost.amount,
            "usage_known": cost.usage_known,
            "usage": usage,
            "note": cost.note,
        }

    @staticmethod
    def _merge_costs(*costs: Cost) -> tuple[float | None, bool]:
        total = 0.0
        has_amount = False
        all_known = True
        for cost in costs:
            if not cost.usage_known:
                all_known = False
            if cost.amount is None:
                if cost.usage_known:
                    all_known = False
                continue
            total += float(cost.amount)
            has_amount = True
        if not has_amount:
            return None, False
        return round(total, 6), all_known

    def estimate(self, mode: str = "rebuild") -> dict:
        mode = self._validate_mode(mode)
        chunks = self._select_chunks(mode)
        chunk_token_est = sum(max(1, c.tokens) for c in chunks)
        embed_cost = cost_embed(chunk_token_est)
        qa_pair_count, qa_cost = self._estimate_qa(mode)
        qa_embed_cost = self._estimate_qa_embed(qa_pair_count)
        total, total_known = self._merge_costs(embed_cost, qa_cost, qa_embed_cost)
        return {
            "mode": mode,
            "chunkCount": len(chunks),
            "chunk_count": len(chunks),
            "chapter_total": max((c.chapter for c in chunks), default=0),
            "qa_pair_count": qa_pair_count,
            "embedding_tokens_estimated": chunk_token_est,
            "total_cost": total,
            "totalCost": total,
            "total_cost_known": total_known,
            "currency": "CNY",
            "warning": "",
            "note": "首次正式入库与重建均覆盖全文切片与问答对生成，需先 estimate 再 confirmed=true。",
            "qa_pair_note": "问答对估算为生成上限；校验/映射失败会剔除，实际条数通常低于 qa_pair_count。",
            "stages": [
                self._stage_payload("chunk_embed", embed_cost, f"{chunk_token_est} tokens"),
                self._stage_payload("qa_generate", qa_cost, f"约 {qa_pair_count} 条"),
                self._stage_payload("qa_embed", qa_embed_cost, "问答召回映射到原文章节切片"),
            ],
            "requires_confirmation": mode in PRODUCTION_MODES,
            "estimate_id": f"est_{uuid.uuid4().hex[:10]}",
        }

    def start(self, mode: str, confirmed: bool) -> dict:
        mode = self._validate_mode(mode)
        if mode in PRODUCTION_MODES and not confirmed:
            raise ValueError("正式入库需要先 estimate 并由用户 confirmed=true 确认")
        version = datetime.now().strftime("v%Y%m%d%H%M%S")
        collection = f"xiyou_rag_{version}"
        estimate = self.estimate(mode)
        job = store.create_job(
            mode=mode,
            collection=collection,
            version=version,
            confirmed=confirmed,
            total_chunks=0,
            estimate_id=estimate.get("estimate_id"),
            stages=estimate.get("stages", []),
            cost_estimate=estimate.get("total_cost"),
        )
        worker = threading.Thread(target=self._run_job, args=(job["job_id"], mode, collection, version), daemon=True)
        worker.start()
        return {"job": job}

    def _run_job(self, job_id: str, mode: str, collection: str, version: str) -> None:
        previous_state = store.get_state()
        inserted = 0
        cost_so_far: float | None = 0.0
        qa_pair_count = 0
        try:
            with self._worker_lock:
                store.update_job(job_id, status="running", started_at=_now(), message="正在切分原文", current_stage="chunking")
                chunks = self._select_chunks(mode)
                total = len(chunks)
                store.update_job(job_id, total_chunks=total, progress=5, message=f"共 {total} 个切片，开始向量化", current_stage="chunk_embed")
                vectors, usage = embedding_client.embed([c.text for c in chunks])
                embed_cost = cost_embed(usage.total_tokens or 0, usage)
                cost_so_far = embed_cost.amount
                inserted = milvus_repo.insert_chunks(collection, chunks, vectors)
                store.update_job(job_id, progress=45, message=f"已写入 {inserted} 条原文切片", cost_so_far=cost_so_far, current_stage="qa_generate")

                generation_result = qa_generation_service.generate(
                    scope=self._qa_scope(mode),
                    confirm=True,
                    run_id=job_id,
                )
                qa_pair_count = generation_result.verified_count
                qa_cost = generation_result.cost
                if cost_so_far is not None and qa_cost.amount is not None:
                    cost_so_far = round(cost_so_far + qa_cost.amount, 6)
                elif qa_cost.amount is None:
                    cost_so_far = None
                store.update_job(
                    job_id,
                    progress=75,
                    message=f"问答对生成完成，已验证 {qa_pair_count} 条",
                    cost_so_far=cost_so_far,
                    current_stage="qa_embed",
                )
                if generation_result.status not in {"succeeded", "partial"} or qa_pair_count <= 0:
                    raise RuntimeError(generation_result.message or "正式问答对生成失败")

                if generation_result.status == "partial":
                    store.update_job(job_id, message=f"问答对部分成功，已验证 {qa_pair_count} 条")
                switched = False
                state_patch = {
                    "chunk_count": inserted,
                    "indexed_at": _now(),
                    "status": "ready",
                    "progress": 100,
                    "message": "索引完成",
                    "qa_pair_count": qa_pair_count,
                }
                if mode in PRODUCTION_MODES:
                    state_patch.update({
                        "production_collection": collection,
                        "production_version": version,
                        "active_collection": collection,
                        "active_version": version,
                        "query_collection": collection,
                        "query_mode": "production",
                    })
                    switched = True
                elif mode == "dev_sample":
                    state_patch.update({
                        "sample_collection": collection,
                        "sample_version": version,
                        "query_collection": collection,
                        "query_mode": "dev_sample",
                        "message": "开发样本索引完成，未替换生产索引",
                    })
                if mode in PRODUCTION_MODES:
                    qa_generation_service.write_version_snapshot(version, generation_result.records)
                    with qa_generation_service.production_publish_lock():
                        qa_generation_service.publish_production_records(generation_result.records)
                        if QA_MILVUS_HYBRID:
                            snap_path = qa_generation_service.version_snapshot_path(version)
                            qa_records = qa_milvus_index.load_records_from_path(snap_path)
                            qa_milvus_index.ensure_index(collection, qa_records)
                        store.update_state(state_patch)
                        qa_pair_store.sync_with_state()
                else:
                    store.update_state(state_patch)
                store.update_job(
                    job_id,
                    status="succeeded",
                    progress=100,
                    switched=switched,
                    active_version=state_patch.get("active_version"),
                    building_version=version,
                    message=state_patch["message"],
                    finished_at=_now(),
                    cost_so_far=cost_so_far,
                    current_stage="done",
                )
        except Exception as exc:
            if collection and inserted:
                try:
                    milvus_repo.drop_collection(collection)
                    milvus_repo.drop_collection(qa_collection_for_chunk_collection(collection))
                except Exception:
                    pass
            store.update_state({
                "status": previous_state.get("status", "ready" if previous_state.get("active_collection") else "idle"),
                "message": f"索引失败，已保留旧版本：{exc}",
                "active_collection": previous_state.get("active_collection"),
                "active_version": previous_state.get("active_version"),
                "production_collection": previous_state.get("production_collection"),
                "production_version": previous_state.get("production_version"),
                "query_collection": previous_state.get("query_collection"),
                "query_mode": previous_state.get("query_mode", "none"),
                "chunk_count": previous_state.get("chunk_count", 0),
                "indexed_at": previous_state.get("indexed_at"),
                "progress": previous_state.get("progress", 0),
            })
            store.update_job(job_id, status="failed", error=str(exc), message="索引失败，已保留旧索引", finished_at=_now(), current_stage="failed")


indexing_service = IndexingService()
