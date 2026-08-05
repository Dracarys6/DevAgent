# DevAgent 秋招开发学习计划

目标：用 8 到 13 周，每天 3 到 5 小时，围绕 DevAgent 项目系统提升 Python、后端开发、AI Agent 开发、工程设计和面试表达能力，争取秋招投递中大厂 AI 应用开发 / 后端开发岗位时，有一个能讲深、能演示、能扩展的项目。

适用岗位：

```text
AI 应用开发工程师
大模型应用开发工程师
Agent 开发工程师
后端开发工程师
AI Platform / AI Infra 初级岗位
研发效能平台后端工程师
DevOps 平台后端工程师
```

核心策略：

```text
不要只学教程，要每天产出可运行代码。
不要只堆功能，要能解释设计取舍。
不要只做 Demo，要写测试、写文档、写面试话术。
不要一开始追求大而全，先跑通命令行 Agent，再扩展后端和可观测性。
Mock 只负责可重复测试；每条核心 Agent 业务链必须完成真实模型和真实工具的端到端验收。
```

---

## 0. 当前进度与计划维护规则

当前进度：

```text
已完成并验收 Day 1 到 Day 56
Day 7 内容已在 Day 6 与 Day 8 开发中覆盖，并已按完成状态维护
已完成正式模块：
- 文件、代码搜索、Shell、Git diff、CI 结果和结构化日志工具
- BaseTool、ToolRegistry、ToolResult、参数 Schema 与 ToolExecutor
- PermissionManager、PolicyStore、CommandGuard 与 Permission API
- AgentRuntime、LLMClient、TaskManager 与任务状态机
- EventBus、EventStore、SSE / WebSocket、Trace 查询与回放
- CI / 日志可复现 fixture、证据模型、DiagnosisService 与结构化诊断 API
- CodeReviewService、GitHub PR Adapter 与 Review Evaluation 基线
- Document / Chunk / EvidenceSnippet、BM25 Retriever 与 knowledge_retrieve 工具
- 20 条固定 RAG eval cases、RAG baseline 报告与 Agent ContextManager
```

计划不是固定不变的课程表。后续每次验收时，根据实际完成情况更新：

```text
1. 已提前掌握的内容，从后续计划中删除或升级难度
2. 验收暴露出的薄弱点，加入下一天或周复盘
3. 项目功能完成后，必须补原理、测试和面试表达
4. 如果某天任务超过 5 小时，可以拆成两天，不追求机械赶进度
5. 如果提前完成，可以做扩展任务，但不能跳过测试和复盘
6. “代码已实现”与“真实链路已验收”分开记录；缺少真实运行报告时不能标记业务闭环完成
```

完成状态标记：

```text
[x] 已完成并验收
[~] 已实现，仍需完善
[ ] 尚未开始
```

---

## 1. 阶段总目标

前 9 周结束时，你应该拥有一个能演示、能评测、能讲清楚架构取舍的核心版本，但这不是项目最终交付：

```text
1. 一个可运行的 DevAgent 后端项目
2. 一个命令行 Agent Demo
3. 一个 FastAPI 后端服务
4. Agent Runtime、ToolRegistry、PermissionManager、EventBus 四个核心模块
5. read_file、search_code、run_shell、git_diff、get_ci_result、search_log 工具
6. 代码合入审查、CI 失败诊断和日志根因分析 Demo
7. 最小 Evaluation、Trace 回放、上下文压缩和研发知识 Memory
8. README、架构说明、安全设计、评测报告、面试问答文档
9. 一套能讲 3 分钟、10 分钟、30 分钟的项目表达
```

第 9 到第 13 周用于把核心版本补成完整工程作品。只有 RAG、Multi-Agent、Trace / Evaluation、持久化和安全增强等关键扩展完成后，项目才算真正完成：

```text
1. RAG 增强：embedding、hybrid search、rerank、检索质量对比
2. 持久化完善：SQLite / PostgreSQL、事件落库、工具调用记录、权限策略持久化
3. Multi-Agent 完整化：父子 Trace、预算、取消传播、部分失败降级
4. 安全增强：更完整的 CommandGuard、敏感字段脱敏、可选 Docker Sandbox
5. 交付材料：架构图、安全设计、Evaluation 报告、Demo 脚本、简历表达
```

求职导向的核心证明点：

```text
1. 我不是只做 ChatBot，而是实现可控、可观测、可评估的 Agent Runtime。
2. 我不是只写几个工具，而是设计 Agent Skills / Tool Calling 扩展协议。
3. 我不是只做 Demo，而是用代码合入审查、CI 诊断和日志根因分析证明 Agent 能解决真实研发问题。
4. 我不是只追求能跑，而是补齐权限鉴权、Trace、Evaluation、RAG/Memory 和 Multi-Agent。
```

---

## 2. 每天学习时间分配

每天 3 到 5 小时，围绕当天项目任务完成学习、实现、测试和项目复盘。

```text
20 分钟：复习昨天内容和运行已有测试
50 到 70 分钟：学习当天核心原理
100 到 160 分钟：完成项目开发任务
30 到 50 分钟：写测试、重构、补 daily 文档
20 到 40 分钟：整理与当天项目内容相关的面试表达
```

每天开发任务必须形成闭环：

```text
学习原理
自己实现
运行验证
自动化测试
验收完善
daily 文档
至少一个面试回答
```

每天结束前做 5 分钟自查：

```text
今天我写了什么代码？
它解决了什么问题？
有没有测试？
如果面试官问我为什么这样设计，我能回答吗？
明天最小任务是什么？
```

每周复盘不再占用单独学习日。每周所有 Day 都用于开发任务，复盘、完整测试、文档更新和项目问答统一放在“每周额外收尾”中，可以分散到当周最后两次学习结束后完成。

---

## 3. 8 到 13 周学习主线

```text
第 1 周：Python 工程基础 + 命令行工具
第 2 周：统一工具协议 + Agent Loop + Tool Calling
第 3 周：FastAPI 后端 + Task API + 任务状态
第 4 周：PermissionManager + 安全控制 + ToolExecutor
第 5 周：EventBus + SSE/WebSocket + Trace
第 6 周：研发效能业务 Demo + CI / 日志诊断
第 7 周：代码合入审查 + 结构化修改建议 + Review Evaluation
第 8 周：RAG / Memory 基线 + Evaluation + 上下文压缩
第 9 周：RAG 增强 + 检索质量优化
第 10 周：持久化深化 + Trace / Evaluation 数据闭环
第 11 周：Multi-Agent 基础闭环 + 父子 Trace
第 12 周：Multi-Agent 完整化 + 安全增强
第 13 周：最终交付 + 简历面试材料 + Demo 稳定性打磨
```

最低成功标准：

```text
完成第 1 到第 5 周，就已经有一个能演示、能评测的 AI Agent 后端项目。
第 6 周到第 9 周用于把项目从“能跑”提升到“具备核心业务和可量化的 RAG 质量优化”。
第 10 周到第 13 周用于完善持久化、Multi-Agent、安全和指标报告；第 13 周完成后才进入最终交付状态。
```

六条长期主线：

```text
1. Agent Runtime：多轮推理、工具调用、防失控、结构化结果
2. Agent Skills / ToolRegistry：工具协议、Schema、扩展成本、MCP 预留
3. Permission & Safety：高风险工具审批、命令拦截、workspace 边界
4. EventBus & Trace：事件流、执行轨迹、任务回放、可观测性
5. RAG / Memory：代码、日志、CI、文档检索，上下文压缩
6. Multi-Agent：任务拆解、并发执行、父子 Trace、结果汇总
```

