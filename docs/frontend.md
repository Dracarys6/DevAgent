# DevAgent Console

## 目标与上下文

DevAgent Console 是项目的可视化操作入口，与现有 CLI 形成双入口。CLI
继续服务于脚本化和快速验证；Web GUI 负责呈现 Agent 的持续执行过程、权限边界和
证据驱动诊断结果。

该界面对应 `plan.md` 的“前端 / TUI 设计”，消费既有 Task API、SSE、Trace、
Permission API 和 Diagnosis API，不把 UI 逻辑耦合进 `AgentRuntime`。

## 实现范围

- React、TypeScript 和 Vite 独立前端工程；
- Agent 任务创建、查询、筛选、取消和 Trace 时间线；
- SSE 事件触发后的任务与 Trace 增量刷新；
- 待审批请求查询，以及单次允许或拒绝；
- CI 诊断表单和结构化证据报告；
- FastAPI 本地开发 CORS 配置；
- 桌面端优先，并提供窄屏响应式布局。

## 视觉系统

界面采用克制但不沉闷的冷色开发者控制台风格：以深蓝灰为底，使用靛蓝作为主要操作色，
少量紫色丰富层次。页面避免强光晕，通过轻渐变、细边框、清晰灰阶和留白建立层级。

任务详情优先展示 Agent 最终结果；完整 Trace 默认收起为可展开的工程细节。运行中的任务
因尚无最终结果会自动展开 Trace，兼顾实时观察和完成后快速阅读两种场景。

## 关键设计

### API 是单一事实来源

界面只展示后端返回的任务、事件、审批和诊断数据。当前内存存储会在进程重启后清空，
页面通过侧栏提示这一运行边界。

### SSE 用于执行状态更新

Agent 执行是服务端单向事件流，首版使用 `EventSource` 订阅现有 SSE 接口。
收到事件后重新获取任务与 Trace，使页面复用后端的排序、脱敏和 Trace 汇总契约。
普通 HTTP 继续承担任务创建、取消和权限审批。

### 敏感配置留在服务端

真实 LLM API Key 不进入浏览器。前端只能选择 provider 和可选 model，密钥仍由
FastAPI 进程的环境变量提供。

## 验证

项目根目录提供前后端一键启动脚本：

```bash
./scripts/start.sh
```

脚本默认使用后端端口 `8000` 和前端端口 `5173`，启动前检查虚拟环境、
Node.js、npm、前端依赖及端口占用。服务就绪后默认打开浏览器；使用
`./scripts/start.sh --no-open` 可关闭该行为。按 `Ctrl+C` 或任一服务异常退出时，
脚本会统一清理两个子进程。需要并行运行其他开发实例时，可通过
`DEVAGENT_BACKEND_PORT` 和 `DEVAGENT_FRONTEND_PORT` 覆盖默认端口。

```bash
cd frontend
npm run lint
npm run build
```

```bash
.venv/bin/pytest tests/api/test_health.py -q
```

## 可衡量结果

- 将任务创建、执行观察、取消和结果查看集中到一个页面，用户无需手动调用四类 API；
- 将 Trace 中的 LLM、工具、权限和错误事件按序列号统一展示；
- CI 报告中的 finding、recommendation 和 evidence 保持引用关系可见；
- 前端生产构建可由 TypeScript 和 ESLint 静态检查重复验证。
