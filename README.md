# DevAgent

> 面向研发效能场景的 AI Agent 后端平台

DevAgent 不只是一个调用大模型 API 的聊天机器人。它围绕真实研发工作流，逐步实现代码仓库分析、CI 失败诊断、日志根因分析、安全工具调用、RAG/Memory、执行轨迹回放、Agent Evaluation 和受控多 Agent 编排。

当前项目处于持续开发阶段，已完成工具与权限执行链、Agent Runtime、任务 API、EventBus、SSE/WebSocket、Trace 回放、CI / Git / 日志工具、证据驱动诊断、代码合入审查，以及 BM25 研发知识检索与上下文压缩基线。项目同时提供 React 可视化控制台，用于查看任务、事件流、Trace、权限请求、诊断报告和 GitHub PR 建议状态。

```text
当前进度：Agent Runtime + Tool/Permission/Event/Trace + Diagnosis/Review + BM25 RAG + ContextManager + Review/RAG Evaluation + React Console
当前阶段：第 8 周 RAG / Memory 基线已完成；第 9 周将在同一评测集上比较向量、混合召回与重排
测试状态：使用 `.venv/bin/pytest -q` 执行全量回归
Python 要求：3.11+
```

---

## 项目亮点

| 能力 | 说明 | 状态 |
| --- | --- | --- |
| 统一工具协议 | 使用 `BaseTool`、Pydantic 参数模型和 `ToolResult` 统一工具调用 | 已完成 |
| 文件读取 | 支持行号、读取范围、workspace 路径边界 | 已完成 |
| 代码搜索 | 基于 ripgrep，支持 glob、超时和输出截断 | 已完成 |
| Shell 执行 | 保留 stdout、stderr、returncode，支持超时和 cwd 限制 | 已完成 |
| ToolRegistry | 支持注册、查询、Schema 导出、参数校验和统一执行 | 已完成 |
| ToolExecutor | 对工具调用返回 `EXECUTED`、`BLOCKED`、`WAITING_PERMISSION`，高风险工具接入权限前置链 | 已完成基础版 |
| 工具 Schema | 从 `BaseTool.args_model` 和 `risk_level` 自动导出统一内部工具协议 | 已完成 |
| 权限领域模型 | `PermissionRequest`、`PermissionDecision`、`PermissionStatus`、`PermissionPolicy` | 已完成基础版 |
| 内存权限管理器 | `InMemoryPermissionManager` 支持创建、查询、审批、列出待审批请求 | 已完成基础版 |
| 内存权限策略匹配 | `InMemoryPermissionPolicyStore` 支持 always allow / deny 的工具名、风险等级和参数指纹匹配 | 已完成基础版 |
| 权限审批 API | 支持查询待审批请求、查询详情、批准 / 拒绝和重复审批冲突处理 | 已完成基础版 |
| 危险命令拦截 | `CommandGuard` 拦截 `rm -rf /`、`sudo`、`mkfs`、`dd`、`curl/wget \| sh` 等明显危险调用 | 已完成基础版 |
| 统一事件协议 | `BaseEvent`、`EventType`、Agent/LLM/Tool/Permission 事件模型、`sequence_id` 和敏感字段脱敏 | 已完成基础版 |
| 内存 EventBus | 支持事件发布订阅、多订阅者投递、失败隔离、历史查询和基于 `sequence_id` 的补发 | 已完成基础版 |
| Mock LLM | 统一 LLM 协议、固定响应序列、请求记录与离线测试 | 已完成 |
| 真实 LLM 适配层 | OpenAI-compatible client、tools schema 转换、tool_calls 解析 | 已完成基础版 |
| Agent Loop | 多轮推理、工具调用、结果观察、最终回答 | 已完成 |
| 防失控保护 | 结构化运行结果、最大步数、工具调用预算、重复调用检测、LLM 异常兜底 | 已完成基础版 |
| Agent 事件轨迹 | 记录 run、LLM、tool、error 事件，支撑后续 CLI、Trace 和 WebSocket | 已完成基础版 |
| 命令行 Demo | 基于事件流展示 LLM 调用、工具调用、最终回答和失败状态 | 已完成基础版 |
| FastAPI 服务骨架 | 提供应用入口、配置模块、`GET /health` 和 OpenAPI 文档 | 已完成基础版 |
| 任务创建 API | `POST /api/v1/agent/tasks`，返回 `task_id` 和 `PENDING` | 已完成基础版 |
| 任务查询/取消 API | 支持查询任务详情、取消任务、404 和 409 状态冲突处理 | 已完成基础版 |
| 任务状态机 | `AgentTask`、`TaskStatus`、合法状态转移和终态保护 | 已完成基础版 |
| 内存任务仓库 | `InMemoryTaskRepository` 支持 create/get/list/update_status，并用副本保护内部状态 | 已完成基础版 |
| 后台任务执行 | `TaskManager` 编排 AgentRuntime，创建任务后后台推进到 DONE / FAILED | 已完成基础版 |
| 任务事件查询 | `InMemoryEventStore` 保存 Agent events，支持按 task_id 查询执行轨迹 | 已完成基础版 |
| 多任务集成测试 | 验证任务状态隔离、事件隔离、取消语义和第三周 API 闭环 | 已完成基础版 |
| Git / CI / 日志工具 | 支持受限 Git diff、压缩 CI 失败证据和结构化日志检索 | 已完成基础版 |
| SSE / WebSocket | 支持任务事件实时推送、断开清理和历史事件衔接 | 已完成基础版 |
| Trace 查询 | 将事件流聚合为任务摘要和可回放步骤 | 已完成基础版 |
| 诊断执行服务 | 证据标准化、LLM 调用、Pydantic 报告校验和失败降级 | 已完成基础版 |
| CI 诊断 API | `POST /api/v1/diagnoses/ci` 返回结构化报告或结构化错误 | 已完成基础版 |
| 代码审查服务与 API | merge-base diff、证据驱动 finding、结构化重试与 `POST /api/v1/reviews/code` | 已完成基础版 |
| GitHub PR 建议模式 | 签名校验、delivery 幂等、installation token、摘要 upsert 与 inline comment | 自动化闭环完成，真实 smoke 待验收 |
| Review Evaluation | 固定 case、风险召回率、可行动准确率、误报率、证据与 diff 定位指标 | 已完成基线 |
| BM25 RAG / Memory | 稳定切片、证据定位、关键词检索和 `knowledge_retrieve` 工具 | 已完成基线 |
| Agent ContextManager | 保留完整历史，为 LLM 请求生成带原子工具块和关键 evidence 的压缩视图 | 已完成基础版 |
| RAG Evaluation | 20 条固定 case、Evidence Hit、Context Reduction、Location 与 p95 指标 | 已完成基线 |
| 可视化控制台 | React 页面展示任务、事件、Trace、权限和诊断结果 | 已完成初版 |
| Agent Skills | 面向业务组合 ToolRegistry 工具能力，预留 MCP 扩展 | 规划中 |
| 权限审批 | 高风险工具审批、策略管理、危险命令防护和审批 API | 已完成基础版 |
| Trace 与事件流 | 统一事件协议、EventBus、SSE/WebSocket、执行回放 | 已完成基础版 |
| 研发诊断 | CI 失败诊断契约与 API、日志根因分析契约、Git diff 分析 | 已完成基础版 |
| 代码合入审查 | base/head 变更审查、结构化建议和 Review Evaluation | 自动化闭环完成 |
| RAG / Memory | 代码、日志、CI、文档和历史案例的 BM25 检索与上下文压缩 | 已完成基线 |
| Evaluation | Review 与 RAG 固定基线、质量/上下文/延迟报告 | 已完成基线 |
| 多 Agent 编排 | 子任务拆分、并发、预算限制、取消传播 | 规划中 |

