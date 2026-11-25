# 西游问典高价值问题修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复已经发现的实时响应、查询理解、证据评测与索引可靠性问题，由 Composer 实施，主管会话负责代码审查和验收。

**Architecture:** 保留 Vue 3 + FastAPI + Milvus 的现有架构及接口契约，以局部修复恢复已有能力。每组先建立有实际行为断言的回归测试，再最小修改；不引入 Agent 框架、GraphRAG、任务队列或新数据库。

**Tech Stack:** Vue 3、Element Plus、Vite、Playwright、Python unittest、FastAPI、Milvus、百炼模型。

**Spec:** 本文件的「范围与证据」即实施规格；用户已授权整理高价值问题后，开新会话使用 Composer 修改，由原会话管控。无需再询问是否执行。

## Global Constraints

- 工作目录：`D:\document\rag\rag_demo`，复用当前 checkout；Composer 负责主体实现，主管负责审查、验收测试与文档，并可接手已复现的局部收尾修复。修改前向实施会话明确文件归属，避免并行覆盖。
- 遵守根目录 AGENTS.md 和用户提供的同名约定；`wmk/` 不提交、不推送、不删除。
- 初始 Git 状态只有 `?? backend/data/eval/results/`，其中是用户已有评测产物，勿清理或加入修改。
- 初次探测 8010/5180 都未响应，且未发现本项目 Python/Node 进程。后续必须重新探测；只在确实不可用时启动一组所需服务，并说明原因。
- 页面测试必须使用 Playwright 真正打开页面并断言交互；不得用构建成功代替页面测试，不使用 Chrome MCP。
- 修改后端并需 8010 生效时使用项目 `backend/restart.ps1`，不得重复启动 uvicorn。
- Python 环境可用：`D:\document\rag\rag_examples\.venv\Scripts\python.exe`。
- 不调用收费模型做批量评测，不重建正式索引，不发布、不推送；使用可控假模型、临时存储和现有前端的 Playwright route mock 验证行为。
- 不自行提交代码；若后续用户要求提交，标题与正文必须中文。
- 沿用公开接口，必要时只添加兼容字段；更新相关契约/说明。

## 范围与证据

1. `backend/app/api/routes.py:223` 将事件存进列表，`rag_chat_service.run()` 完成后才向 StreamingResponse 迭代返回。主管用实际路由函数及假模型复现：模型每 40ms 产生一个 token，3 个 token 全在约 122ms 被收到。
2. `frontweb/src/App.vue:202` 创建普通 answerMsg 对象，推入 ref 数组后回调仍修改原对象，存在绕过 Vue 代理的响应式更新问题。
3. `backend/app/ai/rag/rewrite.py:29` 循环 replace 连锁替换，已复现：孙悟空→孙孙悟空，猪八戒→猪猪八戒，大师兄→孙孙悟空。历史用于检索改写，但 `rag_chat.py:294` 最终生成只见原追问和命中，没有明确消解后的问题；`llm_client.py` 的流式与非流式约束也不同。
4. `utils/text.py:216` 无引用时强补 [1]，不校验 [99] 是否越界；`evaluation.py:50` 把生成答案混进检索评分，任一关键词即判命中。主管已复现：hits=[]、答案只含一个关键词和 [99]，retrieval_ok/citation_ok 均为 True。现有 6 个 rewrite/evaluation 单测全部通过，未覆盖这些反例。
5. `rag_chat.py:136,172` 原问题与改写相同仍重复 embedding/检索，两次 hybrid_search 重复 BM25；融合时相同通道重复投票。`rag_chat.py:299` 写入 budget=2048 却未执行预算控制；meta.latency 仅统计生成阶段。
6. `indexing.py:165` 在 worker lock 外捕获旧状态，而 create_job 已将全局状态设为 running；失败回滚可能恢复 running，排队任务可能回滚到更早的索引。版本名仅精确到秒。`state_store.py:55` 直接覆盖 JSON，损坏读取静默回默认值，重启无未完成任务协调。

