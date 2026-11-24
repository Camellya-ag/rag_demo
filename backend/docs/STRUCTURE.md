# 后端目录说明（对照 base_fastapi_ai）

基项目习惯：`app/core`（配置/中间件/异常）、`app/modules/*`（业务域）、`app/ai/rag`（检索管线）。  
本项目**未引入 MySQL/RBAC**，RAG 以 `app/services/` 为业务实现层，其余与基项目对齐：

| 基项目概念 | 本项目路径 |
|-----------|-----------|
| `app/core` 日志/中间件/异常 | `backend/app/core/` |
| 路由聚合 | `backend/app/router_registry.py` + `backend/app/api/routes.py` |
| RAG 管线 | `backend/app/services/rag_chat.py`、`milvus_repo.py`、`indexing.py` |
| 问答对 | `backend/app/services/qa_generation.py`、`qa_pairs.py` |
| 配置 | `backend/app/config.py` |

后续若拆 `app/modules/rag/`，可将 `services` 内 RAG 相关模块平移，路由层保持不变。