---

## 工作原理

```mermaid
flowchart LR
    User[用户任务] --> Agent[Agent Runtime]
    Agent --> Context[ContextManager]
    Context --> LLM[LLM Client]
    LLM -->|Tool Call| Registry[ToolRegistry]
    Registry --> Tool[BaseTool]
    Tool --> Adapter[Tool Adapter]
    Adapter --> Builtin[文件 / 搜索 / Shell / Knowledge]
    Builtin --> Result[ToolResult]
    Result --> Agent
    Agent -->|Final Answer| User
```

当前已实现的工具调用链：

```mermaid
sequenceDiagram
    participant C as 调用方
    participant R as ToolRegistry
    participant T as BaseTool
    participant A as Adapter
    participant F as 底层工具

    C->>R: execute(name, arguments)
    R->>T: invoke(raw_arguments)
    T->>T: Pydantic 参数校验
    T->>A: execute(validated_args)
    A->>F: 调用底层功能
    F-->>A: str / RunShellResult
    A-->>T: ToolResult
    T-->>R: ToolResult
    R-->>C: ToolResult
```

---

## 快速开始

### 一键启动前后端

完成 Python 和前端依赖安装后，在项目根目录执行：

```bash
./scripts/start.sh
```

脚本会启动 FastAPI 后端与 Vite 前端，确认服务就绪后默认打开
`http://127.0.0.1:5173`。按 `Ctrl+C` 会同时停止两个服务。