已有能力要保留：中文 BM25 + dense + RRF + rerank、QA 回映射原文、生产/样本隔离、引用弹窗、七阶段 trace、费用未知标记。

## Review Focus

- 模型尚未完成时，第一个阶段和 token 已到达客户端；Vue 页面已出现部分文字。
- 原问题已经规范化、包含多个人物或追问指代不清时，改写不重复污染实体，也不凭空确定指代。
- 无检索证据或引用越界时，评测不得成功；引用格式修复不能伪造证据。
- 停止、断连、异常、非流式分支均正确终止并清理资源；已发生费用不伪装为零。
- 同秒请求、排队失败、文件写入中断、进程重启不得丢失最近成功发布的索引。

## Task 1：恢复前后端实时流式与可靠停止

**Files:** `backend/app/api/routes.py`、`backend/app/ai/rag/llm_client.py`、`backend/app/ai/rag/rag_chat.py`、`frontweb/src/App.vue`；新增对应后端测试及 `frontweb/tests/streaming.spec.js`。

**Interfaces:** 保留 POST /api/chat/query 的 SSE stage/hits/token/trace/answer/done，以及 JSON events 兼容分支、POST /api/chat/stop。

- [ ] 先用可控假服务编写测试：发出 first token 后阻塞直到测试释放；HTTP 消费者必须在释放前收到 first token，而非只检查最终 events 内容。
- [ ] 改成生产与消费并行的有界事件通道或直接逐事件生成，确保错误、done、取消均不会死锁；线程/流资源显式清理，保留真实费用信息。
- [ ] 修正 answerMsg 与 trace 的响应式更新路径，测试不能依赖 busy 最后变化触发刷新。
- [ ] Playwright 打开真实 Vite 页面，以分时返回的 SSE route mock 断言：请求完成前 partial text 可见、阶段进度变化；点击停止后不再追加文本；下一轮仍可发送。
- [ ] 验证非流式输出与失败分支；更新契约中必要说明。

## Task 2：修正查询改写和多轮生成输入

**Files:** `backend/app/ai/rag/rewrite.py`、`backend/app/ai/rag/rag_chat.py`、`backend/app/ai/rag/llm_client.py`、`backend/tests/test_rewrite.py`，必要时 `frontweb/src/services/ragService.js`。

**Interfaces:** 保留 rewrite_query(question, messages) 的 existing 字段；生成仍以检索原文为依据。

- [ ] 先新增测试：孙悟空、猪八戒原名保持不变；猴哥/大师兄一次变为孙悟空；重复应用别名转换不再变化；句内多个实体不被重复前缀污染。
- [ ] 避免替换结果重新进入短别名替换，保护完整专名；不靠清理“孙孙”之类事后特判修复。
- [ ] 测试“前轮猪八戒，追问他原来叫什么”等多轮输入；明确生成可见消解后的完整问题或受控近期历史，不将历史模型回答当原文证据。
- [ ] 统一流式和非流式的基于证据、不足说明约束；保留原问题和改写问题的可观测性。
- [ ] 运行改写与聊天测试，确保不需要真实模型。

## Task 3：修正引用与评测的假阳性

**Files:** `backend/app/utils/text.py`、`backend/app/ai/rag/evaluation.py`、`backend/tests/test_evaluation.py`、`backend/scripts/run_eval.py`、`backend/docs/EVALUATION.md`、`backend/docs/RETRIEVAL_TUNING.md`。

**Interfaces:** 引用编号对应本轮 hits；检索评分仅使用 retrieved context，生成质量分开记录；结果字段向后兼容或明确版本。

