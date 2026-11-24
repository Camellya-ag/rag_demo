# Agent 约定（西游问典）

## 仓库与素材

- `wmk/` 已加入 `.gitignore`，**不提交、不推送**；远程仓库已移除该目录。
- 本地仍保留 `wmk/docs/西游记.txt` 供切片与运行；新环境需自行放置该书或修改 `backend/app/config.py` 中 `SOURCE_FILE`。

## 后端热更新

修改 `backend/**` 且需要 8010 立刻生效时，先执行：

```powershell
powershell -ExecutionPolicy Bypass -File D:\document\rag\rag_demo\backend\restart.ps1
```

- 仅结束命令行含 `uvicorn backend.app.main:app` 且占用目标端口的进程，避免误杀。
- 不要重复起第二组 uvicorn；已有 dev server 时只做 restart。
- 前台调试：`backend\run.ps1 -Reload`（单实例）。

## 服务探测

- 后端：`http://127.0.0.1:8010/api/health`
- 前端：`http://127.0.0.1:5180`