如不希望自动打开浏览器：

```bash
./scripts/start.sh --no-open
```

查看完整参数：

```bash
./scripts/start.sh --help
```

### 1. 创建并激活虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 安装依赖与项目

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
```

`-e` 表示 editable install。修改 `src/devagent` 中的源码后，无需重新安装。

### 3. 运行测试

```bash
.venv/bin/pytest -q
```

预期结果：全部测试通过；具体数量以当前分支输出为准。

代码搜索工具依赖 [ripgrep](https://github.com/BurntSushi/ripgrep)。请确保本机可以运行：

```bash
rg --version
```

---

## 命令行 Demo

安装 editable 包后，可以运行：

```bash
devagent "请分析项目" --workspace .
```

也可以直接使用模块入口：

```bash
.venv/bin/python -m devagent.cli "请分析项目" --workspace .
```

输出会展示 LLM 调用、工具调用和最终回答。失败场景会返回非 0 退出码并输出中文错误。

真实 LLM 使用显式开关启用：

```bash
export DEVAGENT_LLM_API_KEY="你的 key"
export DEVAGENT_LLM_MODEL="你的模型名"
devagent "请分析项目中的 ToolRegistry" --workspace . --provider real
```

`real` 模式默认只向模型暴露低风险工具。高风险工具需要通过 ToolExecutor、CommandGuard 和 PermissionManager 审批链显式接入。

---

## 使用示例

调用 CI 诊断 API：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/diagnoses/ci \
  -H 'Content-Type: application/json' \
  -d '{"commit_id":"abc123","workspace":"examples/sample_repo"}'
```

报告使用 `Evidence`、`Finding` 和 `MissingEvidence` 区分已确认症状、推断和缺失证据。自动化测试使用固定 LLM 响应，不访问真实模型网络。

GitHub Pull Request 建议模式接收签名 webhook，并提供任务状态查询：

```text
POST /api/v1/integrations/github/webhooks
GET  /api/v1/integrations/github/review-tasks/{task_id}
```

真实 GitHub App 只申请 `Metadata: Read`、`Contents: Read` 和
`Pull requests: Read and write`。专用测试仓库的配置、只读探测和 opened / synchronize /
redelivery 验收步骤见 [`docs/evaluation/github_pr_smoke.md`](docs/evaluation/github_pr_smoke.md)。

通过默认 Registry 调用工具：

```python
from devagent.tools.builtin import create_builtin_registry

registry = create_builtin_registry()

result = registry.execute(
    "read_file",
    {
        "file_path": "pyproject.toml",
        "start_line": 1,
        "end_line": 10,
        "workspace": ".",
    },
)

print(result.content)
```

搜索代码：

```python
result = registry.execute(
    "search_code",
    {
        "query": "ToolRegistry",
        "workspace": ".",
        "file_pattern": "*.py",
    },
)
```

执行命令：

```python
result = registry.execute(
    "run_shell",
    {
        "command": ["pytest", "-q"],
        "cwd": ".",
        "workspace": ".",
        "timeout": 30,
    },
)

print(result.metadata["returncode"])
print(result.metadata["stdout"])
```

> `run_shell` 已标记为 `HIGH` 风险工具。PermissionManager 完成后，高风险调用将必须经过审批。