- [ ] 先增加反例：hits=[] 且答案含关键词/数字引用不得判检索成功或有效引用；2 个 hits 的 [99] 不合格；未标引用的答案不得自动变成有证据支持。
- [ ] 删除无依据强补 [1] 的行为，或将其显式视为未验证格式修复，不得计入有效引用；不要新增一次收费模型调用补标。
- [ ] 拆开检索文本与答案文本评分，清晰定义章节/关键词作为弱代理的限制；范围校验引用，区分格式有效与证据支持，避免声称已做语义核验。
- [ ] 数据集补少量无答案/越界/多轮/别名回归题，既有 20 题基线保留并注明不可直接比较；记录答案、命中、模型/索引与数据集/代码版本以便离线复算。
- [ ] 更新测试和说明；不执行真实付费全量评测，不把旧 5 题通过宣称为全量通过。

## Task 4：消除重复检索并执行上下文预算

**Files:** `backend/app/ai/rag/rag_chat.py`、`backend/app/ai/rag/milvus_repo.py`，新增或扩展对应单测。

**Interfaces:** 保留原始/改写/QA 通道含义；trace 如复用结果须如实说明，不伪造多路召回。

- [ ] 先用调用计数断言：原问题等于改写时只 embed 一次；同 collection + 同 query 的 BM25 只查一次，原始 dense 结果可复用。
- [ ] 复用稀疏结果并对查询去重；避免相同独立通道被重复计权。不要大规模引入 Redis/语义缓存。
- [ ] 编写预算测试：大 topK 或长 prompt 时按剩余预算选择/去重原文，trace 中输入 token/预算与实际行为一致；预算保留当前 2048 的现有意图，明确是估算值，勿称精准 tokenizer。
- [ ] latency 分离全链路与 generate 时长，新增首字指标供流式验收使用；测试包含前置阶段耗时。
- [ ] 用假 embedding/repository/rerank/LLM 跑完整服务链验证，不能用 mock 掉被测逻辑的测试代替。

## Task 5：保护索引状态和失败恢复

**Files:** `backend/app/ai/rag/indexing.py`、`backend/app/ai/rag/state_store.py`、`backend/app/main.py`、`backend/tests/test_indexing.py`，新增临时文件状态测试。

**Interfaces:** 保留 initial/rebuild/dev_sample 及确认语义；失败保持最近成功版本，生产与样本分离。

- [ ] 用真实 StateStore + 临时文件和假 Milvus 建立测试：失败任务不恢复 running；A 成功后排队 B 失败仍保留 A；同秒任务名不同。
- [ ] 在同一锁保护下捕获有效旧状态、发布和回滚，消除排队旧快照覆盖；版本增加唯一标识。
- [ ] JSON 采用同目录临时文件 + 原子替换；损坏文件有明确诊断/可恢复备份，不能悄悄用空状态覆盖正确索引指针。
- [ ] 重启将无法续跑的 queued/running 任务标记为中断/失败并保留可用活动索引，不自动发起收费重建。
- [ ] 使用临时状态和假仓库验证异常与排队，不触碰本机生产 Milvus 集合。

## 后续候选，首批不扩展

- 历史回答的重新生成按钮没有携带目标消息，实际总重生成最后一问。
- trace 导出未保留完整后端 costs/channels/errors/stopped；未知费用在部分汇总处被按零处理。
- 设置抽屉分块单位应为字而非 tokens，模型选项缺少后端默认 qwen-flash。
- 若首批修复涉及这些区域而需要顺手修改，先向主管报告具体必要性；不得自行扩大为界面重做。

## 总体验收与交付

- [ ] 各组先失败后通过的测试证据，完整后端回归（外部依赖不可用时明确报告，禁止假通过）。
- [ ] `npm run build` 成功；Playwright 实际页面验证真实分时流式与停止，测试可使用 HTTP mock，清楚区分真实页面和真实模型。
- [ ] `git diff --check`，检查无凭据、无 wmk、无用户已有评测产物误入。
- [ ] 交付修改文件、每组测试结果、未解决限制、服务 PID/端口情况；不要自行 commit/push。
- [ ] 由主管复查 diff 和关键行为，再决定是否需要返工；不以实施者自己的完成声明代替验收。
