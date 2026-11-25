from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from backend.app.config import CANDIDATE_LIMIT, DEFAULT_TOP_K, LLM_MODEL_DEFAULT, QA_MILVUS_HYBRID, RERANK_IN
from backend.app.ai.rag.embedding_client import embedding_client
from backend.app.ai.rag.llm_client import llm_client
from backend.app.ai.rag.milvus_repo import milvus_repo
from backend.app.ai.rag.qa_pairs import qa_pair_store
from backend.app.ai.rag.qa_milvus import qa_collection_for_chunk_collection, qa_milvus_index
from backend.app.ai.rag.rerank_client import rerank_client
from backend.app.ai.rag.rewrite import rewrite_query
from backend.app.ai.rag.state_store import store
from backend.app.utils.pricing import Cost, Usage, cost_embed, cost_llm_for_model, cost_rerank
from backend.app.utils.text import ensure_answer_citations, estimate_tokens, normalize_answer_citations, select_hits_by_token_budget, snippet

StageEmitter = Callable[[str, dict[str, Any]], None]


def _stage(emit: StageEmitter, key: str, **patch: Any) -> None:
    emit(key, patch)


def _hit_from_row(row: dict[str, Any], rank: int, score: float) -> dict[str, Any]:
    chapter = int(row.get("chapter", 0) or 0)
    nested = row.get("chunk") if isinstance(row.get("chunk"), dict) else None
    text = str((nested or {}).get("text") or row.get("text") or "")
    tokens = int((nested or {}).get("tokens") or row.get("tokens", 0) or 0)
    chunk_id = row.get("id") or row.get("chunk_id") or (nested or {}).get("id")
    return {
        "id": chunk_id,
        "rank": rank,
        "score": float(score),
        "scoreText": f"{float(score):.3f}",
        "chapter": chapter,
        "chunk": {
            "id": chunk_id,
            "chapter": chapter,
            "chapterTitle": f"第 {chapter} 回",
            "chapter_title": (nested or {}).get("chapter_title") or row.get("chapter_title") or f"第 {chapter} 回",
            "text": text,
            "tokens": tokens,
            "source": (nested or {}).get("source") or row.get("source", "西游记.txt"),
        },
    }


def _reindex_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, hit in enumerate(hits, 1):
        item = dict(hit)
        item["rank"] = idx
        if isinstance(item.get("chunk"), dict):
            chunk = dict(item["chunk"])
            chunk.setdefault("id", item.get("id"))
            item["chunk"] = chunk
        out.append(item)
    return out


def _dedupe_sparse_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for query in queries:
        q = str(query or "").strip()
        if not q or q in seen:
            continue
        seen.add(q)
        out.append(q)
    return out


def _generation_question(question: str, rewritten: dict[str, Any]) -> str:
    return str(rewritten.get("rewritten") or question).strip() or question


def _conversation_context(messages: list[dict[str, Any]], *, limit: int = 4) -> list[str]:
    items: list[str] = []
    for msg in messages[-limit:]:
        if str(msg.get("role") or "").lower() != "user":
            continue
        content = str(msg.get("content") or msg.get("text") or "").strip()
        if content:
            items.append(content)
    return items[-limit:]


