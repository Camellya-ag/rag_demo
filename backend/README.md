# 西游问典后端

FastAPI 服务，默认监听 `http://127.0.0.1:8010`，接口前缀 `/api`，与 `frontweb/src/api/contract.md` 对齐。

## 重启（改代码后加载新逻辑）

```powershell
powershell -ExecutionPolicy Bypass -File backend\restart.ps1
```

前台开发（`--reload`，勿与 restart 多实例并行）：

```powershell
powershell -ExecutionPolicy Bypass -File backend\run.ps1 -Reload
```

## 启动

```powershell
cd D:\document\rag\rag_demo
# 复用 rag_examples 虚拟环境（已含 pymilvus / dashscope / openai）
D:\document\rag\rag_examples\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010 --reload
```

健康检查：`GET http://127.0.0.1:8010/api/health`

## 关键行为

- 混合召回：Milvus 稠密 1024 维 + 中文 BM25，RRF 融合，百炼 rerank 默认开启。
- 查询改写：保留原问题，并结合近期上下文补充原著关键词；**原问题与改写结果共同参与召回**。
- 开发样本：`mode=dev_sample` 少量切片联调，**不会替换正式 production 索引**（可通过 `XIYOU_ALLOW_DEV_SAMPLE=false` 关闭）。
- 正式全书：`mode=initial` / `mode=rebuild` 均覆盖全书切片 + 问答对生成，须先 `POST /knowledge/index/estimate`，再 `confirmed=true` 启动任务；失败时回滚，不污染旧 collection。
- 停止流式：`POST /api/chat/stop` 后，已发生阶段的真实费用会保留在 trace 中，不会清零。
- 问答对：`backend/data/qa_pairs.jsonl` 为正式持久化；命中后映射原文 chunk 参与 RRF / rerank，生成答案不作证据。

接口契约（现行）：`backend/docs/API_CONTRACT.md`（自动校验：`backend/tests/test_api_contract.py`）。  
效果评测：`backend/docs/EVALUATION.md`（`backend/scripts/run_eval.py`）。  
历史文档：`wmk/需求112401-完成后端与联调/接口契约.md`（含旧 `/api/v1` 路径，仅作对照）。  
RAG 实现目录：`backend/app/ai/rag/`（见 `backend/docs/STRUCTURE.md`）。
