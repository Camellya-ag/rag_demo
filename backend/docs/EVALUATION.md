# RAG 效果评测与离线回归

## 资产与用途

- 原有 20 题：`backend/data/eval/eval_questions.json`（含 `reference_answer`，供 RAGAS），保留历史基线。
- 边界样例：`backend/data/eval/eval_offline_regressions.json`，验证无答案、越界引用、多轮和别名。
- 评分：`backend/app/ai/rag/evaluation.py`；RAGAS：`backend/app/ai/rag/ragas_eval.py`；真实评测：`backend/scripts/run_eval.py`。
- 离线测试使用可控模型与临时状态。完整命令与验收结果见 `docs/superpowers/reviews/2026-11-25-rag-supervisor-review.md`。

边界样例和原 20 题用途不同，不能混在一起宣称全书效果提升。测试替身验证程序行为，不代替真实模型回答质量评测。

## 指标口径

| 字段或指标 | 定义与限制 |
| --- | --- |
| retrieval_scored | 有预期章节或关键词时才具备检索评分条件。 |
| retrieval_ok | 必须存在命中，且命中预期章节，或检索文本包含至少一个预期关键词。生成答案不能补足检索命中。无评分预期时为 null。 |
| retrieval_hit_rate | 只在具备检索评分条件的题中计算比例；章节和关键词是弱代理，不等于证据完整或回答正确。 |
| citation_present | 答案是否包含数字引用标记。 |
| citation_in_range / citation_ok | 有当轮证据及数字引用，且所有编号都在 1..len(hits) 内。[99]、占位符 [n] 不能当有效引用。 |
| citation_rate | 范围有效的引用比例，不是语义证据支持率。 |
| has_answer / answer_rate | 检查答案非空且不含“无法据此作答”；不是事实正确率，也不能单独衡量无答案题。 |
| error_rate | 请求或执行异常比例。 |

无答案样例核对预期拒答行为；缺检索标注的题不能默认算检索成功。事实正确性与忠实度仍需核验具体断言及对应原文。

默认门槛保留为检索命中率 0.75、范围有效引用率 0.70、回答率 0.80、错误率不超过 0.05。门槛不能被解释为答案准确率。

## RAGAS 语义指标（可选）

RAGAS 五指标与召回辨析见 **[docs/blog/06-RAGAS五大指标读分指南.md](../../docs/blog/06-RAGAS五大指标读分指南.md)**；工程速查见 **[RAGAS.md](./RAGAS.md)**。

在规则指标之上，可用 [RAGAS](https://docs.ragas.io/) 评估忠实度与答案质量。依赖**单独安装**（不进入 FastAPI 运行时）：

```powershell
pip install -r backend/requirements-eval.txt
```

| RAGAS 字段 | 含义（简述） |
| --- | --- |
| faithfulness | 回答是否可由检索 contexts 支撑 |
| answer_relevancy | 回答与问题的相关性 |
| context_precision | 检索片段与问题的精确度 |
| context_recall | 检索是否覆盖参考答案所需信息 |
| answer_correctness | 回答与 `reference_answer` 的一致性 |

`citation_ok` 与 RAGAS 互补：前者只校验引用编号范围，后者用语义/LLM 评判质量。**`--fail-fast` 仅针对规则阈值**，RAGAS 暂不设硬门槛。

环境变量：`XIYOU_RAGAS_LLM_MODEL`、`XIYOU_RAGAS_EMBEDDING_MODEL`（默认与评测模型/embedding 一致）、`XIYOU_RAGAS_MAX_WORKERS`（默认 4）。

## 离线验证

评分测试不需要后端或模型：

```powershell
D:\document\rag\rag_examples\.venv\Scripts\python.exe -m unittest backend.tests.test_evaluation -v
```

完整离线回归使用以下命令（模型调用由传输层保护，Milvus 隔离测试需要本机服务）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File backend\scripts\run_offline_tests.ps1
```

保护拦截外部调用边界，不替换被测业务方法。测试结果及范围见监督记录。

浏览器回归用 Playwright 打开真实页面，验证分时文字、阶段变化、自然结束、UI 停止及下一轮发送；构建成功不等于页面测试通过。

## 真实模型评测

以下命令产生真实 API 费用，需要已有可用的 8010 服务与正式索引。本批没有运行收费的全量评测：

```powershell
cd D:\document\rag\rag_demo
# 前 5 题冒烟
D:\document\rag\rag_examples\.venv\Scripts\python.exe backend\scripts\run_eval.py --limit 5 --fail-fast
# 原有 20 题全量
D:\document\rag\rag_examples\.venv\Scripts\python.exe backend\scripts\run_eval.py --fail-fast
# 规则分 + RAGAS（每题约 1 次 chat + 多轮评测 LLM/Embedding 调用）
D:\document\rag\rag_examples\.venv\Scripts\python.exe backend\scripts\run_eval.py --limit 5 --ragas
D:\document\rag\rag_examples\.venv\Scripts\python.exe backend\scripts\run_eval.py --ragas
```

输出：`backend/data/eval/results/eval_YYYYMMDD_HHMMSS.json`。比较前核对数据集哈希、代码状态、模型和活动索引版本，并保存答案、命中及 trace 标识。版本不可得时标记未知及原因，不能用固定说明文字代替真实版本。

启用 `--ragas` 时，同一文件增加 `ragas_summary`、`ragas_model`、`cases[].ragas`；无 `reference_answer` 或请求失败的题记 `ragas_skipped_reason`。

时延区分：latency_ms 是脚本观察的请求耗时；latency_total_ms 是后端全链路耗时；first_token_ms 是后端首个生成 token 的耗时。非流式接口的首字字段不代表浏览器已逐字显示。

## 历史基线限制

2026-11-24 的 `eval_20261124_210335.json` 覆盖 20 题，记录检索率 0.95、引用率 0.40、回答率 1.00。旧评分曾将生成答案并入检索文本，引用只检查标号，因此不能直接与修正后指标比较。

后续 5 题引用率 1.00 只覆盖局部，且曾受自动补标影响，不代表全量质量达标。下次真实评测应按新口径重新建立基线。
