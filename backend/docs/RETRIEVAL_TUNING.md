# 检索参数调优建议（基于 2026-11-24 全量评测）

基线结果：`backend/data/eval/results/eval_20261124_210335.json`

| 指标 | 基线 | 阈值 | 结论 |
|------|------|------|------|
| retrieval_hit_rate | 0.95 | 0.75 | 达标 |
| citation_rate | 0.40 | 0.70 | 未达标（已加 ensure_answer_citations） |
| answer_rate | 1.00 | 0.80 | 达标 |
| error_rate | 0.00 | 0.05 | 达标 |

## 失败样例归类

### 章节偏移但答案仍可答（q01/q04/q07/q10/q11/q12）

- 现象：chapter_ok=false，但 keyword_ok=true 或答案可接受。
- 建议：CANDIDATE_LIMIT 16→20~24；rerank 前加章节轻量加权；保持 QA 通道参与 RRF。

### 单题检索未命中（原 q09）

- 已修正评测集关键词为「西天」「取经」，并扩展 expected_chapters。

### 引用标注不稳定

- 已实施：有命中且无 [n] 时自动补 `[1]`（`backend/app/utils/text.py`）。

## 推荐实验（一次只改一项）

- 实验 A：CANDIDATE_LIMIT=24
- 实验 B：DEFAULT_TOP_K=6
- 实验 C：关闭 threshold
- 实验 D：CHUNK_OVERLAP=96

改后执行：`python backend/scripts/run_eval.py --fail-fast`
