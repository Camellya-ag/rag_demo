"""Canonical HTTP route catalog for docs and contract tests.

Keep this module aligned with `backend/app/api/routes.py` and
`backend/docs/API_CONTRACT.md`.
"""

from __future__ import annotations

API_PREFIX = "/api"

# method, path (relative to API_PREFIX), brief description
CONTRACT_ROUTES: list[tuple[str, str, str]] = [
    ("GET", "/health", "服务与索引健康状态"),
    ("GET", "/settings/defaults", "默认问答/切片/计费配置"),
    ("GET", "/knowledge/source", "素材与索引状态（前端左侧信息源）"),
    ("GET", "/knowledge/distribution", "章节切片分布"),
    ("GET", "/knowledge/chunks/{chunk_id}", "单条原文切片"),
    ("POST", "/knowledge/index/estimate", "入库费用估算"),
    ("POST", "/knowledge/index", "创建索引任务（需 confirmed=true）"),
    ("GET", "/knowledge/index/jobs/{job_id}", "索引任务进度"),
    ("POST", "/chat/query", "RAG 问答（SSE 或 JSON events）"),
    ("POST", "/chat/stop", "停止流式问答"),
    ("GET", "/chat/traces/{trace_id}", "查询一次问答 trace"),
]

CHAT_SSE_EVENTS = ["stage", "hits", "token", "trace", "answer", "error", "done"]

INDEX_MODES = ["initial", "rebuild", "dev_sample"]

DEPRECATED_ROUTE_HINTS = {
    "/api/v1": "已废弃，统一使用 /api",
    "/chat/stream": "已废弃，请用 POST /api/chat/query",
    "/knowledge/status": "已废弃，请用 GET /api/knowledge/source",
    "/knowledge/index/tasks": "已废弃，请用 POST /api/knowledge/index",
}

