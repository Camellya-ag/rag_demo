# 百炼单价（估算用）

> 地域：**华北 2（北京）**，档：**≤128K 输入**（RAG 单次请求一般落在此档）。  
> 来源：[模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)（核对日期见 `config.PRICING_UPDATED_AT`）。

| 模型 | 计费项 | 官方价（元/百万 tokens） | 本项目默认（元/千 tokens） | 环境变量覆盖 |
|------|--------|-------------------------|---------------------------|-------------|
| `text-embedding-v4` | 输入 | 0.5 | 0.0005 | `PRICE_EMBED_PER_1K` |
| `qwen3-rerank` | 输入 | 0.5 | 0.0005 | `PRICE_RERANK_PER_1K` |
| `qwen-flash` | 输入 / 输出 | 0.15 / 1.5 | 0.00015 / 0.0015 | `PRICE_LLM_QWEN_FLASH_*` 或 `PRICE_LLM_IN/OUT_PER_1K` |
| 问答生成（同 `qwen-flash`） | 输入 / 输出 | 同上 | 同上 | `PRICE_QA_GEN_QWEN_FLASH_*` |

说明：

- 控制台活动价、Batch 半价、上下文缓存等**不在此默认价**内；以账单为准。
- `usage_known=false` 时页面/API 不展示伪造总价，仅展示参考单价或「未知」。