### 3.1 每日验收等级

每天结束时按三个等级判断，不要只判断“写没写完”。

```text
基础通过：
功能能够运行，理解主要 API。

工程通过：
有边界处理、异常设计、类型标注和自动化测试。

面试通过：
能解释设计取舍、风险、替代方案和后续演进。
```

### 3.2 项目范围控制

前 9 周核心主线只实现能够组成完整 DevAgent 闭环的能力。以下内容不默认加入主线：

```text
MCP
向量数据库和复杂 RAG
Redis
Celery 等分布式任务队列
复杂 React 前端
完整 Docker Sandbox
多模型供应商同时接入
```

只有满足下面条件后，才选择其中一个作为扩展：

```text
命令行 Agent 已经稳定运行
核心模块有测试
CI 诊断 Demo 已经完成
README 和架构说明已经能讲清楚
扩展能力确实解决当前项目中的真实问题
```

### 3.3 文件与接口命名约定

```text
正式源码：src/devagent/<module>/
单元测试：tests/<module>/test_<name>.py
跨模块集成测试：tests/integration/test_<workflow>.py
示例数据：examples/<scenario>/
评测数据：eval/cases/
学习记录：docs/learning/weekN/dayXX.md

HTTP API 前缀：/api/v1
Agent 任务接口：/api/v1/agent/tasks
权限接口：/api/v1/permissions
Python 包运行入口：devagent 或 .venv/bin/python -m devagent.<module>
```

---

## 4. 第 1 周：Python 工程基础 + 命令行工具

目标：补齐 Python 基础，写出 DevAgent 最早需要的三个底层工具：读文件、搜代码、执行命令。

本周重点原理：

```text
Python 基本语法
函数与模块
类与 dataclass
类型标注
异常处理
pathlib 路径安全
subprocess 命令执行
pytest 单元测试
```

详细原理、API 用法、练习步骤和面试问答记录在对应的 `docs/learning/weekN/dayXX.md`；总计划只保留里程碑、产出和验收边界。

每日任务与验收：

```text
Day 1：环境与 Python 工程基础 [x]
产出：pyproject.toml、虚拟环境、pytest smoke test
验收：项目可 editable install，.venv 中可稳定运行 pytest

Day 2：文件读取工具 read_file [x]
产出：受行数限制、带行号的文件读取函数及测试
验收：正常读取与文件不存在、参数非法均有确定行为

Day 3：workspace 路径安全 [x]
产出：基于 Path.resolve() 的工作区边界校验及越界测试
验收：相对路径、绝对路径和符号链接均不能逃逸 workspace

Day 4：代码搜索工具 search_code [x]
产出：基于 rg 的代码搜索、结果截断和失败处理
验收：支持查询、文件过滤、空结果和非法 workspace

Day 5：Shell 执行工具 run_shell [x]
产出：受 cwd、timeout 和输出长度限制的命令执行工具
验收：保留 stdout、stderr、returncode，并覆盖超时与越界场景

Day 6：ToolResult 与错误模型 [x]
产出：统一 ToolResult、稳定 ErrorCode 和底层结果适配
验收：调用方不解析错误文本即可判断成功、失败及失败类型

Day 7：工具适配层与统一调用入口 [x]
产出：read_file、search_code、run_shell 的 ToolResult adapters
验收：底层异常被转换为结构化错误，关键 metadata 不丢失
```

#### 第 1 周额外收尾

```text
运行完整测试；同步 daily 文档；确认工具安全边界、统一返回协议和模块依赖关系可解释
```

---

## 5. 第 2 周：统一工具协议 + Agent Loop + Tool Calling

目标：写出命令行版最小 Agent。先用 MockLLMClient，再接真实 LLM API。

本周重点原理：

```text
LLM messages
system / user / assistant / tool message
tool calling
Agent Loop
ReAct
max_steps
工具结果注入上下文
循环检测
```

详细消息协议、Tool Calling 原理和 Agent Loop 推导保留在对应 daily 文档。

每日任务与验收：

```text
Day 8：BaseTool 与 ToolRegistry [x]
产出：统一工具抽象、Pydantic 参数校验、注册与 schema 能力
验收：新增工具不修改 Registry 核心逻辑，执行结果统一为 ToolResult

Day 9：MockLLMClient [x]
产出：ToolCall、LLMResponse 和可编排固定响应的 MockLLMClient
验收：不访问网络即可稳定复现多轮工具调用和最终回答

Day 10：最小 AgentRuntime [x]
产出：messages 构造、LLM 调用、工具执行、结果回填和停止返回的最小循环
验收：可断言工具调用顺序、tool message 和最终答案

Day 11：Agent 防失控与结构化运行结果 [x]
产出：max_steps、重复调用检测、错误回填和 AgentRunResult
验收：未知工具、参数错误、重复调用和步数耗尽均能确定结束

Day 12：AgentEvent 与执行轨迹 [x]
产出：Agent 生命周期、LLM 和工具调用的结构化事件
验收：成功与失败路径事件顺序稳定，可支撑后续 Trace 和流式展示

Day 13：命令行 Agent Demo [x]
产出：支持 workspace 和运行预算参数的 CLI 入口
验收：可展示工具调用摘要、最终答案和友好错误，不泄漏原始堆栈

Day 14：真实 LLM API 最小接入 [x]
产出：OpenAI-compatible LLMClient、tools schema 转换和 CLI provider 选择
验收：Mock 默认离线稳定；真实模式配置缺失时明确失败，配置完整时可完成工具调用
```

#### 第 2 周额外收尾

```text
运行完整测试与 CLI Demo；同步 daily 文档；确认 Agent Loop、Tool Calling、防失控机制和 LLM provider 边界可解释
```

---

## 6. 第 3 周：FastAPI 后端 + 任务状态

目标：把命令行 Agent 包成后端服务，支持创建任务、查询状态、查询事件。

本周重点原理：

```text
HTTP
REST API
FastAPI 路由
Pydantic 请求响应模型
async / await
后台任务
任务状态机
```

每日任务与验收：

```text
Day 15：创建 FastAPI app、配置模块和 GET /health [x]
产出：src/devagent/api/app.py、src/devagent/config.py、tests/api/test_health.py
验收：.venv/bin/uvicorn 启动成功，pytest 可使用 TestClient 调接口

Day 16：设计创建任务 API [x]
产出：src/devagent/api/schemas.py、src/devagent/api/routes/tasks.py
接口：POST /api/v1/agent/tasks
验收：非法 max_steps 被 Pydantic 拒绝，响应包含 task_id 和 PENDING

Day 17：实现 AgentTask 与显式状态转移 [x]
产出：src/devagent/task/models.py、src/devagent/task/repository.py
类型：TaskStatus、AgentTask、InMemoryTaskRepository
验收：非法状态转移被拒绝，状态机与 repository copy 保护有单元测试

Day 18：实现任务查询和取消接口 [x]
产出：GET /api/v1/agent/tasks/{task_id}、POST /api/v1/agent/tasks/{task_id}/cancel
验收：任务不存在返回 404，非法重复取消返回 409，取消后的状态一致

Day 19：学习 asyncio，并异步执行 Agent [x]
产出：src/devagent/task/manager.py 的 TaskManager.create/run/cancel
验收：创建接口快速返回；任务在后台变为 RUNNING / DONE / FAILED；TaskManager 支持 runtime_factory 注入测试
说明：理解 BackgroundTasks 适合响应后小任务，不等同于可靠任务队列

Day 20：实现内存事件记录和事件查询接口 [x]
产出：src/devagent/event/store.py、tests/event/test_store.py
接口：GET /api/v1/agent/tasks/{task_id}/events
验收：能看到任务开始、结束和错误事件；EventStore 读写都用 deepcopy 保护内部状态

Day 21：并发任务与取消集成测试 [x]
产出：tests/integration/test_task_api.py、tests/integration/test_task_cancellation.py
验收：同时创建多个任务不会互相覆盖；事件按 task_id 隔离；已取消任务不会继续执行；终态任务取消返回 409
```

