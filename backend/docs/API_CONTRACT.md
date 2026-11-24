# 西游问典 API 契约（现行版）

> **单一事实来源**：`backend/app/api/routes.py` + `backend/app/api/contract_catalog.py`。
> 契约测试：`backend/tests/test_api_contract.py`。

## 基址与代理

- 后端：`http://127.0.0.1:8010`
- 统一前缀：`/api`（**不是** `/api/v1`）
- 前端 Vite 代理：`/api -> http://127.0.0.1:8010`

## 废弃路径对照

| 旧文档路径 | 现行路径 |
|-----------|----------|
| `POST /api/v1/chat/stream` | `POST /api/chat/query` |
| `GET /api/v1/knowledge/status` | `GET /api/knowledge/source` |
| `POST /api/v1/knowledge/index/tasks` | `POST /api/knowledge/index` |
| `GET /api/v1/knowledge/index/tasks/{id}` | `GET /api/knowledge/index/jobs/{job_id}` |

## 路由一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查、活动索引版本、QA 状态 |
| GET | `/api/settings/defaults` | 默认模型/切片/价格 |
| GET | `/api/knowledge/source` | 素材与索引状态 |
| GET | `/api/knowledge/distribution` | 章节切片分布 |
| GET | `/api/knowledge/chunks/{chunk_id}` | 单条切片详情 |
| POST | `/api/knowledge/index/estimate` | 入库费用估算 |
| POST | `/api/knowledge/index` | 创建索引任务 |
| GET | `/api/knowledge/index/jobs/{job_id}` | 索引任务进度 |
| POST | `/api/chat/query` | RAG 问答（SSE 或 JSON events） |
| POST | `/api/chat/stop` | 按 `request_id` 停止流式请求 |
| GET | `/api/chat/traces/{trace_id}` | 获取一次问答 trace |

## 关键字段口径

### `qa_pair_count`

- **以 `qa_pairs.verified` 为准**。
- `GET /api/knowledge/source` 中 `source.qa_pair_count` 与 `source.qa_pairs.verified` 保持一致。
- `state.json` 中历史值若不一致，启动时会由 `qa_pair_store.reconcile_state_qa_pair_count()` 自动修复。

### 索引模式 `mode`

- `initial`：首次正式全书入库
- `rebuild`：重建并切换 production 版本
- `dev_sample`：开发样本（默认不替换 production）

## 问答：`POST /api/chat/query`

### 请求

```json
{
  "request_id": "optional-uuid",
  "question": "孙悟空是怎么出生的？",
  "settings": {
    "top_k": 4,
    "threshold": 0.35,
    "temperature": 0.3,
    "model": "qwen-flash",
    "streaming": true,
    "system_prompt": "你是《西游记》阅读助手……"
  },
  "messages": [{"role": "user", "content": "……"}]
}
```

### 响应

- `Accept: text/event-stream`：SSE 事件流
- `Accept: application/json`：一次性返回 `{"events": [...]}`

事件类型：`stage` `hits` `token` `trace` `answer` `error` `done`

`stage` 固定顺序：`rewrite` → `embed` → `retrieve` → `fusion` → `rerank` → `assemble` → `generate`

## 索引流程

1. `POST /api/knowledge/index/estimate`（`mode=initial|rebuild`）
2. 前端展示 `chunk_count`、`qa_pair_count`、`total_cost`、`stages[]`
3. `POST /api/knowledge/index`，`{"mode": "rebuild", "confirmed": true}`
4. 轮询 `GET /api/knowledge/index/jobs/{job_id}`

## 前端契约镜像

`frontweb/src/api/contract.md` 与本文件保持同路径/同字段；有冲突时以本文件为准。

