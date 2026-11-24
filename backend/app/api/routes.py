from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.app.config import (
    API_PREFIX,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    LLM_MODEL_DEFAULT,
    MILVUS_URI,
    pricing_snapshot,
)
from backend.app.services.indexing import indexing_service
from backend.app.services.milvus_repo import milvus_repo
from backend.app.services.qa_pairs import qa_pair_store
from backend.app.services.rag_chat import rag_chat_service
from backend.app.services.source_loader import source_loader
from backend.app.services.state_store import store

router = APIRouter(prefix=API_PREFIX)


class EstimateBody(BaseModel):
    mode: str = "rebuild"


class IndexBody(BaseModel):
    mode: str = "rebuild"
    confirmed: bool = False


class ChatBody(BaseModel):
    request_id: str | None = None
    question: str
    settings: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


class StopBody(BaseModel):
    request_id: str


@router.get("/health")
def health():
    state = store.get_state()
    return {
        "ok": True,
        "status": "ok",
        "version": "0.1.0",
        "service": "xiyou-rag",
        "milvus": MILVUS_URI,
        "milvus_uri": MILVUS_URI,
        "active_index_version": state.get("active_version"),
        "active_collection": state.get("active_collection"),
        "query_collection": state.get("query_collection"),
        "qa_pairs": qa_pair_store.status(),
    }


@router.get("/settings/defaults")
def settings_defaults():
    return {
        "settings": {
            "top_k": 4,
            "temperature": 0.3,
            "model": LLM_MODEL_DEFAULT,
            "threshold": None,
            "chunk_size": CHUNK_SIZE,
            "chunk_unit": "char",
            "chunk_overlap": CHUNK_OVERLAP,
            "overlap_unit": "char",
            "streaming": True,
            "system_prompt": "你是《西游记》阅读助手。请严格依据检索到的原文片段回答问题，回答末尾用 [n] 标注引用来源。若片段不足以回答，请如实说明。",
        },
        "models": {
            "llm_default": LLM_MODEL_DEFAULT,
            "embedding": EMBEDDING_MODEL,
            "embedding_dim": EMBEDDING_DIM,
        },
        "pricing": pricing_snapshot(),
    }


@router.get("/knowledge/source")
def knowledge_source():
    meta = source_loader.meta()
    state = store.get_state()
    qa_status = qa_pair_store.status()
    return {
        "source": {
            "name": meta.file_name,
            "file_name": meta.file_name,
            "author": meta.author,
            "size": f"{meta.size_bytes / 1024 / 1024:.2f} MB",
            "size_bytes": meta.size_bytes,
            "lines": meta.lines,
            "chapters": meta.chapters,
            "chapter_count": meta.chapters,
            "chunk_count": state.get("chunk_count", 0),
            "chunks": state.get("chunk_count", 0),
            "embedding_model": "text-embedding-v4",
            "dimension": 1024,
            "vector_dim": 1024,
            "indexed_at": state.get("indexed_at"),
            "status": state.get("status", "idle"),
            "index_status": state.get("status", "idle"),
            "active_version": state.get("active_version"),
            "building_version": state.get("sample_version") if state.get("status") == "running" else None,
            "qa_pair_count": int(state.get("qa_pair_count") or qa_status.get("verified") or qa_status.get("loaded") or 0),
            "qa_pairs": qa_status,
        }
    }


@router.get("/knowledge/distribution")
def knowledge_distribution():
    state = store.get_state()
    collection = state.get("query_collection") or state.get("active_collection")
    if collection and milvus_repo.count(collection) > 0:
        rows = milvus_repo.client.query(collection_name=collection, filter="chunk_id != ''", output_fields=["chapter"], limit=16384)
        chunks = [type("C", (), {"chapter": int(r.get("chapter", 0) or 0)})() for r in rows]
        return {"items": source_loader.distribution(chunks)}
    chunks = source_loader.chunk(chapter_limit=20)
    return {"items": source_loader.distribution(chunks)}