### 第 3 周额外收尾

```text
运行 API 集成测试
在 Swagger 完整走一遍创建、查询、取消、事件查询
画 TaskManager 与 AgentRuntime 调用图
整理异步任务、状态机和取消机制项目问答
更新本周 daily 文档
```

任务状态设计：

```text
PENDING：任务创建
RUNNING：Agent 执行中
WAITING_PERMISSION：等待审批
DONE：完成
FAILED：失败
CANCELLED：取消
```

原理问题：

```text
HTTP 请求为什么不能一直阻塞等 Agent 完成？
后台任务和同步接口有什么区别？
任务状态机为什么比一个 bool finished 更好？
为什么 API 响应要用 Pydantic 模型？
```

面试问题：

```text
你的后端如何管理长时间运行的 Agent 任务？
用户断开连接后任务怎么办？
如何查询任务当前执行到哪一步？
FastAPI 的 async 适合什么场景？
asyncio.create_task 有什么生命周期风险？
为什么生产环境长任务最终可能需要独立 Worker 和消息队列？
```

验收标准：

```text
.venv/bin/uvicorn devagent.api.app:app --reload 能启动
Swagger 可以创建 Agent 任务
任务状态能从 PENDING -> RUNNING -> DONE
events 接口能返回执行记录
```

---

## 7. 第 4 周：PermissionManager + 安全控制 + 异步任务

目标：把工具调用做成真实后端系统，而不是简单函数调用。

本周重点原理：

```text
工具抽象
参数校验
风险等级
权限审批
安全策略
命令黑名单
路径白名单
Prompt Injection 防护
```

每日任务与验收：

```text
Day 22：复查 ToolRegistry 与参数 Schema [x]
产出：src/devagent/tools/schema.py、tests/tools/test_tool_schema.py
接口：ToolRegistry.schemas() -> list[dict]
验收：工具协议只维护一份，不重复定义参数结构；内置工具 risk_level 输出稳定

Day 23：定义风险模型和 PermissionRequest [x]
产出：src/devagent/permission/models.py
类型：RiskLevel、PermissionDecision、PermissionRequest、PermissionPolicy
验收：风险等级和审批状态可以 JSON 序列化；RiskLevel 复用工具层定义；重复审批被拒绝

Day 24：实现内存 PermissionManager [x]
产出：src/devagent/permission/manager.py
接口：request_permission(...)、resolve(request_id, decision)、check_request_status(request_id)
验收：权限请求可创建、查询、审批和列出；重复审批被拒绝；返回副本保护内部状态

Day 25：实现 always_allow / always_deny 匹配规则 [x]
产出：src/devagent/permission/policy_store.py、tests/permission/test_policy_store.py
验收：说明规则粒度，避免“允许一次 pytest”扩大成“允许所有 Shell”

Day 26：设计 CommandGuard [x]
产出：src/devagent/security/command_guard.py、tests/security/test_command_guard.py
接口：CommandGuard.validate(command, workspace) -> GuardResult
验收：拦截明显危险调用；GuardResult 输出 decision、reason、matched_rule；文档明确黑名单不是完整安全方案

Day 27：把 run_shell 接入审批链 [x]
产出：src/devagent/tools/executor.py 的 ToolExecutor.execute(tool_call, context)
验收：ToolExecutor 对 run_shell 返回 EXECUTED / BLOCKED / WAITING_PERMISSION；Guard BLOCK 和等待审批不执行命令；Day28 再接任务状态与恢复 API

Day 28：权限审批 API 与等待恢复 [x]
产出：src/devagent/api/routes/permissions.py
接口：GET /api/v1/permissions/{request_id}、POST /api/v1/permissions/{request_id}/resolve
验收：Permission API 可查询待审批请求并批准 / 拒绝；重复审批返回 409；完整 Agent 恢复执行在 Runtime 接入 ToolExecutor 后完成
```

### 第 4 周额外收尾

```text
运行权限绕过和危险命令测试
检查高风险工具是否全部经过 ToolExecutor
更新安全设计文档和权限审批时序图
整理审批、策略匹配、CommandGuard、Sandbox 项目问答
更新本周 daily 文档
```

安全规则：

```text
read_file：只能读 workspace 内文件
search_code：只能搜 workspace 内文件
run_shell：必须审批
run_shell：必须 timeout
run_shell：必须限制 cwd
run_shell：必须限制输出长度
run_shell：禁止 sudo、rm -rf /、curl | sh、wget | sh
```

原理问题：

```text
为什么 LLM 不能直接决定执行高风险操作？
allow_once 和 always_allow 的区别是什么？
为什么权限策略要持久化？
为什么工具返回内容不能当成系统指令？
Prompt Injection 在日志分析场景里怎么出现？
```

面试问题：

```text
Agent 能执行 Shell 命令，如何保证安全？
你如何防止 Prompt Injection？
你如何设计工具风险等级？
权限审批流程是什么？
```

验收标准：

```text
低风险工具可以直接执行
run_shell 会进入 WAITING_PERMISSION
用户审批后才会执行
危险命令会被系统拒绝
权限流程有测试覆盖
```

---

## 8. 第 5 周：EventBus + WebSocket + Trace

目标：让 Agent 执行过程可观察、可回放、可展示。

本周重点原理：

```text
事件驱动
发布订阅
WebSocket
SSE
sequence_id
断线重连
Trace
可观测性
```

每日任务与验收：

```text
Day 29：定义事件协议 [x]
产出：src/devagent/event/models.py
类型：BaseEvent、EventType、AgentStarted、ToolCallStarted、PermissionRequested 等
验收：事件可 JSON 序列化；同一任务 sequence_id 单调递增；敏感字段可脱敏

Day 30：实现内存 EventBus [x]
产出：src/devagent/event/bus.py、tests/event/test_event_bus.py
接口：publish(event)、subscribe(task_id)、unsubscribe(subscription_id)
验收：一个事件可被多个订阅者收到；失败订阅者不拖垮发布流程；支持 sequence_id 历史补发

Day 31：AgentRuntime 接入生命周期事件 [x]
修改：src/devagent/agent/runtime.py
发布：AgentStarted、LLMCallStarted、LLMCallFinished、AgentFinished、AgentError
验收：成功和失败任务都有完整生命周期事件；保留旧 AgentEvent 兼容；EventBus 订阅失败不影响 Agent 主流程

Day 32：工具与权限流程接入事件 [x]
修改：src/devagent/tools/executor.py、src/devagent/permission/manager.py
发布：ToolCallStarted / Finished / Failed、PermissionRequested / Resolved
验收：事件 payload 不泄漏 API Key 等敏感信息

Day 33：实现 SSE，再理解 WebSocket [x]
产出：src/devagent/api/routes/stream.py
接口：GET /api/v1/agent/tasks/{task_id}/stream
验收：浏览器或 curl 能持续接收服务端事件
说明：本项目主要是服务端单向推送，先做 SSE 更简单；审批需要双向交互时再用普通 HTTP 或 WebSocket

Day 34：实现 WebSocket 和断线重连协议 [x]
产出：src/devagent/api/websocket.py
接口：WS /api/v1/sessions/{session_id}/stream?last_seen_sequence_id=N
验收：断线重连后能补发缺失事件，不重复展示已确认事件

Day 35：Trace 查询与回放接口 [x]
产出：src/devagent/trace/service.py、src/devagent/api/routes/traces.py
接口：GET /api/v1/agent/tasks/{task_id}/trace
验收：按 sequence_id 返回完整执行轨迹，并包含工具耗时与最终状态
```

