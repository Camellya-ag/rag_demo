from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from backend.app.config import CANDIDATE_LIMIT, DEFAULT_TOP_K, LLM_MODEL_DEFAULT
from backend.app.ai.rag.embedding_client import embedding_client
from backend.app.ai.rag.llm_client import llm_client
from backend.app.ai.rag.milvus_repo import milvus_repo
from backend.app.ai.rag.qa_pairs import qa_pair_store
from backend.app.ai.rag.rerank_client import rerank_client
from backend.app.ai.rag.rewrite import rewrite_query
from backend.app.ai.rag.state_store import store
from backend.app.utils.pricing import Cost, Usage, cost_embed, cost_llm_for_model, cost_rerank
from backend.app.utils.text import estimate_tokens, snippet

StageEmitter = Callable[[str, dict[str, Any]], None]


def _stage(emit: StageEmitter, key: str, **patch: Any) -> None:
    emit(key, patch)


def _hit_from_row(row: dict[str, Any], rank: int, score: float) -> dict[str, Any]:
    chapter = int(row.get("chapter", 0) or 0)
    return {
        "id": row.get("id") or row.get("chunk_id"),
        "rank": rank,
        "score": float(score),
        "scoreText": f"{float(score):.3f}",
        "chapter": chapter,
        "chunk": {
            "id": row.get("id") or row.get("chunk_id"),
            "chapter": chapter,
            "chapterTitle": f"第 {chapter} 回",
            "chapter_title": row.get("chapter_title") or f"第 {chapter} 回",
            "text": row.get("text", ""),
            "tokens": int(row.get("tokens", 0) or 0),
            "source": row.get("source", "西游记.txt"),
        },
    }


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

        t0 = time.perf_counter()
        embed_inputs = [rewritten["original"], rewritten["rewritten"]]
        vectors, usage = embedding_client.embed(embed_inputs)
        if len(vectors) < 2:
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
        sparse_queries = [rewritten["original"], rewritten["rewritten"]]
        if rewritten.get("keywords"):
            sparse_queries.append(" ".join(rewritten["keywords"][:6]))
        dense_original = milvus_repo.dense_search(collection, vectors[0], CANDIDATE_LIMIT)
        dense_rewritten = milvus_repo.dense_search(collection, vectors[1], CANDIDATE_LIMIT)
        sparse_merged: dict[str, dict[str, Any]] = {}
        for q in sparse_queries:
            q = str(q or "").strip()
            if not q:
                continue
            for row in milvus_repo.sparse_search(collection, q, CANDIDATE_LIMIT):
                prev = sparse_merged.get(row["id"])
                if not prev or row["score"] > prev["score"]:
                    sparse_merged[row["id"]] = row
        sparse = sorted(sparse_merged.values(), key=lambda x: x["score"], reverse=True)[:CANDIDATE_LIMIT]
        for i, row in enumerate(sparse, 1):
            row["rank"] = i
        qa_hits = qa_pair_store.recall(rewritten["original"], rewritten["rewritten"])
        qa_channel = qa_pair_store.build_chunk_channel(collection, qa_hits, milvus_repo, limit=CANDIDATE_LIMIT)
        retrieve_detail = {
            "indexSize": milvus_repo.count(collection),
            "dense_original": {"metric": "余弦相似度", "items": dense_original},
            "dense_rewritten": {"metric": "余弦相似度", "items": dense_rewritten},
            "sparse": {"metric": "BM25", "items": sparse},
            "qa_pairs": qa_hits,
            "sparse_queries": sparse_queries,
        }
        trace["channels"] = {
            "dense_original": dense_original,
            "dense_rewritten": dense_rewritten,
            "sparse": sparse,
            "qa_pairs": qa_hits,
            "qa_chunks": qa_channel,
        }
        finish_stage(
            "retrieve",
            int((time.perf_counter() - t0) * 1000),
            Cost(0, usage_known=True),
            f"稠密 {len(dense_original) + len(dense_rewritten)} · 稀疏 {len(sparse)} · QA {len(qa_channel)}",
            retrieve_detail,
        )

        t0 = time.perf_counter()
        fused = milvus_repo.rrf_fuse_channels([dense_original, dense_rewritten, sparse, qa_channel])
        fusion_detail = {
            "method": "RRF",
            "k": 60,
            "channels": ["dense_original", "dense_rewritten", "sparse", "qa_chunks"],
            "items": fused,
        }
        trace["fusion"] = fusion_detail
        finish_stage("fusion", int((time.perf_counter() - t0) * 1000), Cost(0), f"合并 {len(fused)} 条", fusion_detail)

        t0 = time.perf_counter()
        docs = [row.get("text", "") for row in fused]
        rerank_scores, rerank_usage = rerank_client.score(rewritten["rewritten"], docs)
        rerank_cost = cost_rerank(rerank_usage.total_tokens or estimate_tokens(rewritten["rewritten"]) + sum(estimate_tokens(d) for d in docs), rerank_usage)
        reranked = []
        for row, score in zip(fused, rerank_scores):
            item = dict(row)
            item["rerankScore"] = float(score)
            item["rerankText"] = f"{float(score):.3f}"
            reranked.append(item)
        reranked.sort(key=lambda x: x.get("rerankScore", 0), reverse=True)
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
            "model": rerank_client.model,
            "threshold": threshold,
            "dropped": len(dropped),
            "tokens": rerank_usage.total_tokens,
            "items": reranked,
        }
        trace["rerank"] = rerank_detail
        finish_stage("rerank", int((time.perf_counter() - t0) * 1000), rerank_cost, f"保留 {len(reranked)} 条", rerank_detail)

        hits = [_hit_from_row(row, idx + 1, row.get("rerankScore", row.get("score", 0))) for idx, row in enumerate(reranked)]
        emit("hits", {"type": "hits", "hits": hits})

        context_parts = []
        for idx, hit in enumerate(hits, 1):
            chunk = hit["chunk"]
            context_parts.append(f"[{idx}] 第{chunk['chapter']}回 {chunk['id']}\n{chunk['text']}")
        prompt = (
            f"{system_prompt}\n\n检索片段：\n"
            + ("\n\n".join(context_parts) if context_parts else "（无命中片段）")
            + f"\n\n问题：{question}\n\n请用中文回答，并在句末使用 [n] 标注引用。"
        )
        assemble_detail = {"ids": [h["id"] for h in hits], "tokens": estimate_tokens(prompt), "budget": 2048, "prompt": prompt}
        trace["assemble"] = assemble_detail
        finish_stage("assemble", 0, Cost(0), f"入选 {len(hits)} 个片段", assemble_detail)

        if not hits:
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

        t0 = time.perf_counter()
        _stage(emit, "generate", status="running", ms=0, cost=0, summary=f"{model} 生成中", detail={"model": model, "temperature": temperature})
        answer_parts: list[str] = []
        usage = Usage()
        if streaming:
            for piece in llm_client.stream_answer(prompt, model=model, temperature=temperature):
                if cancel_event and cancel_event.is_set():
                    trace["stopped"] = True
                    break
                if isinstance(piece, dict) and piece.get("__usage__"):
                    usage.merge(piece["__usage__"])
                    continue
                answer_parts.append(piece)
                emit("token", {"type": "token", "text": piece})
        else:
            text, usage = llm_client.complete(prompt, model=model, temperature=temperature)
            answer_parts.append(text)
            emit("token", {"type": "token", "text": text})

        answer = "".join(answer_parts).strip()
        out_tokens = usage.output_tokens or estimate_tokens(answer)
        in_tokens = usage.input_tokens or estimate_tokens(prompt)
        gen_cost = cost_llm_for_model(in_tokens, out_tokens, model=model, in_known=usage.known, out_known=usage.known)
        status = "stopped" if trace["stopped"] else "done"
        gen_detail = {"model": model, "temperature": temperature, "streaming": streaming, "inputTokens": in_tokens, "outputTokens": out_tokens, "usage_known": usage.known}
        finish_stage("generate", int((time.perf_counter() - t0) * 1000), gen_cost, f"输出 {out_tokens} tokens", gen_detail, status=status)

        latency = int((time.perf_counter() - t0) * 1000)
        trace["costs"]["total"] = round(total_cost, 6) if total_cost_known else None
        trace["costs"]["total_known"] = total_cost_known
        trace["answer"] = {"text": answer, "hits": hits}
        store.save_trace(trace_id, trace)
        return {
            "text": answer,
            "hits": hits,
            "meta": {
                "latency": latency,
                "tokens": out_tokens,
                "cost": round(total_cost, 6) if total_cost_known else None,
                "followUps": [],
                "trace_id": trace_id,
            },
            "trace": trace,
        }


rag_chat_service = RagChatService()
