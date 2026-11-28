# RAGAS 评测（仓库速查）

**博客向正文（五指标、召回辨析、耗时与心法）** → [docs/blog/06-RAGAS五大指标读分指南.md](../../docs/blog/06-RAGAS五大指标读分指南.md)

**工程集成、子进程、环境变量、faithfulness 踩坑** → [docs/blog/04-RAGAS语义评测与踩坑.md](../../docs/blog/04-RAGAS语义评测与踩坑.md)

**命令、门槛、结果字段** → [EVALUATION.md](./EVALUATION.md)

| 代码 | 路径 |
| --- | --- |
| 拼表与 merge | `backend/app/ai/rag/ragas_eval.py` |
| 子进程 evaluate | `backend/scripts/ragas_eval_worker.py` |
| 评测入口 | `backend/scripts/run_eval.py` |

官方框架：[https://docs.ragas.io/](https://docs.ragas.io/)