### 第 5 周额外收尾

```text
运行事件顺序、断线重连和多订阅者测试
画事件发布、实时推送、历史回放数据流
整理 SSE 与 WebSocket 选择依据
检查事件 payload 的敏感信息脱敏
更新本周 daily 文档
```

事件类型：

```text
AgentStarted
AgentFinished
AgentError
LLMCallStarted
LLMCallFinished
ToolCallStarted
ToolCallFinished
ToolCallFailed
PermissionRequested
PermissionResolved
```

原理问题：

```text
为什么 Agent 执行过程适合事件化？
WebSocket 和普通 HTTP 有什么区别？
本项目为什么可以先实现 SSE？
sequence_id 有什么作用？
断线重连后如何补发事件？
Trace 和普通日志有什么区别？
```

面试问题：

```text
为什么要设计 EventBus？
前端如何实时展示 Agent 执行过程？
如何回放一次历史任务？
如何定位 Agent 为什么得出某个结论？
```

验收标准：

```text
每个任务都有完整事件流
WebSocket 能实时看到工具调用
events 接口能回放历史事件
每个事件有 task_id、event_type、sequence_id、timestamp、payload
```

---

## 9. 第 6 周：研发效能业务 Demo

目标：做出真正贴近 AI 开发 / 后端岗位的业务场景：CI 失败诊断、日志根因分析、代码仓库问答。

本周重点原理：

```text
CI 流程
测试失败日志
错误栈
Git diff
日志检索
根因分析
证据链输出
```

每日任务与验收：

```text
Day 36：设计可重复的 sample_repo 和失败场景 [x]
产出：examples/sample_repo/、examples/sample_repo/tests/
验收：不调用 Agent 时，人可以手动复现失败并说明根因

Day 37：实现 git_diff 工具 [x]
产出：src/devagent/tools/git_tools.py、tests/tools/test_git_tools.py
工具接口：git_diff(commit_id, workspace) -> ToolResult
验收：合法 commit 返回 diff；非法 commit 返回结构化错误

Day 38：准备 mock CI 数据并实现 get_ci_result [x]
产出：examples/sample_ci/abc123.json、src/devagent/tools/ci_tools.py
工具接口：get_ci_result(commit_id) -> ToolResult
验收：工具能返回失败 job、test case、核心日志，不把整份日志全部塞入上下文

Day 39：实现 search_log [x]
产出：examples/sample_logs/、src/devagent/tools/log_tools.py
工具接口：search_log(task_id, level=None, keyword=None) -> ToolResult
验收：结果按时间排序，支持截断，明确首个异常点

Day 40：设计证据驱动的 CI 诊断流程 [x]
产出：src/devagent/prompts/ci_diagnosis.py、src/devagent/diagnosis/models.py
类型：DiagnosisReport、Evidence、Recommendation
边界：只完成输出契约、Prompt 和固定 JSON 校验，不调用 LLM API 或 HTTP API
验收：每个结论引用具体工具证据；缺少证据时明确说明；非法 evidence 引用无法通过 Pydantic 校验

Day 41：设计日志根因分析流程 [x]
产出：src/devagent/prompts/log_diagnosis.py、src/devagent/eval/live_log_diagnosis.py、tests/prompts/test_log_diagnosis.py、tests/eval/test_live_log_diagnosis.py
边界：复用 DiagnosisReportDraft 契约，模型生成分析字段，Service 绑定身份和原始日志 Evidence
验收：区分根因、后续连锁错误和推测；首个异常只能作为根因候选；日志单独支持的 root cause 不得标为 confirmed

Day 42：接通诊断执行服务与 API 闭环 [x]
产出：src/devagent/diagnosis/service.py、src/devagent/api/routes/diagnoses.py、tests/integration/test_ci_diagnosis.py、tests/api/test_diagnoses.py、tests/fixtures/diagnosis_cases/
执行链：工具输出标准化为 Evidence -> 构造 DiagnosisInput -> 调用注入的 LLMClient.chat() -> 校验 DiagnosisReportDraft -> 服务端绑定 report_id、target 和原始 evidence -> DiagnosisReport.model_validate() -> API 返回结构化报告
接口：POST /api/v1/diagnoses/ci、POST /api/v1/diagnoses/log
测试策略：自动化测试使用 MockLLMClient 或固定 LLMClient，不访问真实网络；另用显式 live runner 调用真实 provider
验收：自动化验证非法 JSON、悬空 evidence_id 和工具失败降级；真实 provider 分别通过固定 CI 和日志 case，返回通过 Pydantic 校验且引用真实 Evidence 的 DiagnosisReport，并保存脱敏结果、模型、延迟和失败信息
实测：CI 修复后连续 3 次通过，平均延迟 17.18 秒、p95 20.97 秒；日志诊断一次调用通过，首异常/连锁错误识别与证据引用均为 100%，延迟 34.19 秒
```

### 第 6 周额外收尾

```text
录制 CI 诊断和日志诊断演示
检查所有诊断结论是否引用证据
通过诊断 API 完成一次确定性本地回归
使用本地 .env 配置的真实 provider 完成 CI 诊断 live acceptance，并保存脱敏报告
整理根因、症状、推测三者区别
更新 README 的业务 Demo 部分
更新本周 daily 文档
```

CI 诊断输出格式：

```text
结论
关键证据
失败 job / test case
涉及文件
可能原因
修复建议
后续验证方式
```

日志分析输出格式：

```text
失败时间线
首个异常点
相关模块
根因判断
证据
修复建议
```

原理问题：

```text
为什么诊断报告要分结论和证据？
如何避免 Agent 凭空编造 CI 失败原因？
为什么要结合日志、代码和 diff 三类信息？
mock 数据为什么对 Demo 很重要？
如何区分根因、症状和相关性？
```

面试问题：

```text
你的 Agent 如何分析一次 CI 失败？
如何判断失败是代码改动引起还是环境问题？
如何保证诊断报告有依据？
日志分析时如何定位第一个异常点？
```

验收标准：

```text
Agent 能稳定调用 get_ci_result、search_code、git_diff
Agent 能稳定调用 search_log、search_code
DiagnosisService 能把工具证据、LLM 调用和 DiagnosisReport 校验串成闭环
POST /api/v1/diagnoses/ci 返回结构化报告或结构化失败
回答中必须引用具体日志或文件
Demo 可以重复运行
```

---

## 10. 第 7 周：代码合入审查 + 结构化修改建议

目标：实现平台无关的代码合入审查闭环，根据 `base_ref...head_ref` 分析待合入变更，并以 GitHub App 作为首个平台适配，通过 Pull Request webhook 触发审查和回写非阻塞建议。

本周重点原理：

```text
three-dot diff 与 merge base
变更 hunk 和受影响上下文
代码审查风险分类与严重级别
证据驱动 finding
误报、漏报与可行动建议
结构化输出和 Review Evaluation
GitHub App、webhook 签名与 delivery 幂等
平台 adapter 与核心服务解耦
```

