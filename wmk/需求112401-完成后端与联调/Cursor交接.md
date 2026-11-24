# 西游问典项目交接

更新时间：2026-11-24。**需求与 UI 链路展示均已验收；代码已推送 `main`。**

## 交付结论

| 项 | 状态 |
|----|------|
| 全书索引 production | `xiyou_rag_v20261124193025`，1596 chunks |
| 问答对 | 206 条已验证持久化（估算 300 为上限，校验未通过会剔除） |
| RAG 链路 | 改写+双路稠密+稀疏+QA→RRF→rerank→生成+trace |
| 前端 | 双栏、西游背景图、真实分布图、全链路弹窗/复制、步骤详情默认展开 |
| 测试 | 后端 unittest 23/23；Playwright 3/3（冒烟 2 + 集成 1） |
| 索引发布 | production 成功：版本快照 + 正式 qa_pairs.jsonl 同事务切换；失败不污染旧索引/旧 QA |
| Git | 已提交并推送 `main`（见下方提交说明） |
| qa_pilot | 已删除；样例见 `backend/data/fixtures/qa_pairs.sample.jsonl` |
| 单价 | `backend/docs/PRICING.md`（华北2北京官方原价换算） |

## 核心功能说明

- 查询前 `qa_pair_store.sync_with_state()`，按 `query_mode` 与版本读取 `backend/data/qa_snapshots/{version}.jsonl`；无快照时兼容现有 `qa_pairs.jsonl`（当前 production `v20261124193025`）。
- 若仅有历史 `qa_pairs.jsonl`、无对应版本快照，启动/查询时会自动回填 `{version}.jsonl`（不提交到 Git）。
- 前端全链路复制日志：`traceLog.js` 展示稠密原问/改写双路、真实 tokens，密钥字段脱敏。
- 西游主题图已接入 `frontweb/public/bg/`（`xiyou-mist.png`、`xiyou-hero.png`），支持 `prefers-reduced-motion`。
- 全链路弹窗 `RetrievalPanel` 支持 `expandAll`，逐步展示 `detail`（稠密双路、融合、重排序号等）。
- embed trace 补充 `queries` / `preview`；rerank 命中带 `rerankRank`。

## 验收对照

- `需求.md`：后端联调、混合检索、rerank、费用展示、确认后入库、适量测试 — **已完成**
- `改ui/需求.md`：页面展示完整 RAG 链路与各步情况 — **已完成**

## 非阻断遗留

- 后端未拆 `app/ai/rag`（见 `backend/docs/STRUCTURE.md`）
- 多历史版本 QA 批量快照脚本（production 已快照 + 自动回填）

## 运行

- 后端：`backend/run.ps1` 或 README 中 uvicorn `8010`
- 前端：`frontweb` → `npm run dev` → `5180`
- 密钥：仅读 `D:\document\rag\rag_examples\.env`，勿提交

## 原始需求与用户约束

（见历史段落；核心已全部落地。）

## 参考位置

- 后端：`backend/app/`；结构说明 `backend/docs/STRUCTURE.md`
- 前端：`frontweb/src/`；契约 `frontweb/src/api/contract.md`
- 接口说明：`wmk/需求112401-完成后端与联调/接口契约.md`
