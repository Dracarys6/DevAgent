# DevAgent Console

DevAgent Console 是后端 Agent Runtime 的 Web GUI，首版覆盖：

- 创建、筛选和取消 Agent 任务；
- 通过 SSE 实时刷新执行 Trace；
- 查看 LLM、工具、权限与错误事件；
- 查询并处理高风险工具审批；
- 提交 CI 诊断并展示 finding、recommendation 与 evidence。

## 本地运行

推荐在项目根目录一键启动前后端：

```bash
./scripts/start.sh
```

脚本会在服务就绪后默认打开浏览器。使用 `./scripts/start.sh --no-open`
可以只启动服务；按 `Ctrl+C` 会同时停止前后端。

需要分别调试进程时，可先在项目根目录启动 API：

```bash
.venv/bin/uvicorn devagent.api.app:app --reload
```

再启动前端：

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`。Vite 开发服务器默认将 `/api` 和
`/health` 代理到 `http://127.0.0.1:8000`。

如果前端与 API 不在同一域名，可通过 `VITE_API_BASE_URL` 指定 API 地址。

## 当前边界

- 后端任务、事件和权限请求保存在内存中，API 重启后会清空。
- CI 诊断依赖服务端配置 `DEVAGENT_LLM_API_KEY` 和
  `DEVAGENT_LLM_MODEL`。
- 权限页面只处理已有审批请求，不在前端构造或模拟审批数据。