每日任务与验收：

```text
Day 43：定义代码审查领域模型与风险分类 [x]
产出：src/devagent/review/models.py、tests/review/test_review_models.py
类型：CodeReviewInput、CodeReviewReport、ReviewFinding、ReviewSeverity、ReviewCategory
验收：每条 finding 必须包含文件、行号、evidence_ids、修改建议和验证方式；悬空证据引用被拒绝

Day 44：实现 git_compare 与变更证据采集 [x]
产出：扩展 src/devagent/tools/git_tools.py、tests/tools/test_git_tools.py
接口：git_compare(...) -> GitCompareResult；GitCompareTool -> ToolResult
验收：使用 merge base 读取变更范围；保留文件状态、hunk 定位和截断元数据；不执行 checkout、merge、commit 或 push

Day 45：设计证据驱动的 Merge Review Prompt [x]
产出：src/devagent/prompts/code_review.py、tests/prompts/test_code_review.py
边界：只报告证据支持的可行动问题，区分 correctness、security、compatibility、performance、maintainability、test_gap，不把格式偏好升级为阻塞问题
验收：固定输出通过 CodeReviewReport 校验；证据不足时返回 missing_evidence

Day 46：实现 CodeReviewService [x]
产出：src/devagent/review/service.py、tests/review/test_service.py
执行链：git_compare -> Evidence -> read_file / search_code 补充代码上下文 -> LLMClient.chat() -> CodeReviewReportDraft -> Service 绑定身份与原始 evidence -> CodeReviewReport
验收：模型非法 JSON、悬空 evidence_id、工具失败均转换为结构化错误或证据不足状态

Day 47：实现代码审查 API 与平台协议 [x]
产出：src/devagent/api/routes/reviews.py、src/devagent/review/ports.py、tests/api/test_reviews.py
接口：POST /api/v1/reviews/code
协议：PullRequestSource、ReviewPublisher、WebhookDeliveryStore
验收：输入 base_ref、head_ref 和 workspace，返回结构化报告；核心 service 不导入 GitHub SDK；API 不自动修改、批准或合入代码

Day 48：接入 GitHub Pull Request 建议模式 [x]
产出：src/devagent/integrations/github/、src/devagent/api/routes/github_webhooks.py、tests/integrations/github/
接口：POST /api/v1/integrations/github/webhooks
触发事件：opened、reopened、synchronize、ready_for_review
执行边界：签名、事件和幂等检查后返回 202，由 TaskManager 异步完成审查与发布
验收：基于原始 body 和常量时间比较校验 X-Hub-Signature-256；有界内存 DeliveryStore 保证 delivery ID 幂等；使用 FakeGitHubClient 回写摘要和以 line / side 定位的 inline comments，无法映射时降级到摘要；不访问真实网络
学习记录：对应 daily 文档解释 GitHub App installation token、webhook 签名、delivery redelivery、202 异步确认和 review comment line / side 定位

Day 49：建立 Review Evaluation 并完成端到端验收 [x]
产出：eval/cases/code_review/、src/devagent/eval/review_metrics.py、src/devagent/eval/live_review.py、tests/eval/test_review_metrics.py、tests/eval/test_live_review.py、tests/integration/test_github_pr_review.py、eval/reports/code_review_baseline.md、eval/reports/code_review_live_summary.md、docs/evaluation/github_pr_smoke.md
样例：正确性、安全、兼容性、性能、测试缺口、无缺陷变更和固定 GitHub webhook payload
真实验证：固定本地变更先通过真实 provider 的 Service / Git / read_file / Pydantic 全链路验收；GitHub 阶段在专用测试仓库安装 GitHub App，先用固定 LLM 验证平台链路，再显式使用真实 provider 完成一次分析
验收：Local Review 可重复计算 finding 匹配、误报、证据覆盖与引用完整率，并保存脱敏 live report；真实 PR 完成 opened、synchronize、redelivery，报告、Trace 和评论可由 report_id 关联
实测：专用 GitHub 测试仓库完成真实 App 鉴权、webhook、PR evidence、真实模型分析、摘要 upsert、inline comment 和 delivery 去重；真实 provider 找到 1 个 HIGH security finding，webhook 到摘要发布耗时 37.2 秒
```

### 第 7 周额外收尾

```text
运行代码审查 Evaluation 并记录基线
检查 HIGH / CRITICAL finding 是否都有直接证据和验证方式
对无缺陷变更检查误报
录制一次 base/head 合入审查 Demo
验证 GitHub App 最小权限、签名拒绝、delivery 去重和评论更新语义
记录真实 PR URL、base/head SHA、delivery GUID、report_id、评论 URL、阶段耗时和结果；不记录 token、私钥或 webhook secret
更新本周 daily 文档；README.md 和 plan.md 在周收尾统一同步
```

量化验收：

```text
HIGH / CRITICAL 风险召回率 >= 85%
可行动 finding 准确率 >= 70%
误报率 <= 20%
Finding 证据引用完整率 = 100%
文件与行号可定位率 = 100%
相比整文件注入，平均审查上下文字符数降低 >= 40%
小型本地样例仓库 diff 采集与证据预处理 p95 < 1 秒，不含 LLM 网络耗时
固定审查任务的人工证据查找步骤减少 >= 30%
无效 webhook 签名拒绝率 = 100%
重复 delivery 去重率 = 100%
固定 fixture 评论行号映射正确率 = 100%
真实 PR opened、synchronize、redelivery smoke test 成功率 = 100%
真实 PR 始终只保留 1 条 DevAgent 摘要评论
真实 PR webhook 接收到摘要评论发布耗时目标 < 60 秒
```

---

## 11. 第 8 周：RAG / Memory 基线 + Evaluation + 上下文压缩

目标：把第 6 到第 7 周的 CI 诊断、日志根因分析、代码合入审查和代码问答从“能跑”提升到“证据可检索、质量可评测、上下文可控”，并建立第 9 周检索优化可复用的 BM25 基线。

本周重点原理：

```text
文档 / 代码 / 日志切片
关键词检索与轻量 BM25
EvidenceSnippet
检索命中率
上下文压缩
Evaluation 数据集
指标前后对比
```

每日任务与验收：

```text
Day 50：定义 RAG / Memory 数据模型 [x]
产出：src/devagent/memory/models.py
类型：Document、Chunk、EvidenceSnippet、RetrievalResult
验收：每条 evidence 都包含 source、path、line_range 或等价定位信息

Day 51：实现本地切片器 [x]
产出：src/devagent/memory/chunker.py、tests/memory/test_chunker.py
范围：代码、Markdown、日志、CI JSON
验收：chunk 保留来源、行号、类型和稳定 chunk_id

Day 52：实现关键词检索器 [x]
产出：src/devagent/memory/retriever.py、tests/memory/test_retriever.py
策略：以 BM25 作为可复现基线，第 9 周在同一评测集上比较向量检索、混合召回和重排
验收：Top-5 能找回预期文件或日志片段

Day 53：实现 knowledge_retrieve 工具 [x]
产出：src/devagent/tools/knowledge_tools.py
工具接口：knowledge_retrieve(query, workspace, top_k) -> ToolResult
验收：ToolResult 返回压缩后的 evidence snippets，而不是整文件内容

Day 54：实现 Evaluation 基线 [x]
产出：eval/cases/、src/devagent/eval/runner.py、tests/eval/
指标：Tool Hit Rate、Evidence Hit Rate、Answer Keyword Hit Rate、Latency
验收：固定 20 条本地 eval cases 可以重复运行

Day 55：实现上下文压缩基础版 [x]
产出：src/devagent/agent/context_manager.py
策略：保留原始任务、关键观察、最近 N 轮消息和 evidence snippets
验收：长任务上下文字符数相比直接注入完整文件 / 日志降低 40% 以上

Day 56：RAG 对业务 Demo 的指标对比 [x]
产出：docs/evaluation.md、eval/reports/rag_baseline.md、真实 RAG Agent runner 与脱敏 live report
离线指标：Top-5 Evidence Hit Rate、Context Reduction Rate、Retrieval p95 Latency
真实指标：Tool Call Rate、Answer Keyword Hit Rate、Grounded Citation Rate、Abstention Accuracy、端到端 p95
验收：真实 provider 必须通过 AgentRuntime 自主调用 knowledge_retrieve 并生成结构化答案；报告同时保存成功和失败 case，能区分检索质量与最终回答质量
实测：gpt-5.6-terra / Responses 对 8 条代表性 case 完成真实运行，Tool Call、Evidence Hit、Grounded Citation、Abstention 均为 100%，严格端到端成功率 87.5%，p95 24.55 秒
```

