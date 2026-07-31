# DevAgent Console

DevAgent Console 是后端 Agent Runtime 的 Web GUI，首版覆盖：

- 创建、筛选和取消 Agent 任务；
- 通过 SSE 实时刷新执行 Trace；
- 查看 LLM、工具、权限与错误事件；
- 查询并处理高风险工具审批；
- 提交 CI 诊断并展示 finding、recommendation 与 evidence；
- 比较本地 Git refs 并保留代码审查历史；
- 展示 GitHub PR 建议模式的 webhook 接入、安全边界和处理流程，并通过
  `task_id` 查询异步审查状态；
- 在工作区中直接执行确定性 BM25 知识检索，展示 Top-K 证据、文件行号、
  检索耗时与截断状态，并保留最近 10 次本地查询；
- 通过内嵌 Swagger UI 调试 HTTP API。

## 本地运行

推荐在项目根目录一键启动前后端：

```bash
./scripts/start.sh
```

需要分别调试进程时，可先在项目根目录启动 API：

```bash
uv run --locked uvicorn devagent.api.app:app --reload
```

再启动前端：

```bash
cd frontend
npm ci
npm run dev
```

浏览器访问 `http://localhost:5173`。Vite 开发服务器默认将 `/api` 和
`/health` 代理到 `http://127.0.0.1:8000`。

如果前端与 API 不在同一域名，可通过 `VITE_API_BASE_URL` 指定 API 地址。

新建 Agent 任务与 HTTP Task API 使用相同默认值：问题为“你好”、provider 为
`real`、workspace 为 `.`、步骤上限为 10、工具调用预算为 20。`model` 和
`base_url` 默认留空，由服务端的 `DEVAGENT_LLM_MODEL` 和
`DEVAGENT_LLM_BASE_URL` 提供；也可以在创建表单中覆盖。Mock 仍作为显式的离线演示选项。

## 知识检索

“知识检索”页面调用 `POST /api/v1/knowledge/search`，直接消费后端
`RetrievalResult`，不经过 LLM 改写。输入研发问题、服务端工作区路径和
`top_k`（1–50）后，页面会展示候选片段数、返回证据数、检索耗时、截断状态，
以及每条证据的排名、BM25 分数、相对文件路径、行号和原文片段。

后端当前按请求扫描工作区，支持 Python、Markdown、日志、JSON、TOML、YAML 和
纯文本文件；会跳过 Git、虚拟环境、`node_modules`、缓存目录和软链接，并限制
单文件、总字符数与可索引文件数量。页面最近 10 次查询保存在浏览器
`localStorage`，只用于单浏览器恢复，不代表服务端索引或历史持久化。

## 当前边界

- 后端任务、事件和权限请求保存在内存中，API 重启后会清空。
- 知识检索尚未引入持久化索引或向量检索，大型工作区每次请求都会重新发现、加载
  和切片文件；页面显示的 `retrieval_ms` 仅统计 BM25 检索器内部耗时，不包含文件
  扫描、读取和切片时间。
- CI 诊断依赖服务端配置 `DEVAGENT_LLM_API_KEY` 和
  `DEVAGENT_LLM_MODEL`。
- GitHub PR 建议由 GitHub webhook 触发，浏览器不保存或发送 webhook
  secret。当前页面提供接入说明、Webhook URL 和只读任务查询；处于
  `pending` 或 `running` 的任务每 2 秒自动刷新。后端任务状态仍保存在
  进程内存中，服务重启后会清空。
- Day 49 的 Review Evaluation 固定基线没有 HTTP 查询接口，前端不把报告
  文件硬编码为动态指标。真实 GitHub PR smoke 仍需专用 App、仓库与公网
  HTTPS webhook 完成验收。
- 权限页面只处理已有审批请求，不在前端构造或模拟审批数据。
