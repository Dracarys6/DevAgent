# DevAgent Console

DevAgent Console 是后端 Agent Runtime 的 Web GUI，首版覆盖：

- 创建、筛选和取消 Agent 任务；
- 通过 SSE 实时刷新执行 Trace；
- 查看 LLM、工具、权限与错误事件；
- 查询并处理高风险工具审批；
- 提交 CI 诊断并展示 finding、recommendation 与 evidence；
- 比较本地 Git refs 并保留代码审查历史；
- 展示 GitHub PR 建议模式的 webhook 接入、安全边界和处理流程；
- 通过内嵌 Swagger UI 调试 HTTP API。

## 本地运行

推荐在项目根目录一键启动前后端：

```bash
./scripts/start.sh
```

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

新建 Agent 任务与 HTTP Task API 使用相同默认值：问题为“你好”、provider 为
`real`、workspace 为 `.`、步骤上限为 10、工具调用预算为 20。`model` 和
`base_url` 默认留空，由服务端的 `DEVAGENT_LLM_MODEL` 和
`DEVAGENT_LLM_BASE_URL` 提供；也可以在创建表单中覆盖。Mock 仍作为显式的离线演示选项。

## 当前边界

- 后端任务、事件和权限请求保存在内存中，API 重启后会清空。
- CI 诊断依赖服务端配置 `DEVAGENT_LLM_API_KEY` 和
  `DEVAGENT_LLM_MODEL`。
- GitHub PR 建议由 GitHub webhook 触发，浏览器不保存或发送 webhook
  secret。当前页面提供接入说明和 Webhook URL；后端尚未提供 delivery
  与 GitHub 审查任务查询接口，因此不会展示平台任务历史。
- 权限页面只处理已有审批请求，不在前端构造或模拟审批数据。