### 第 8 周额外收尾

```text
运行完整 Evaluation
记录无 RAG 与有 RAG 的证据命中率、上下文长度和耗时差异
检查诊断报告是否引用 evidence source
整理 RAG、Evaluation、上下文压缩项目问答
更新本周 daily 文档；README.md 和 plan.md 在周收尾统一同步
```

量化验收：

```text
Top-5 Evidence Hit Rate >= 80%
平均上下文输入字符数降低 >= 40%
本地样例检索 p95 延迟 < 800ms
证据引用完整率 >= 90%
每次 Prompt / 工具描述 / RAG 策略调整后能输出前后指标对比
```

---

## 12. 第 9 周：RAG 增强 + 检索质量优化

目标：紧接第 8 周的 BM25、Evaluation 和上下文压缩基线，引入向量检索、混合召回与可替换重排，并在同一固定评测集上用质量、延迟和上下文成本决定默认检索策略。

本周重点：

```text
EmbeddingProvider 与 VectorRetriever 边界
向量检索
BM25 + 向量混合召回
分数归一化或 Reciprocal Rank Fusion
可替换 rerank
检索失败分类
同数据集前后指标对比
```

每日任务与验收：

```text
Day 57：固化 RAG 增强评测集与 BM25 基准 [x]
产出：eval/cases/rag/、eval/reports/rag_bm25_baseline.md
范围：将第 8 周 20 条用例扩充到 30 到 50 条，覆盖代码、Markdown、日志和 CI JSON，并以 expected_paths 标注 evidence source relevance
验收：固定数据集可重复输出 Top-5 Evidence Hit Rate、MRR@5、p95 延迟和失败类型
实测：36 条固定 case（30 正 / 6 负）覆盖 21 份多类型文档；BM25 Top-5 命中率 100%、MRR@5 98.3%、负样本准确率 100%、上下文减少 77.8%，本地检索 p95 7.31 ms

Day 58：定义向量检索抽象 [x]
产出：src/devagent/memory/embeddings.py、src/devagent/memory/vector_retriever.py
接口：EmbeddingProvider、VectorRetriever，provider 适配与检索流程解耦
验收：固定向量 fixture 可确定性验证相似度排序、空语料和 provider 失败
实测：固定二维向量完整经过文档编码、查询编码、单位化、cosine 排序和 Evidence 映射；排序与 tie-break 重复一致，异常向量拒绝、受控 provider 错误转换和空语料零调用均达到 100%

Day 59：实现向量检索基线 [x]
产出：向量索引构建、查询和元数据映射实现及 tests/memory/
验收：向量结果保留 source、path、line_range、score 和稳定 chunk_id，并输出与 BM25 的质量和延迟差异

Day 60：实现 BM25 + 向量混合召回 [x]
产出：src/devagent/memory/hybrid_retriever.py、tests/memory/test_hybrid_retriever.py
策略：使用可解释的分数归一化或 Reciprocal Rank Fusion，保留稳定 tie-break
验收：同一查询可追踪关键词与向量候选来源，融合结果可确定性复现

Day 61：实现可替换 rerank [x]
产出：src/devagent/memory/reranker.py、tests/memory/test_reranker.py
范围：只重排 Top-N 候选，记录召回分数、重排分数与耗时
验收：reranker 失败可降级到混合召回，EvidenceSnippet 定位信息不丢失

Day 62：接入业务链路并优化上下文 [x]
产出：knowledge_retrieve、CI / 日志诊断、代码合入审查的检索策略接入
验收：业务报告能引用混合检索 evidence；相比整文件或日志注入，平均上下文字符数降低 40% 以上

Day 63：RAG 增强对比与第 9 周验收 [x]
产出：docs/evaluation.md、eval/reports/rag_optimization.md、eval/reports/rag_live_provider.md
对比：BM25、向量、混合召回、混合召回 + rerank
验收：先根据固定数据集的质量、延迟和上下文成本选择候选策略；再让真实 provider 通过 AgentRuntime 在代表性正负样本上运行至少 2 次，比较答案关键词、证据引用、拒答、端到端延迟和失败率后决定默认策略
```

### 第 9 周额外收尾

```text
运行完整 RAG Evaluation 和相关业务回归
核对所有检索策略使用同一数据集、top_k 和统计口径
记录质量提升、延迟代价、失败分类和默认策略选择依据
运行真实 RAG Agent Evaluation，保存 provider/model、每条 case 的工具调用、最终答案、引用、耗时和失败原因
整理 RAG 检索、混合召回和 rerank 项目问答
每周收尾同步 README.md 和 plan.md
```

量化验收：

```text
固定 RAG eval cases 数量达到 30 到 50 条
完整固定集 Hit@5、Recall@5、负样本准确率、定位完整率与检索延迟先通过硬门槛
通过硬门槛后比较 Precision@5、NDCG@5、MRR@5、上下文和 provider 成本，不设置数学上不可达的固定增量
平均上下文输入字符数相比整文件 / 日志注入降低 >= 40%
本地样例库完整检索链路 p95 延迟 < 800ms
证据引用完整率 >= 95%
真实 Agent knowledge_retrieve Tool Call Rate = 100%
真实 Agent Grounded Citation Rate >= 90%
真实 Agent 负样本 Abstention Accuracy = 100%
真实 Agent 端到端成功率 >= 80%
```

---

## 13. 第 10 到第 13 周：关键扩展完善与最终交付

目标：不为了赶时间牺牲功能完整性。第 10 到第 13 周用于把持久化、Multi-Agent、Trace / Evaluation 和安全增强补扎实，并让第 9 周选定的 RAG 策略进入稳定业务闭环，形成有指标、有文档、有 Demo、有工程说服力的最终版本。

### 第 10 周：持久化深化 + Trace / Evaluation 数据闭环

状态：已完成（Day64-Day70）。任务、结构化事件与 sequence、工具调用、权限请求/策略、
Evaluation 运行、GitHub delivery 与 PR publication 已接入 SQLite Repository，并通过统一数据库
的 adapter 重建验收。

```text
重点：让任务、事件、工具调用和权限策略可以跨进程保存，支撑 Trace 回放和评测报告。
产出：storage 模块、Repository 接口、数据库设计文档、持久化测试。
验收：服务重启后仍能查询关键任务、事件 Trace、工具调用记录和权限策略。
```

优先任务：