@router.get("/knowledge/chunks/{chunk_id}")
def knowledge_chunk(chunk_id: str):
    state = store.get_state()
    collection = state.get("query_collection") or state.get("active_collection")
    row = milvus_repo.get_chunk(collection, chunk_id) if collection else None
    if not row:
        for chunk in source_loader.chunk(chunk_limit=2000):
            if chunk.id == chunk_id:
                return {"chunk": {
                    "id": chunk.id,
                    "chapter": chunk.chapter,
                    "chapter_title": chunk.chapter_title,
                    "chapterTitle": f"第 {chunk.chapter} 回",
                    "text": chunk.text,
                    "tokens": chunk.tokens,
                    "source": chunk.source,
                }}
        raise HTTPException(status_code=404, detail="未找到片段")
    chapter = int(row.get("chapter", 0) or 0)
    return {
        "chunk": {
            "id": row.get("chunk_id"),
            "chapter": chapter,
            "chapter_title": row.get("chapter_title"),
            "chapterTitle": f"第 {chapter} 回",
            "text": row.get("text"),
            "tokens": row.get("tokens"),
            "source": row.get("source"),
        }
    }


@router.post("/knowledge/index/estimate")
def estimate_index(body: EstimateBody):
    try:
        return indexing_service.estimate(body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/knowledge/index")
def start_index(body: IndexBody):
    try:
        return indexing_service.start(body.mode, body.confirmed)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/knowledge/index/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    payload = dict(job)
    payload.setdefault("id", job.get("job_id"))
    return {"job": payload}


@router.get("/chat/traces/{trace_id}")
def get_trace(trace_id: str):
    trace = store.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return {"trace": trace}


@router.post("/chat/stop")
def stop_chat(body: StopBody):
    ok = store.cancel_request(body.request_id)
    return {"ok": ok, "request_id": body.request_id}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/query")
def chat_query(body: ChatBody, request: Request):
    request_id = body.request_id or uuid.uuid4().hex
    cancel_event = store.register_cancel(request_id)

    def event_stream():
        events: list[str] = []

        def emit(key: str, patch: dict[str, Any]):
            if key in {"hits", "token"}:
                packet = {**patch}
            else:
                packet = {"type": "stage", "key": key, "patch": patch, **patch}
            events.append(_sse(packet.get("type", "stage") if key in {"hits", "token"} else "stage", packet))

        try:
            result = rag_chat_service.run(
                {"request_id": request_id, "question": body.question, "settings": body.settings or {}, "messages": body.messages},
                emit,
                cancel_event=cancel_event,
            )
            events.append(_sse("trace", {"type": "trace", "trace": result.get("trace"), "trace_id": result["meta"].get("trace_id")}))
            events.append(_sse("answer", {"type": "answer", "text": result.get("text"), "hits": result.get("hits"), "meta": result.get("meta"), "trace_id": result["meta"].get("trace_id")}))
            events.append(_sse("done", {"type": "done", "ok": True, "trace_id": result["meta"].get("trace_id")}))
        except Exception as exc:
            events.append(_sse("error", {"type": "error", "message": str(exc)}))
            events.append(_sse("done", {"type": "done", "ok": False}))
        finally:
            store.drop_cancel(request_id)
        return events

    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        def stream():
            for chunk in event_stream():
                yield chunk
        return StreamingResponse(stream(), media_type="text/event-stream")

    # 非流式兼容：一次性返回 events
    packets = []
    def collect_emit(key, patch):
        if key in {"hits", "token"}:
            packets.append({"type": key, **patch})
        else:
            packets.append({"type": "stage", "key": key, "patch": patch, **patch})
    try:
        result = rag_chat_service.run(
            {"request_id": request_id, "question": body.question, "settings": body.settings or {}, "messages": body.messages},
            collect_emit,
            cancel_event=cancel_event,
        )
        packets.extend([
            {"type": "trace", "trace": result.get("trace"), "trace_id": result["meta"].get("trace_id")},
            {"type": "answer", "text": result.get("text"), "hits": result.get("hits"), "meta": result.get("meta")},
            {"type": "done", "ok": True},
        ])
    except Exception as exc:
        packets.append({"type": "error", "message": str(exc)})
    finally:
        store.drop_cancel(request_id)
    return JSONResponse({"events": packets})
