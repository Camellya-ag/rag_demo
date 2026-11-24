# RAG 效果评测闭环

## 目标

为《西游问典》建立可复用的质量回归：

- 固定问题集（20 题）
- 统一指标（检索命中、引用标注、可答率、错误率）
- 可存档结果 JSON，便于版本对比

## 资产位置

- 评测集：`backend/data/eval/eval_questions.json`
- 评分逻辑：`backend/app/ai/rag/evaluation.py`
- 运行脚本：`backend/scripts/run_eval.py`
- 离线单测：`backend/tests/test_evaluation.py`
- API 契约单测：`backend/tests/test_api_contract.py`

## 指标定义

| 指标 | 含义 |
|------|------|
| `retrieval_hit_rate` | 命中预期章节，或命中文本包含全部 `must_keywords` |
| `citation_rate` | 答案包含 `[n]` 引用标注 |
| `answer_rate` | 非空答案且非“无法据此作答” |
| `error_rate` | 请求异常占比 |

默认阈值（可在脚本中覆盖）：

- `retrieval_hit_rate >= 0.75`
- `citation_rate >= 0.70`
- `answer_rate >= 0.80`
- `error_rate <= 0.05`

## 运行方式

```powershell
cd D:\document\rag\rag_demo
# 冒烟（前 5 题，会产生真实费用）
D:\document\rag\rag_examples\.venv\Scripts\python.exe backend\scripts\run_eval.py --limit 5 --fail-fast

# 全量 20 题
D:\document\rag\rag_examples\.venv\Scripts\python.exe backend\scripts\run_eval.py --fail-fast
```

输出目录：`backend/data/eval/results/eval_YYYYMMDD_HHMMSS.json`

## 建议节奏

1. 每次调整切片/rerank/改写策略后，先跑 `--limit 5` 冒烟。
2. 发版前跑全量 20 题并归档结果 JSON。
3. 对比相邻两次 `summary`（命中率、引用率、平均 cost/latency）。

## 基线（2026-11-24）

- 结果：`backend/data/eval/results/eval_20261124_210335.json`
- 摘要：`retrieval_hit_rate=0.95`，`citation_rate=0.40`，`answer_rate=1.0`
- 调优：`backend/docs/RETRIEVAL_TUNING.md`