```text
1. 设计 agent_tasks、agent_events、tool_calls、permission_policies、eval_runs 表。
2. 接入 SQLite 或 PostgreSQL，先保证 Repository 边界清晰。
3. EventBus / EventStore 写入持久化事件。
4. ToolExecutor 记录工具调用耗时、状态、错误码。
5. Evaluation 运行结果可保存、可对比。
6. GitHub webhook delivery 和 PR review 发布状态可持久化，服务重启后仍能避免重复审查与重复评论。
```

完成指标：1000 条事件重放 p95 4.82ms；12 路并发 webhook claim 仅 1 个成功；关键持久化
对象跨 adapter 重建恢复率 100%。

### 第 11 周：Multi-Agent 基础闭环 + 父子 Trace

```text
重点：让父 Agent 能把 CI、日志和代码分析拆成受控子任务，并保留完整父子 Trace。
产出：Multi-Agent 数据模型、Coordinator 或 SpawnAgentTool、父子 Trace、结果汇总器。
验收：父 Agent 能创建受限子任务、汇总证据并处理单个子任务失败，所有子任务均可追溯到父任务。
```

优先任务：

```text
1. 定义 SubAgentTask、SubAgentResult、AgentBudget。
2. 实现 Coordinator 或 SpawnAgentTool，并限制递归深度和子任务数量。
3. 建立 parent_task_id、child_task_id 和父子事件关联。
4. 汇总日志、代码、CI 子任务 evidence，保留来源与定位信息。
5. 实现部分失败降级，单个子任务失败不丢弃其他有效结果。
6. 用固定 CI / 日志诊断场景统计任务完成率、证据汇总完整率和额外耗时。
```

### 第 12 周：Multi-Agent 完整化 + 安全增强

```text
重点：让 Multi-Agent 服务 CI / 日志诊断，而不是为了堆概念。
产出：MultiAgentCoordinator、父子 Trace、预算与取消传播、安全增强测试。
验收：父 Agent 可以受控创建子 Agent，子任务隔离上下文，失败可降级，越权工具调用被拦截。
```

优先任务：

```text
1. 实现 max_depth、max_children、max_concurrency 和共享预算。
2. 子 Agent 只获得 allowed_tools。
3. 父任务取消时传播到运行中子任务。
4. 增加超时、预算耗尽和部分失败的结构化结果与 Evaluation。
5. 强化 CommandGuard、敏感字段脱敏和 Prompt Injection 防护文档。
```

### 第 13 周：最终交付 + 面试材料 + Demo 稳定性

```text
重点：把项目从“自己能跑”整理成“别人能看懂、面试能讲清、Demo 能稳定复现”。
产出：最终 README、架构图、安全设计、Evaluation 报告、Demo 脚本、项目问答、简历描述。
验收：新用户 15 分钟内启动；能稳定演示代码合入审查、CI 诊断、日志诊断、权限审批、Trace / RAG / Evaluation。
```

最终交付检查：

```text
1. 代码合入审查完成本地 base/head 闭环，并有高风险召回率、可行动建议准确率、误报率和证据引用指标。
2. RAG / Memory 完成最小可讲版本，并有 Evidence Hit Rate、上下文压缩率和检索延迟指标。
3. Multi-Agent 完成受控编排，支持父子 Trace、预算控制、取消传播和部分失败降级。
4. Trace / Evaluation 能支撑问题定位和前后指标对比。
5. 持久化能保存关键任务、事件、工具调用、权限策略和 Evaluation 结果。
6. README 只描述真实已实现能力，不夸大。
7. 架构图与代码模块一致。
8. Demo 脚本可以重复运行。
9. 安全文档能解释权限审批、危险命令拦截和敏感信息脱敏。
10. 简历项目描述有数字支撑，但不把 pytest passed 当主要成果。
```

README 必须包含：

```text
项目简介
核心功能
架构设计
快速开始
Demo 示例
核心模块
安全设计
评测结果
未来规划
```

简历项目描述模板：

```text
设计并实现面向研发效能场景的 AI Agent 后端平台，支持代码仓库分析、代码合入审查、CI 失败诊断和日志根因分析。系统采用 Agent Runtime + ToolRegistry + PermissionManager + EventBus 架构，实现多轮工具调用、权限审批、流式事件推送、Trace 回放和 Agent Evaluation。
```

项目 3 分钟讲法：

```text
第一段：项目是做什么的，解决什么场景。
第二段：核心架构，Agent Runtime、ToolRegistry、PermissionManager、EventBus。
第三段：技术难点，长任务、工具安全、事件流、Trace、评测。
第四段：Demo 和结果，代码合入审查、CI 失败诊断、日志根因分析、代码问答。
```

验收标准：

```text
能本地启动项目
能稳定演示代码合入审查、CI 诊断、日志诊断和权限审批等核心 Demo
README 清楚
简历描述清楚
能回答 30 个项目相关面试问题
```

---

## 14. 项目相关高频面试问题清单

这里只保留能够从 DevAgent 真实实现继续追问的问题，不承担通用八股复习职责。

### 14.1 项目中的 Python 设计

```text
1. 为什么 RunShellResult 使用 dataclass，而工具参数更适合使用 Pydantic？
2. 为什么工具执行层错误使用异常，命令非零退出码却作为结果返回？
3. 为什么正式模块不能在 import 时执行 input、print 或写文件？
4. editable install 解决了什么导入问题？
5. 为什么 workspace 应由调用方传入，而不是写成全局变量？
6. ToolResult 为什么需要 JSON 序列化？
7. BaseTool 为什么适合使用抽象基类？
8. async / await 在 Agent 和 FastAPI 中分别解决什么问题？
9. 如何用 pytest 的 tmp_path 测试文件与命令工具？
10. MockLLMClient 为什么比直接 Mock 某个函数更适合测试 Agent Loop？
```

### 14.2 项目中的后端设计

```text
1. 为什么创建 Agent 任务后先返回 task_id，而不是等待最终答案？
2. AgentTask 为什么需要显式状态机？
3. 为什么生产环境不能只依赖 asyncio.create_task 执行可靠长任务？
4. 本项目为什么可以优先使用 SSE，什么情况下才需要 WebSocket？
5. 如何设计任务取消，避免状态已经 CANCELLED 但工具仍继续执行？
6. ToolResult、HTTP 错误响应和 AgentTask FAILED 有什么区别？
7. Pydantic 参数校验应该放在 API 层、工具层，还是两层都需要？
8. 如何防止多个并发任务互相覆盖 workspace、事件或权限状态？
9. sequence_id 如何帮助断线重连和 Trace 回放？
10. EventBus 为什么能降低 AgentRuntime 与 UI 的耦合？
```

### 14.3 项目中的持久化设计

```text
1. tasks、events、tool_calls 为什么需要分表？
2. 为什么 events 需要 task_id + sequence_id 唯一约束？
3. 任务状态更新和事件写入是否需要事务？
4. 为什么不能把所有 ToolResult 和事件都只存为一大段文本？
5. 哪些事件 payload 适合 JSON 字段，哪些字段应该单独建列和索引？
6. 为什么内存 Repository 适合 MVP，却不适合服务重启后的任务回放？
7. 如何查询某个 task 的完整 Trace，并保证事件顺序？
8. tool_calls 表应该保存哪些字段，哪些敏感数据不能保存？
9. 如何统计工具失败率、平均耗时和 Agent 平均步骤数？
10. SQLite 切换到 PostgreSQL 时，本项目最可能遇到哪些差异？
```

### 14.4 Agent 原理