---

## 核心设计

### ToolResult

所有工具最终返回统一结果：

```json
{
  "success": true,
  "content": "1: [build-system]",
  "metadata": {
    "path": "pyproject.toml"
  },
  "error_code": null,
  "error_message": null
}
```

稳定错误码用于程序判断，中文错误信息用于阅读。调用方不需要解析错误文本。

### BaseTool

`BaseTool` 统一负责：

```text
工具名称与描述
Pydantic 参数模型
风险等级
参数校验
未预期异常保护
工具 Schema 导出
```

### ToolRegistry

`ToolRegistry` 只依赖 `BaseTool` 协议，不依赖具体工具实现：

```text
register：注册工具
get：查询工具
list：稳定排序展示工具
schemas：导出工具 Schema
execute：按名称统一执行工具
```

新增工具时，只需实现新的 `BaseTool` 并在应用组装阶段注册。

---

## 项目结构

```text
DevAgent/
├── frontend/                   # React 可视化控制台
├── src/devagent/agent/         # AgentRuntime 与 ContextManager
├── src/devagent/diagnosis/     # 诊断模型与执行服务
├── src/devagent/eval/          # RAG / Review Evaluation 计算
├── src/devagent/event/         # EventBus、事件模型和存储
├── src/devagent/memory/        # Document、Chunk 与 BM25 Retriever
├── src/devagent/trace/         # Trace 聚合与回放
├── src/devagent/tools/
│   ├── models.py              # ToolResult、ErrorCode、RiskLevel
│   ├── base.py                # BaseTool
│   ├── registry.py            # ToolRegistry
│   ├── builtin.py             # 内置工具包装与默认 Registry
│   ├── adapters.py            # 底层结果到 ToolResult 的适配
│   ├── read_file_tools.py     # 文件读取
│   ├── search_code_tools.py   # 代码搜索
│   └── run_shell_tools.py     # 命令执行
├── eval/
│   ├── cases/                 # 固定 RAG / Review Evaluation 数据集
│   └── reports/               # 可审查的 baseline 报告
├── scripts/                   # 基线报告与开发辅助脚本
├── tests/                     # 单元与集成测试
├── docs/evaluation.md         # Evaluation 口径、结果与边界
├── docs/learning/             # 每日学习与验收记录
├── plan.md                    # 项目设计文档
└── learning_plan.md           # 八周开发学习计划
```

---

## 开发路线

```mermaid
flowchart TD
    A[Agent Runtime]
    A --> B[ToolRegistry / Agent Skills]
    B --> C[FastAPI / ToolExecutor]
    C --> D[PermissionManager / EventBus / Trace]
    D --> E[CI / 日志诊断闭环]
    E --> F[代码合入审查 + Review Evaluation]
    F --> G[RAG / Memory + 上下文压缩]
    G --> H[Multi-Agent + 持久化扩展]
    H --> I[最终交付 + Demo 稳定性]

    style A fill:#2d7d46,color:#fff
    style B fill:#d9e8ff,color:#111
    style C fill:#d9e8ff,color:#111
    style D fill:#fff0c2,color:#111
    style E fill:#fff0c2,color:#111
    style F fill:#f4d7e6,color:#111
    style G fill:#f4d7e6,color:#111
    style H fill:#e3dcff,color:#111
    style I fill:#e3dcff,color:#111
```

详细资料：

- [项目设计文档](plan.md)
- [开发学习计划](learning_plan.md)
- [Evaluation 指标与基线](docs/evaluation.md)
- [RAG Evaluation Baseline](eval/reports/rag_baseline.md)
- [学习与验收记录](docs/learning/README.md)

---

## 设计原则

```text
不依赖 LLM 自觉保证安全，所有工具参数都由后端校验。
底层工具保持单一职责，Agent 层通过 ToolResult 统一处理。
高风险能力必须支持权限审批、超时、路径限制和审计。
所有 Agent 结论应尽量引用代码、日志、CI 或 Git diff 证据。
先完成可测试的单 Agent 闭环，再实现多 Agent 编排。
```

---

## License

本项目当前用于个人学习、工程实践与求职作品展示。
