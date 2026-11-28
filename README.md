# 西游问典

西游问典是一个围绕《西游记》原著构建的 RAG（检索增强生成）问答项目。它将原文分块并建立检索索引，在回答问题时召回相关片段，生成带引用的答案，同时展示检索、生成过程和费用信息。

项目适合学习和实验中文 RAG 的完整链路：从文档切分、混合检索和重排，到流式回答、引用检查和离线评测。

## 功能

- **知识入库**：按章节读取和切分原文；支持首次正式入库、重建和隔离的开发样本入库。正式入库前先估算费用并确认。
- **混合检索**：使用 Milvus 稠密向量与 BM25 检索，通过 RRF 融合候选结果，并支持重排；原问题和结合上下文改写的问题共同参与召回。
- **问答与引用**：检索原文片段，结合上下文生成答案，展示引用和命中内容；支持 SSE 流式输出及停止生成。
- **过程与费用**：展示检索阶段、运行记录和费用估算；部分费用依赖服务商返回的用量和配置的单价。
- **评测**：提供规则评测、离线回归和可选的 RAGAS 语义指标。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 前端 | Vue 3、Vite、Element Plus |
| 后端 | Python、FastAPI、Uvicorn |
| 检索 | Milvus、稠密向量、BM25、RRF、重排 |
| 模型服务 | 阿里云百炼：Embedding、文本生成和重排 |
| 评测 | Python unittest、规则指标、可选 RAGAS |

## 快速开始

以下命令以 Windows PowerShell 为例，在仓库根目录执行。需要 Python 3.10 或更新版本、Node.js 18 或更新版本、可访问的 Milvus 服务，以及可用的阿里云百炼 API Key。

### 1. 准备原文和 Milvus

仓库不包含《西游记》文本。请自行准备可使用的 UTF-8 文本，放到以下位置，或修改 [backend/app/config.py](backend/app/config.py) 中的 `SOURCE_FILE`：

```text
wmk/docs/西游记.txt
```

原文所在的 `wmk/` 被 Git 忽略，不会随仓库推送。启动支持 BM25 全文检索的 Milvus 服务；默认地址为 `http://127.0.0.1:19530`。已有服务时直接复用，也可通过环境变量 `MILVUS_URI` 指向其他实例。

### 2. 安装并启动后端

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

$env:DASHSCOPE_API_KEY = "替换为你的百炼 API Key"
# 如使用其他 Milvus 地址，可取消下一行注释并修改
# $env:MILVUS_URI = "http://127.0.0.1:19530"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010 --reload
```

保持该终端运行。启动后可访问 [健康检查](http://127.0.0.1:8010/api/health) 和 [API 文档](http://127.0.0.1:8010/docs)。后端也接受 `ALIYUN_API_KEY`，优先使用 `DASHSCOPE_API_KEY`。

配置优先使用进程环境变量。代码还会尝试读取仓库同级的 `rag_examples/.env`；仓库根目录的 `.env` 不会被当前后端配置自动加载。不要将 API Key 写入版本控制。

### 3. 安装并启动前端

另开一个终端，在仓库根目录执行：

```powershell
cd frontweb
npm ci
npm run dev
```

打开 [http://127.0.0.1:5180](http://127.0.0.1:5180)。Vite 默认将 `/api` 请求代理到 `http://127.0.0.1:8010`；需要更改时可参考 [frontweb/.env.example](frontweb/.env.example)。

### 4. 建立索引并开始问答

在页面中选择首次正式入库，查看原文分块、问答对及费用估算，确认后等待索引任务完成，再输入问题。正式入库和重建会调用模型服务并产生费用；估算值取决于用量和单价配置。已有索引时可直接问答。

API 调用方也可使用 `dev_sample` 建立少量开发样本；该模式不会替换正式生产索引。正式 `initial` 和 `rebuild` 需要先调用费用估算接口并确认，详见 [API 契约](backend/docs/API_CONTRACT.md)。

## 配置

| 环境变量 | 用途 | 默认值 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 百炼 API Key；也可使用 `ALIYUN_API_KEY` | 无 |
| `MILVUS_URI` | Milvus 服务地址 | `http://127.0.0.1:19530` |
| `XIYOU_LLM_MODEL` | 默认回答模型 | `qwen-flash` |
| `XIYOU_QA_GEN_MODEL` | 问答对生成模型 | `qwen-flash` |
| `XIYOU_RERANK_MODEL` | 重排模型 | 默认 `qwen3-rerank`，也可回退读取 `RERANK_MODEL` |
| `XIYOU_CHUNK_SIZE` / `XIYOU_CHUNK_OVERLAP` | 分块大小与重叠量 | `512` / `64` |
| `XIYOU_ALLOW_DEV_SAMPLE` | 是否允许开发样本索引 | `true` |
| `VITE_API_PROXY_TARGET` | 前端开发服务器的后端代理目标 | `http://127.0.0.1:8010` |

完整默认值和其他参数见 [后端配置](backend/app/config.py)；费用估算的口径见 [定价说明](backend/docs/PRICING.md)。

## 测试与评测

在仓库根目录、已安装后端依赖的 Python 环境中，可运行无需真实模型的评分测试：

```powershell
python -m unittest backend.tests.test_evaluation -v
```

需要完整离线回归时，可使用脚本并显式指定自己的 Python 路径；部分 Milvus 隔离测试需要本机 Milvus：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File backend\scripts\run_offline_tests.ps1 -Python (Resolve-Path .\.venv\Scripts\python.exe)
```

可选 RAGAS 依赖单独安装。真实模型评测需要运行中的后端和可用索引，并会产生 API 费用：

```powershell
python -m pip install -r backend/requirements-eval.txt
python backend/scripts/run_eval.py --limit 5 --ragas
```

指标定义、限制和更多命令见 [评测说明](backend/docs/EVALUATION.md)。规则中的引用检查只验证编号范围，不能单独证明回答得到原文支持。

## 目录结构

```text
.
├── backend/
│   ├── app/ai/rag/       # 切分、索引、检索、生成和评测
│   ├── docs/             # API、检索调优和评测文档
│   ├── scripts/          # 评测与工具脚本
│   └── tests/            # 后端测试
├── frontweb/
│   ├── src/              # Vue 页面、组件和 API 客户端
│   └── tests/            # 页面测试
└── docs/                 # 项目设计与评审记录
```

## 更多文档

- [后端说明](backend/README.md) · [后端结构](backend/docs/STRUCTURE.md)
- [API 契约](backend/docs/API_CONTRACT.md) · [检索调优](backend/docs/RETRIEVAL_TUNING.md)
- [效果评测](backend/docs/EVALUATION.md) · [RAGAS 速查](backend/docs/RAGAS.md)

## 许可证

仓库目前尚未包含许可证文件；如需复用或分发代码，请先与项目维护者确认授权。