```text
1. Agent 和普通 ChatBot 的区别是什么？
2. Agent Loop 是什么？
3. ReAct 思想是什么？
4. tool calling 的流程是什么？
5. 工具结果为什么要注入上下文？
6. Agent 如何决定下一步调用哪个工具？
7. 如何避免 Agent 无限循环？
8. 如何处理工具调用失败？
9. 如何降低 Agent 幻觉？
10. 如何测试一个输出不稳定的 Agent？
```

### 14.5 工具系统与安全

```text
1. ToolRegistry 的作用是什么？
2. 工具描述为什么重要？
3. 工具参数如何校验？
4. 高风险工具为什么需要权限审批？
5. allow_once 和 always_allow 区别是什么？
6. 如何拦截危险 Shell 命令？
7. 如何限制文件读取范围？
8. Prompt Injection 是什么？
9. 日志里的恶意指令如何防护？
10. Docker Sandbox 能解决什么问题？
```

### 14.6 可观测性与评测

```text
1. 为什么 Agent 执行过程要事件化？
2. EventBus 的作用是什么？
3. Trace 和日志有什么区别？
4. WebSocket 如何实时推送事件？
5. 断线重连如何补发事件？
6. Agent Evaluation 是什么？
7. Tool Hit Rate 如何计算？
8. Keyword Hit Rate 有什么局限？
9. Prompt 改动后如何评估效果？
10. 长任务上下文太长怎么办？
```

---

## 15. 项目面试深挖回答模板

### 15.1 你的项目不是普通 ChatBot 吗？

回答：

```text
不是。普通 ChatBot 通常是用户输入后直接调用 LLM 返回文本，而我的项目实现了 Agent Runtime。它会根据任务多轮调用工具，例如代码搜索、文件读取、CI 查询、日志检索和 Git diff，然后把工具结果重新注入上下文继续推理。系统还有 ToolRegistry、PermissionManager 和 EventBus，分别解决工具扩展、安全审批和执行过程可观测问题。
```

### 15.2 Agent Loop 怎么工作？

回答：

```text
用户创建任务后，Agent Runtime 构造 system prompt 和 user message 调用 LLM。如果 LLM 返回 tool call，系统会通过 ToolRegistry 校验参数并执行工具。工具结果会作为 tool message 放回上下文，然后 Agent 继续下一轮推理。直到模型返回 final answer，或者达到 max_steps、任务超时、用户取消、工具不可恢复错误等结束条件。
```

### 15.3 如何保证工具调用安全？

回答：

```text
我把工具分成 LOW、MEDIUM、HIGH、CRITICAL 风险等级。read_file、search_code 这类只读工具可以直接执行，但 run_shell、文件写入、外部网络请求等高风险工具必须经过 PermissionManager。权限支持 allow_once、always_allow、deny_once、always_deny。同时 Shell 工具有命令黑名单、cwd 限制、timeout、输出截断，文件工具有 workspace 路径限制。
```

### 15.4 为什么需要 EventBus？

回答：

```text
Agent 不是一次性返回结果，而是一个持续执行过程，中间会有 LLM 调用、工具调用、权限审批、错误处理和最终总结。EventBus 把这些过程抽象成事件，Agent Runtime 只负责发布事件，WebSocket、Trace、日志和前端都可以订阅事件。这样 UI 和 Agent 解耦，也方便任务回放和问题定位。
```

### 15.5 如何分析 CI 失败？

回答：

```text
Agent 会先调用 get_ci_result 获取失败 job、测试用例和错误日志；然后提取关键错误，比如失败测试名和异常栈；接着用 search_code 搜索相关模块，用 git_diff 查看本次 commit 改动；最后综合 CI 日志、代码和 diff，输出结论、证据、涉及文件、可能原因、修复建议和验证方式。
```

### 15.6 如何分析待合入代码？

```text
我先用 base_ref...head_ref 和 merge base 获取真实合入范围，再把 diff hunk、受影响实现、调用方、测试和仓库规范标准化为 Evidence。模型只生成能引用证据的结构化 finding，每条问题都包含严重级别、文件行号、修改建议和验证方式。固定缺陷集会统计高风险召回率、可行动建议准确率和误报率，避免把“看起来像代码审查”当成真实效果。
```

### 15.7 如何评估 Agent 效果？

回答：

```text
我设计了最小 Evaluation。每个 eval case 包含 question、expected_tools 和 expected_keywords。运行 eval runner 后统计 Tool Hit Rate、Keyword Hit Rate、平均耗时、平均工具调用次数和失败率。这样 Prompt、工具描述或 Agent 策略修改后，可以用固定问题集比较效果，而不是只凭主观感觉。
```

---

## 16. 每周阶段产出清单

```text
第 1 周交付：read_file、search_code、run_shell、ToolResult、pytest 测试
第 2 周交付：命令行 Agent、ToolRegistry、MockLLMClient、真实 LLMClient
第 3 周交付：FastAPI 服务、任务创建、任务状态机、任务事件查询
第 4 周交付：PermissionManager、PolicyStore、CommandGuard、ToolExecutor、Permission API
第 5 周交付：EventBus、SSE/WebSocket、Trace 查询与回放
第 6 周交付：CI 诊断 Demo、Git diff、日志分析、诊断执行闭环
第 7 周交付：代码合入审查、GitHub PR 建议模式、结构化修改建议、Review Evaluation 基线与指标报告
第 8 周交付：RAG / Memory BM25 基线、Evaluation 基线、上下文压缩、RAG 基线报告
第 9 周交付：向量检索、混合召回、可替换 rerank、RAG 质量与延迟对比报告
第 10 周交付：持久化 Repository、事件 / 工具调用 / 权限策略落库、Trace 数据闭环
第 11 周交付：Multi-Agent 基础闭环、父子 Trace、证据汇总、部分失败降级
第 12 周交付：Multi-Agent 完整化、父子 Trace、预算控制、取消传播、安全增强
第 13 周交付：最终 README、架构图、安全设计、Evaluation 报告、Demo 脚本、简历与面试材料
```

---

## 17. 学习优先级

如果时间不够，按这个优先级砍功能：

```text
必须完成：
1. Python 工具函数
2. ToolRegistry
3. Agent Loop
4. FastAPI 任务接口
5. EventBus
6. PermissionManager
7. CI 诊断 Demo
8. 代码合入审查闭环
9. RAG / Evaluation 最小闭环

尽量完成：
1. WebSocket
2. Trace 回放
3. search_log
4. git_diff
5. 多 Agent 编排最小闭环
6. 持久化最小闭环
7. README
8. 测试

有余力再做：
1. pgvector / Qdrant
2. Docker Sandbox
3. 前端页面
4. MCP
5. 多模型供应商适配
```

---

## 18. 最终秋招准备标准

投递前自查：

```text
我能 3 分钟讲清项目背景、架构和亮点
我能 10 分钟讲清 Agent Loop、ToolRegistry、PermissionManager、EventBus
我能现场跑一个 Demo
我能展示一次有证据、可定位、可量化评测的代码合入审查
我能解释每个核心模块为什么这样设计
我能回答安全、评测、上下文、长任务、WebSocket、数据库相关问题
README 能让别人本地跑起来
简历描述不夸大，也突出工程复杂度
```

最终你要给面试官留下的印象：

```text
这个候选人不是只会调大模型 API。
他理解 Agent 的工程化落地问题。
他知道工具调用、安全审批、事件流、Trace、评测这些真实系统问题。
他的后端基础虽然还在成长，但能持续把复杂系统拆成可运行模块。
```
