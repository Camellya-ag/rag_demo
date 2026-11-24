# 西游问典前端 API 契约

> 现行后端契约：`backend/docs/API_CONTRACT.md`（以此为准）。
> 废弃：`/api/v1/*`、`/chat/stream`、`/knowledge/status`、`/knowledge/index/tasks/*`。

默认通过 Vite 代理访问 `http://127.0.0.1:8010`，也可使用 `VITE_API_BASE` 直连。

## 健康检查
- `GET /api/health`
- 返回：`{ ok, version, milvus, active_index_version }`

## 知识库
- `GET /api/knowledge/source`
- `GET /api/knowledge/distribution`
- `GET /api/knowledge/chunks/{id}`
- `POST /api/knowledge/index/estimate` body: `{ mode: "initial" | "rebuild" }`
- **`initial`**：首次**正式**生产入库（全文 + 问答对），必须先 estimate 再 `confirmed=true`；前端不向用户展示“样本验证”流程
- **`rebuild`**：在同语义下重建生产索引并切换版本
- 后端若保留 `sample` 限额仅用于开发自测，不应通过 `initial` 的 `warning` 误导正式用户；应返回全文 `chunk_count` / `qa_pair_count` 与分项费用
- estimate 响应建议包含：`chunk_count`、`qa_pair_count`、`total_cost`、`stages[]`（如 `chunk_embed` / `qa_generate` / `qa_embed`），每项可带 `usage_known`
- `qa_pair_count` 与 `source.qa_pairs.verified` 保持一致（verified 为权威口径）
- `POST /api/knowledge/index` body: `{ mode, confirmed: true }`
- `GET /api/knowledge/index/jobs/{job_id}`

## 问答（SSE 优先）
- `POST /api/chat/query`
- body:
```json
{
  "request_id": "uuid",
  "question": "...",
  "settings": { "top_k": 4, "temperature": 0.3, "model": "qwen-plus", "streaming": true, "system_prompt": "..." },
  "messages": [{ "role": "user", "content": "..." }]
}
```
- SSE 事件：`stage` `hits` `token` `answer` `error` `done`
- 可选：`answer` / `done` 携带 `trace`（或 `meta.trace`），用于回填整条链路快照；前端也会从流式 `stage` 事件累积
- `retrieve.detail` 建议包含 `qa_pairs[]`（正式召回，不再试点），字段：`id`、`question`、`scoreText`、`mapped_chunk_ids`
- `POST /api/chat/stop` body: `{ "request_id": "uuid" }`

## 效果评测

- 固定评测集：`backend/data/eval/eval_questions.json`
- 运行说明：`backend/docs/EVALUATION.md`