class RagChatService:
    def run(self, payload: dict[str, Any], emit: StageEmitter, *, cancel_event=None) -> dict[str, Any]:
        request_id = payload.get("request_id") or uuid.uuid4().hex
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        question = str(payload.get("question") or "").strip()
        settings = payload.get("settings") or {}
        messages = payload.get("messages") or []
        top_k = int(settings.get("topK") or settings.get("top_k") or DEFAULT_TOP_K)
        raw_threshold = settings.get("threshold")
        threshold = float(raw_threshold) if raw_threshold is not None else None
        model = settings.get("model") or LLM_MODEL_DEFAULT
        temperature = float(settings.get("temperature", 0.3))
        streaming = bool(settings.get("streaming", True))
        system_prompt = settings.get("systemPrompt") or settings.get("system_prompt") or ""

        total_cost = 0.0
        total_cost_known = True
        stages_cost: dict[str, float] = {}
        pipeline_started = time.perf_counter()
        first_token_ms: int | None = None
        trace: dict[str, Any] = {
            "trace_id": trace_id,
            "request_id": request_id,
            "question": question,
            "settings": {
                "model": model,
                "temperature": temperature,
                "top_k": top_k,
                "threshold": threshold,
                "streaming": streaming,
                "system_prompt": system_prompt,
            },
            "stages": {},
            "channels": {},
            "errors": [],
            "stopped": False,
            "costs": {"total": 0.0, "total_known": True, "by_stage": {}, "usage_unknown": []},
        }

        def finish_stage(key: str, ms: int, cost: Cost, summary: str, detail: Any, status="done"):
            nonlocal total_cost, total_cost_known
            cost_payload = cost.as_dict()
            amount = cost_payload["amount"]
            if cost.usage_known and amount is not None:
                total_cost += float(amount)
                stages_cost[key] = round(float(amount), 6)
            else:
                total_cost_known = False
                stages_cost[key] = None
            patch = {
                "status": status,
                "ms": ms,
                "cost": amount,
                "cost_known": cost.usage_known,
                "summary": summary,
                "detail": detail,
            }
            trace["stages"][key] = patch
            trace["costs"]["by_stage"][key] = amount
            if not cost.usage_known:
                trace["costs"]["usage_unknown"].append(key)
            _stage(emit, key, **patch)

        state = store.get_state()
        collection = state.get("query_collection") or state.get("active_collection")
        if not collection or milvus_repo.count(collection) <= 0:
            msg = "知识库尚未建立或当前无可用索引，请先执行样本或全文索引。"
            trace["errors"].append(msg)
            _stage(emit, "rewrite", status="done", ms=0, cost=0, summary=msg, detail=None)
            return {"text": msg, "hits": [], "meta": {"latency": 0, "tokens": 0, "cost": 0, "trace_id": trace_id}, "trace": trace}

        if cancel_event and cancel_event.is_set():
            trace["stopped"] = True
            return {"text": "", "hits": [], "meta": {"trace_id": trace_id, "cost": total_cost}, "trace": trace}

        t0 = time.perf_counter()
        rewritten = rewrite_query(question, messages)
        if rewritten.get("llm_usage"):
            usage = rewritten["llm_usage"]
            rewrite_cost = cost_llm_for_model(
                usage.get("input_tokens") or 0,
                usage.get("output_tokens") or 0,
                model=rewritten.get("llm_model") or model,
                in_known=bool(usage.get("known")),
                out_known=bool(usage.get("known")),
            )
        else:
            rewrite_cost = Cost(amount=0.0, usage_known=True)
        finish_stage("rewrite", int((time.perf_counter() - t0) * 1000), rewrite_cost, rewritten["rewritten"], rewritten)
        trace["rewrite"] = rewritten
        generation_question = _generation_question(question, rewritten)

        t0 = time.perf_counter()
        same_query = rewritten["original"] == rewritten["rewritten"]
        embed_inputs = [rewritten["original"]] if same_query else [rewritten["original"], rewritten["rewritten"]]
        vectors, usage = embedding_client.embed(embed_inputs)
        if same_query:
            vectors = vectors + vectors
        elif len(vectors) < 2:
            vectors = vectors + vectors
        embed_cost = cost_embed(usage.total_tokens or sum(estimate_tokens(t) for t in embed_inputs), usage)
        finish_stage(
            "embed",
            int((time.perf_counter() - t0) * 1000),
            embed_cost,
            f"{usage.total_tokens or sum(estimate_tokens(t) for t in embed_inputs)} tokens",
            {
                "model": "text-embedding-v4",
                "dim": 1024,
                "input": rewritten["rewritten"],
                "queries": embed_inputs,
                "duplicate_query_reused": same_query,
                "tokens": usage.total_tokens,
                "preview": [f"{float(v):.4f}" for v in (vectors[1] or vectors[0] or [])[:8]],
                "price": "按 DashScope embedding 计费",
            },
        )

        if cancel_event and cancel_event.is_set():
            trace["stopped"] = True
            trace["costs"]["total"] = round(total_cost, 6) if total_cost_known else None
            trace["costs"]["total_known"] = total_cost_known
            _stage(emit, "generate", status="stopped", ms=0, cost=stages_cost.get("generate", 0), summary="已停止", detail={})
            store.save_trace(trace_id, trace)
            return {"text": "", "hits": [], "meta": {"trace_id": trace_id, "cost": total_cost}, "trace": trace}

        t0 = time.perf_counter()
        state = store.get_state()
        collection = state.get("query_collection") or state.get("active_collection")
        qa_pair_store.sync_with_state()
        sparse_queries = _dedupe_sparse_queries(
            [rewritten["original"], rewritten["rewritten"], " ".join(rewritten.get("keywords") or [])]
        )
        chunk_dense_o, chunk_sparse, chunk_fused = milvus_repo.hybrid_search(
            collection, vectors[0], sparse_queries, CANDIDATE_LIMIT
        )
        if same_query:
            chunk_dense_rw = chunk_dense_o
            chunk_fused_rw = chunk_fused
            sparse_reused = True
        else:
            chunk_dense_rw, _, chunk_fused_rw = milvus_repo.hybrid_search(
                collection,
                vectors[1],
                sparse_queries,
                CANDIDATE_LIMIT,
                sparse_hits=chunk_sparse,
            )
            sparse_reused = True

        qa_hits: list[dict[str, Any]] = []
        qa_hybrid_mode = "skipped"
        if QA_MILVUS_HYBRID and qa_pair_store.enabled and qa_pair_store.export_verified_records():
            qa_coll = qa_collection_for_chunk_collection(collection)
            if milvus_repo.count(qa_coll) <= 0:
                qa_milvus_index.ensure_index(collection, qa_pair_store.export_verified_records())
            if qa_pair_store.qa_collection_ready(collection):
                qa_hits = qa_milvus_index.hybrid_recall(qa_coll, vectors[1], sparse_queries, CANDIDATE_LIMIT)
                qa_hybrid_mode = "milvus_hybrid"
        if not qa_hits and qa_pair_store.enabled:
            qa_hits = qa_pair_store.recall(rewritten["original"], rewritten["rewritten"])
            qa_hybrid_mode = "local_keyword_fallback" if qa_hits else "skip"

        qa_channel = qa_pair_store.build_chunk_channel(collection, qa_hits, milvus_repo, limit=CANDIDATE_LIMIT)
        qa_by_chunk: dict[str, dict[str, Any]] = {}
        for src in qa_hits:
            for cid in src.get("mapped_chunk_ids") or []:
                qa_by_chunk[cid] = src
        for hit in qa_channel:
            hit.setdefault("qa_pair_hit", True)
            src = qa_by_chunk.get(hit.get("id"))
            if src:
                hit["evidence_quote"] = src.get("evidence_quote") or ""
                hit["matched_question"] = src.get("question") or hit.get("matched_question")

        dense_original = chunk_dense_o
        dense_rewritten = chunk_dense_rw
        retrieve_detail = {
            "indexSize": milvus_repo.count(collection),
            "dense_original": {"metric": "余弦相似度", "items": dense_original},
            "dense_rewritten": {"metric": "余弦+BM25 融合", "items": chunk_fused_rw},
            "sparse": {"metric": "BM25", "items": chunk_sparse},
            "chunk_hybrid_original": {"metric": "稠密+BM25", "items": chunk_fused},
            "chunk_hybrid_rewritten": {"metric": "稠密+BM25", "items": chunk_fused_rw},
            "qa_pairs": qa_hits,
            "qa_hybrid_mode": qa_hybrid_mode,
            "sparse_queries": sparse_queries,
            "sparse_reused": sparse_reused,
            "same_query": same_query,
        }
        trace["channels"] = {
            "dense_original": dense_original,
            "dense_rewritten": chunk_fused_rw,
            "sparse": chunk_sparse,
            "qa_pairs": qa_hits,
            "qa_chunks": qa_channel,
        }
        finish_stage(
            "retrieve",
            int((time.perf_counter() - t0) * 1000),
            Cost(0, usage_known=True),
            f"原文混合 {len(chunk_fused)} · 改写混合 {len(chunk_fused_rw)} · QA {qa_hybrid_mode} {len(qa_channel)}",
            retrieve_detail,
        )

        t0 = time.perf_counter()
        fusion_channels = [chunk_fused, chunk_fused_rw, qa_channel]
        if same_query:
            fusion_channels = [chunk_fused, qa_channel]
        fused = milvus_repo.rrf_fuse_channels(fusion_channels)
        fusion_detail = {
            "method": "RRF",
            "k": 60,
            "channels": (
                ["chunk_hybrid_original", "qa_chunks"]
                if same_query
                else ["chunk_hybrid_original", "chunk_hybrid_rewritten", "qa_chunks"]
            ),
            "rewritten_reused": same_query,
            "items": fused,
        }
        fused = fused[: max(RERANK_IN, top_k * 2)]
        for i, row in enumerate(fused, 1):
            row["rank"] = i
        trace["fusion"] = fusion_detail
        finish_stage("fusion", int((time.perf_counter() - t0) * 1000), Cost(0), f"合并 {len(fused)} 条", fusion_detail)

        t0 = time.perf_counter()
        docs = [row.get("text", "") for row in fused]
        rerank_degraded = False
        rerank_error: str | None = None
        rerank_usage = Usage()
        try:
            rerank_scores, rerank_usage = rerank_client.score(rewritten["rewritten"], docs)
            rerank_cost = cost_rerank(
                rerank_usage.total_tokens or estimate_tokens(rewritten["rewritten"]) + sum(estimate_tokens(d) for d in docs),
                rerank_usage,
            )
            reranked = []
            for row, score in zip(fused, rerank_scores):
                item = dict(row)
                item["rerankScore"] = float(score)
                item["rerankText"] = f"{float(score):.3f}"
                reranked.append(item)
            reranked.sort(key=lambda x: x.get("rerankScore", 0), reverse=True)
        except Exception as exc:
            rerank_degraded = True
            rerank_error = str(exc)
            rerank_cost = Cost(0.0, usage_known=True, note="重排失败，已降级使用 RRF 归一化分")
            reranked = milvus_repo.normalize_rrf_scores(fused)
        if threshold is not None:
            dropped = [r for r in reranked if r.get("rerankScore", 0) < threshold]
            reranked = [r for r in reranked if r.get("rerankScore", 0) >= threshold]
        else:
            dropped = []
        reranked = reranked[:top_k]
        for i, row in enumerate(reranked, 1):
            row["rerankRank"] = i
        rerank_detail = {
            "skipped": False,
            "degraded": rerank_degraded,
            "error": rerank_error,
            "model": rerank_client.model,
            "threshold": threshold,
            "dropped": len(dropped),
            "tokens": rerank_usage.total_tokens,
            "items": reranked,
        }
        trace["rerank"] = rerank_detail
        finish_stage("rerank", int((time.perf_counter() - t0) * 1000), rerank_cost, f"保留 {len(reranked)} 条", rerank_detail)

        if cancel_event and cancel_event.is_set():
            trace["stopped"] = True
            trace["costs"]["total"] = round(total_cost, 6) if total_cost_known else None
            trace["costs"]["total_known"] = total_cost_known
            _stage(emit, "generate", status="stopped", ms=0, cost=stages_cost.get("generate", 0), summary="已停止", detail={})
            store.save_trace(trace_id, trace)
            return {"text": "", "hits": [], "meta": {"trace_id": trace_id, "cost": total_cost}, "trace": trace}

        context_budget = 2048
        recent_context = _conversation_context(messages)
        context_prefix = system_prompt
        if recent_context:
            context_prefix = f"{system_prompt}\n\n近期用户追问：\n" + "\n".join(f"- {item}" for item in recent_context)
        prompt_header = (
            f"{context_prefix}\n\n检索片段：\n"
            f"（待组装）\n\n问题：{generation_question}\n\n"
            "请用中文回答，并在句末使用 [1]、[2] 等序号标注引用来源。"
        )
        reserved_tokens = estimate_tokens(prompt_header) + 48
        candidate_hits = [_hit_from_row(row, idx + 1, row.get("rerankScore", row.get("score", 0))) for idx, row in enumerate(reranked)]
        selected_rows, budget_stats = select_hits_by_token_budget(
            candidate_hits,
            reserved_tokens=reserved_tokens,
            budget=context_budget,
        )
        selected_hits = _reindex_hits(selected_rows)
        emit("hits", {"type": "hits", "hits": selected_hits})
        context_parts = []
        for idx, hit in enumerate(selected_hits, 1):
            chunk = hit["chunk"]
            context_parts.append(f"[{idx}] 第{chunk['chapter']}回 {chunk['id']}\n{chunk['text']}")
        prompt = (
            f"{context_prefix}\n\n检索片段：\n"
            + ("\n\n".join(context_parts) if context_parts else "（无命中片段）")
            + f"\n\n问题：{generation_question}\n\n请用中文回答，并在句末使用 [1]、[2] 等序号标注引用来源。"
        )
        assemble_detail = {
            "ids": [h["id"] for h in selected_hits],
            "selected_count": len(selected_hits),
            "candidate_count": len(candidate_hits),
            "tokens": estimate_tokens(prompt),
            "budget": context_budget,
            "budget_stats": budget_stats,
            "generation_question": generation_question,
            "prompt": prompt,
        }
        trace["assemble"] = assemble_detail
        finish_stage("assemble", 0, Cost(0), f"入选 {len(selected_hits)} 个片段", assemble_detail)

        if not selected_hits or budget_stats.get("remaining_tokens", 0) < 0 or estimate_tokens(prompt) > context_budget:
            no_evidence = "知识库中没有检索到与问题足够相关的原文片段，无法据此作答。"
            trace["costs"]["total"] = round(total_cost, 6) if total_cost_known else None
            trace["costs"]["total_known"] = total_cost_known
            trace["answer"] = {"text": no_evidence, "hits": []}
            _stage(emit, "generate", status="done", ms=0, cost=0.0, cost_known=True, summary="无证据，跳过生成", detail={"skipped": True})
            emit("token", {"type": "token", "text": no_evidence})
            store.save_trace(trace_id, trace)
            return {
                "text": no_evidence,
                "hits": [],
                "meta": {
                    "latency": 0,
                    "tokens": 0,
                    "cost": round(total_cost, 6) if total_cost_known else None,
                    "followUps": [],
                    "trace_id": trace_id,
                },
                "trace": trace,
            }

        if cancel_event and cancel_event.is_set():
            trace["stopped"] = True
            trace["costs"]["total"] = round(total_cost, 6) if total_cost_known else None
            trace["costs"]["total_known"] = total_cost_known
            _stage(emit, "generate", status="stopped", ms=0, cost=stages_cost.get("generate", 0), summary="已停止", detail={})
            store.save_trace(trace_id, trace)
            return {
                "text": "",
                "hits": selected_hits,
                "meta": {"trace_id": trace_id, "cost": total_cost},
                "trace": trace,
            }

        t0 = time.perf_counter()
        _stage(emit, "generate", status="running", ms=0, cost=0, summary=f"{model} 生成中", detail={"model": model, "temperature": temperature})
        answer_parts: list[str] = []
        usage = Usage()
        if streaming:
            answer_stream = llm_client.stream_answer(
                prompt,
                model=model,
                temperature=temperature,
                cancel_event=cancel_event,
            )
            try:
                for piece in answer_stream:
                    if cancel_event and cancel_event.is_set():
                        trace["stopped"] = True
                        break
                    if isinstance(piece, dict) and piece.get("__usage__"):
                        usage.merge(piece["__usage__"])
                        continue
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - pipeline_started) * 1000)
                    answer_parts.append(piece)
                    emit("token", {"type": "token", "text": piece})
            finally:
                close = getattr(answer_stream, "close", None)
                if callable(close):
                    close()
        else:
            text, usage = llm_client.complete(prompt, model=model, temperature=temperature)
            first_token_ms = int((time.perf_counter() - pipeline_started) * 1000)
            answer_parts.append(text)
            emit("token", {"type": "token", "text": text})

        if cancel_event and cancel_event.is_set():
            trace["stopped"] = True

        answer = "".join(answer_parts).strip()
        if not streaming:
            answer = ensure_answer_citations(answer, len(selected_hits))
        answer, citation_meta = normalize_answer_citations(answer, len(selected_hits))
        out_tokens = usage.output_tokens or estimate_tokens(answer)
        in_tokens = usage.input_tokens or estimate_tokens(prompt)
        gen_cost = cost_llm_for_model(in_tokens, out_tokens, model=model, in_known=usage.known, out_known=usage.known)
        status = "stopped" if trace["stopped"] else "done"
        gen_detail = {
            "model": model,
            "temperature": temperature,
            "streaming": streaming,
            "inputTokens": in_tokens,
            "outputTokens": out_tokens,
            "usage_known": usage.known,
            "question": generation_question,
            "citation": citation_meta,
        }
        finish_stage("generate", int((time.perf_counter() - t0) * 1000), gen_cost, f"输出 {out_tokens} tokens", gen_detail, status=status)

        generate_latency = int((time.perf_counter() - t0) * 1000)
        total_latency = int((time.perf_counter() - pipeline_started) * 1000)
        trace["costs"]["total"] = round(total_cost, 6) if total_cost_known else None
        trace["costs"]["total_known"] = total_cost_known
        trace["answer"] = {"text": answer, "hits": selected_hits}
        store.save_trace(trace_id, trace)
        return {
            "text": answer,
            "hits": selected_hits,
            "meta": {
                "latency": generate_latency,
                "total_latency": total_latency,
                "first_token_ms": first_token_ms,
                "tokens": out_tokens,
                "cost": round(total_cost, 6) if total_cost_known else None,
                "followUps": [],
                "trace_id": trace_id,
            },
            "trace": trace,
        }


rag_chat_service = RagChatService()
