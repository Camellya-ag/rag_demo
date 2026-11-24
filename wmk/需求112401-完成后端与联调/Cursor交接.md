# 西游问典项目交接

更新时间：2026-11-24 19:45。**需求「完成后端与联调」已收尾。**

## 交付结论

| 项 | 状态 |
|----|------|
| 全书索引 production | `xiyou_rag_v20261124193025`，1596 chunks |
| 问答对 | 206 条已验证持久化（估算 300 为上限，校验未通过会剔除） |
| RAG 链路 | 改写+双路稠密+稀疏+QA→RRF→rerank→生成+trace |
| 前端 | 双栏、背景图、真实分布图、全链路弹窗/复制 |
| 测试 | 后端 unittest 18/18；Playwright 冒烟+集成 |
| Git | 已提交并推送 `main`（见下方提交说明） |
| qa_pilot | 已删除；样例见 `backend/data/fixtures/qa_pairs.sample.jsonl` |
| 单价 | `backend/docs/PRICING.md`（华北2北京官方原价换算） |

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