# 后端目录说明（对照 base_fastapi_ai）

基项目习惯：`app/core`（配置/中间件/异常）、`app/modules/*`（业务域）、`app/ai/rag`（检索管线）。  
本项目**未引入 MySQL/RBAC**，RAG 管线在 `app/ai/rag/`，其余与基项目对齐：

| 基项目概念 | 本项目路径 |
|-----------|-----------|
| `app/core` 日志/中间件/异常 | `backend/app/core/` |
| 路由聚合 | `backend/app/router_registry.py` + `backend/app/api/routes.py` |
| RAG 管线 | `backend/app/ai/rag/`（`rag_chat`、`milvus_repo`、`indexing`、`rewrite`、`embedding_client` 等） |
| 问答对 | `backend/app/ai/rag/qa_generation.py`、`qa_pairs.py` |
| 索引/任务状态 | `backend/app/ai/rag/state_store.py` |
| 配置 | `backend/app/config.py` |

`backend/app/services/` 仅保留兼容 re-export（可选从 `backend.app.ai.rag` 导入）。路由层 `api/routes.py` 直接引用 `ai.rag`。
