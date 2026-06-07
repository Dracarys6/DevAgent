# DevAgent 秋招开发学习计划

目标：用最多 2 个月，每天 3 到 5 小时，围绕 DevAgent 项目系统提升 Python、后端开发、AI Agent 开发、工程设计和面试表达能力，争取秋招投递中大厂 AI 应用开发 / 后端开发岗位时，有一个能讲深、能演示、能扩展的项目。

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
```

---

## 0. 当前进度与计划维护规则

当前进度：

```text
已完成 Day 1 到 Day 5
当前自动化测试：23 个
已完成正式模块：
- read_file
- workspace 路径安全
- search_code
- run_shell
- RunShellResult
```

计划不是固定不变的课程表。后续每次验收时，根据实际完成情况更新：

```text
1. 已提前掌握的内容，从后续计划中删除或升级难度
2. 验收暴露出的薄弱点，加入下一天或周复盘
3. 项目功能完成后，必须补原理、测试和面试表达
4. 如果某天任务超过 5 小时，可以拆成两天，不追求机械赶进度
5. 如果提前完成，可以做扩展任务，但不能跳过测试和复盘
```

完成状态标记：

```text
[x] 已完成并验收
[~] 已实现，仍需完善
[ ] 尚未开始
```

---

## 1. 两个月总目标

两个月结束时，你应该拥有：

```text
1. 一个可运行的 DevAgent 后端项目
2. 一个命令行 Agent Demo
3. 一个 FastAPI 后端服务
4. ToolRegistry、PermissionManager、EventBus 三个核心模块
5. read_file、search_code、run_shell、git_diff、get_ci_result、search_log 工具
6. CI 失败诊断和日志根因分析 Demo
7. 基础测试用例
8. README、项目架构说明、面试问答文档
9. 一套能讲 3 分钟、10 分钟、30 分钟的项目表达
```

如果时间充足，再补：

```text
1. PostgreSQL 事件落库
2. Trace 回放
3. Agent Evaluation
4. 上下文压缩
5. Docker Sandbox
6. 简单 Web 页面或 TUI
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

---

## 3. 八周学习主线

```text
第 1 周：Python 工程基础 + 命令行工具
第 2 周：统一工具协议 + Agent Loop + Tool Calling
第 3 周：FastAPI 后端 + 任务状态
第 4 周：PermissionManager + 安全控制 + 异步任务
第 5 周：EventBus + WebSocket + Trace
第 6 周：CI 诊断 / 日志分析业务 Demo
第 7 周：数据库 + Evaluation + 上下文压缩
第 8 周：项目打磨 + 面试准备 + 简历包装
```

最低成功标准：

```text
完成第 1 到第 6 周，就已经有一个能讲的 AI Agent 后端项目。
第 7 周和第 8 周用于把项目从“能跑”提升到“中大厂面试可讲”。
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

两个月主线只实现能够组成完整 DevAgent 闭环的能力。以下内容不默认加入主线：

```text
多 Agent
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

### Day 1：环境与 Python 基础 [x]

学习任务：

```text
1. 学会使用 venv 创建虚拟环境
2. 学会 pip 安装依赖
3. 学会运行 python 文件
4. 学会运行 pytest
5. 复习变量、字符串、列表、字典、函数
```

开发任务：

```text
1. 创建 requirements.txt 或 pyproject.toml
2. 安装 pytest、pydantic、fastapi、uvicorn
3. 创建 tests/test_smoke.py
4. 写一个最简单的 add(a, b) 函数并测试
```

原理理解：

```text
venv 为什么重要？
pip 安装的包保存在哪里？
模块导入时 Python 会去哪里找文件？
pytest 怎么发现测试文件？
```

面试问题：

```text
为什么 DevAgent 需要虚拟环境和 editable install？
为什么正式模块不能在 import 时直接执行 input 或写文件？
```

验收标准：

```text
pytest 可以跑通
你能解释 venv、pip、pytest 分别解决什么问题
```

### Day 2：文件读取工具 read_file [x]

学习任务：

```text
1. 学习 pathlib.Path
2. 学习文件读取 open / read_text
3. 学习异常 FileNotFoundError、PermissionError
```

开发任务：

```text
1. 实现 read_file(path, start_line, end_line)
2. 返回带行号的文本
3. 限制最大读取 200 行
4. 文件不存在时返回清晰错误
5. 写 3 个测试：正常读取、文件不存在、行号非法
```

原理理解：

```text
相对路径和绝对路径有什么区别？
为什么 Agent 读文件要限制行数？
为什么工具结果最好带行号？
```

面试问题：

```text
你如何防止 Agent 读取敏感文件？
如果用户传入 ../../.ssh/id_rsa，你怎么处理？
```

验收标准：

```text
read_file 可以读取 plan.md 指定行
read_file 不会一次返回超大文件
```

### Day 3：路径安全 [x]

学习任务：

```text
1. 学习 Path.resolve()
2. 学习 workspace 根目录限制
3. 学习路径穿越攻击
```

开发任务：

```text
1. 实现 ensure_workspace_path(workspace, path)
2. 禁止读取 workspace 外文件
3. 禁止读取 .ssh、/etc、/var 等敏感路径
4. 给路径安全写测试
```

原理理解：

```text
路径穿越是什么？
为什么不能只用字符串 contains 判断路径安全？
resolve() 的作用是什么？
```

面试问题：

```text
本地 Agent 为什么比普通 ChatBot 更需要权限控制？
你如何设计文件访问白名单？
```

验收标准：

```text
../ 跳出项目目录会被拒绝
绝对路径指向项目外会被拒绝
```

### Day 4：代码搜索工具 search_code [x]

学习任务：

```text
1. 学习 subprocess.run
2. 学习 stdout / stderr / returncode
3. 学习 ripgrep rg 的基础用法
```

开发任务：

```text
1. 实现 search_code(query, workspace, file_pattern=None)
2. 优先调用 rg
3. 限制搜索结果最大字符数
4. 搜不到时返回空结果，不要直接报错
5. 写测试或手动验证
```

原理理解：

```text
关键词搜索和向量搜索有什么区别？
为什么第一版代码检索可以先用 rg？
为什么工具输出要截断？
```

面试问题：

```text
代码检索为什么不能只依赖向量数据库？
grep / rg 这类关键词搜索在 Agent 中有什么价值？
```

验收标准：

```text
能搜索当前项目中的 plan.md、Agent、ToolRegistry 等关键词
```

### Day 5：Shell 执行工具 run_shell [x]

学习任务：

```text
1. 学习 subprocess 超时
2. 学习 shell=True 的风险
3. 学习命令输出截断
```

开发任务：

```text
1. 实现 run_shell(command, cwd, timeout, workspace)
2. 定义 RunShellResult，保留 stdout、stderr、returncode
3. 区分命令业务失败与工具执行层错误
4. 设置 timeout
5. 限制 cwd 在 workspace 内
6. 分别限制 stdout 和 stderr 长度
7. 处理命令不存在、权限不足和超时
```

原理理解：

```text
为什么 shell 命令是高风险工具？
timeout 为什么重要？
stdout 和 stderr 有什么区别？
```

面试问题：

```text
如果 Agent 想执行 rm -rf /，系统应该如何拦截？
你如何设计 Shell 工具的安全边界？
```

验收标准：

```text
能执行 pytest
超时命令会被终止
输出不会无限大
非零退出码不会丢失 stderr 和 returncode
cwd 越过 workspace 时会被拒绝
```

### Day 6：ToolResult 与错误模型

学习任务：

```text
1. 对比 dataclass、TypedDict、Pydantic BaseModel
2. 学习结构化返回和序列化
3. 学习错误码设计
4. 区分底层执行结果和统一工具结果
```

开发任务：

```text
1. 在 src/devagent/tools/models.py 定义 ToolResult
2. 字段包括 success、content、metadata、error_code、error_message
3. 定义稳定错误码，例如 FILE_NOT_FOUND、PATH_OUTSIDE_WORKSPACE、COMMAND_TIMEOUT
4. 编写适配函数，将 read_file、search_code、RunShellResult 转为 ToolResult
5. 保留 RunShellResult 作为底层执行结果，不直接删除
6. ToolResult 必须可以转成 JSON，供未来 LLM 和 API 使用
7. 补成功、业务失败、执行异常、JSON 序列化测试
```

原理理解：

```text
为什么工具不应该直接返回字符串？
为什么底层 RunShellResult 和上层 ToolResult 可以同时存在？
异常和错误返回值分别适合什么情况？
结构化错误对 Agent 自我修复有什么帮助？
```

面试问题：

```text
LLM 调工具失败后，如何让它根据错误继续修正？
工具返回值为什么要标准化？
```

验收标准：

```text
所有工具返回统一结构
失败时有明确 error_code
metadata 保留 returncode、cwd 等机器可读信息
ToolResult 可以被 JSON 序列化
调用方不需要解析中文字符串判断错误类型
```

### Day 7：本周复盘

复盘任务：

```text
1. 整理第 1 周代码
2. 删除正式模块中的重复练习实现
3. 补齐测试并检查覆盖的边界情况
4. 写一页学习笔记：工具系统的安全边界
5. 准备 8 个面试问题答案
6. 画出 read_file、search_code、run_shell 到 ToolResult 的调用图
7. 运行 ruff 或基础代码检查，可选
```

本周必须能讲清楚：

```text
文件读取为什么要限制 workspace？
代码搜索为什么先用 rg？
Shell 执行有哪些风险？
ToolResult 为什么要结构化？
pytest 在项目中起什么作用？
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

### Day 8：BaseTool 与 ToolRegistry

学习任务：

```text
1. 学习抽象基类 ABC 和泛型基础
2. 学习 Pydantic 参数模型与 JSON Schema
3. 理解依赖倒置和注册表模式
```

开发任务：

```text
1. 定义 BaseTool，包含 name、description、args_schema、risk_level、execute
2. 实现 ReadFileTool、SearchCodeTool、RunShellTool 适配器
3. 实现 ToolRegistry.register / get / list / execute
4. 禁止重复注册同名工具
5. 参数校验失败时返回统一 ToolResult
6. 注册并执行 read_file、search_code、run_shell
7. 编写注册、查询、重复注册、未知工具、参数错误测试
```

原理理解：

```text
ToolRegistry 解决什么问题？
为什么 Agent 不应该直接调用具体函数？
工具 description 为什么会影响 LLM 调用质量？
```

面试问题：

```text
你如何设计可扩展的工具系统？
新增一个工具需要改哪些地方？
```

验收标准：

```text
ToolRegistry 不依赖具体工具实现
工具参数由 Pydantic 校验
任意工具执行后都返回 ToolResult
新增工具时不需要修改 Registry 核心逻辑
```

### Day 9：MockLLMClient

学习任务：

```text
1. 理解 system、user、assistant、tool 四类消息
2. 理解 tool_call_id 的作用
3. 理解模型响应为何需要内部统一协议
```

开发任务：

```text
1. 定义 LLMResponse
2. 定义 ToolCall
3. 实现 MockLLMClient
4. 第一次返回 search_code tool_call
5. 第二次返回 read_file tool_call
6. 第三次返回 final_answer
7. 测试固定响应序列和调用次数
```

原理理解：

```text
为什么先用 mock？
测试 Agent Loop 时，真实 LLM 有什么问题？
```

面试问题：

```text
如何测试一个输出不稳定的 Agent？
为什么 Agent 项目需要 mock LLM？
```

验收标准：

```text
测试不调用网络和真实模型
MockLLMClient 可以稳定复现多轮工具调用
ToolCall 参数可以被序列化和校验
```

### Day 10：最小 AgentRuntime

开发任务：

```text
1. 实现 AgentRuntime.run(user_input)
2. 构造 messages
3. 调用 llm_client.chat
4. 如果有 tool_call，执行工具
5. 把工具结果加入 messages
6. 如果没有 tool_call，返回 final answer
7. 保存每轮完整 messages，便于测试和调试
```

原理理解：

```text
Agent Loop 的本质是什么？
工具结果为什么要重新放回上下文？
max_steps 为什么是必需的？
```

面试问题：

```text
你的 Agent 是怎么从用户问题一步步得到最终答案的？
Agent 什么时候停止？
```

验收标准：

```text
Agent 能按 MockLLMClient 计划调用 search_code 和 read_file
工具结果作为 tool message 写回 messages
最终返回稳定答案
测试可以断言工具调用顺序
```

### Day 11：max_steps、错误处理、重复调用检测

开发任务：

```text
1. 加入 max_steps
2. 工具不存在时返回错误给模型
3. 参数错误时返回错误给模型
4. 记录最近工具调用
5. 简单检测重复调用同一个工具同一参数
6. 定义 AgentRunResult，记录最终状态、答案、步数和错误
```

原理理解：

```text
Agent 为什么会失控？
重复工具调用可能是什么原因？
如何区分可恢复错误和不可恢复错误？
```

面试问题：

```text
如何避免 Agent 无限循环？
如何处理工具调用失败？
```

验收标准：

```text
达到 max_steps 后能够正常结束
未知工具和参数错误会反馈给模型
相同工具和参数连续重复时会被检测
Agent 失败不会只留下未处理异常
```

### Day 12：接入真实 LLM API

学习任务：

```text
1. 理解 token、context window、temperature 和 tool schema
2. 理解 API Key 环境变量管理
3. 理解模型供应商适配层的作用
```

开发任务：

```text
1. 编写真实 LLMClient
2. 从环境变量读取 API Key
3. 构造 tools schema
4. 解析 tool_calls
5. 保留 MockLLMClient 用于测试
6. 对网络错误、限流、超时做最小错误处理
7. 不把 API Key 写进仓库
```

原理理解：

```text
system prompt 的作用是什么？
tool schema 如何影响模型选择工具？
temperature 对稳定性有什么影响？
```

面试问题：

```text
Prompt 和 tool description 分别控制什么？
如何降低 Agent 的幻觉？
```

验收标准：

```text
真实模型能调用至少一个工具
没有 API Key 时给出清晰中文错误
Mock 测试仍然可以离线运行
供应商返回结构不会直接泄漏到 AgentRuntime
```

### Day 13：命令行 Demo

开发任务：

```text
1. 实现 app/agent/cli.py
2. 支持命令行输入问题
3. 输出每一步工具调用
4. 输出最终答案
5. 支持 --workspace 和 --max-steps 参数
6. 对用户输入和错误做友好展示
```

演示命令：

```bash
python -m app.agent.cli "这个项目的入口在哪里？"
```

面试问题：

```text
你能现场演示 Agent 调用工具分析代码吗？
这个 Demo 和普通 ChatBot 有什么区别？
```

验收标准：

```text
从任意目录运行时可以显式指定 workspace
能够看到工具名、参数、结果摘要和最终答案
命令失败时不会打印难以理解的完整堆栈
```

### Day 14：本周复盘

复盘任务：

```text
1. 补 AgentRuntime 测试
2. 画一张 Agent Loop 流程图
3. 写 10 个面试问答
4. 整理命令行 Demo 录屏脚本
5. 复习项目中实际使用的 ABC、Pydantic、dataclass 和异常链
6. 整理 ToolRegistry 与 Agent Loop 项目深挖问答
```

本周必须能讲清楚：

```text
Agent Loop
Tool Calling
工具结果注入上下文
max_steps
mock LLM 的价值
```

本周最终验收：

```text
命令行 Agent 可以稳定完成一次代码仓库入口分析
离线测试不依赖真实 LLM
能画出 User -> AgentRuntime -> LLMClient -> ToolRegistry -> ToolResult 的调用链
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
Day 15：创建 FastAPI app、配置模块和 GET /health
产出：app/main.py、配置读取、health 接口测试
验收：uvicorn 启动成功，pytest 可使用 TestClient 调接口

Day 16：设计创建任务 API
产出：CreateTaskRequest、CreateTaskResponse、POST /api/v1/agent/tasks
验收：非法 max_steps 被 Pydantic 拒绝，响应包含 task_id 和 PENDING

Day 17：实现 AgentTask 与显式状态转移
产出：TaskStatus、AgentTask、内存 TaskRepository
验收：非法状态转移被拒绝，状态机有单元测试

Day 18：实现任务查询和取消接口
产出：GET /tasks/{id}、POST /tasks/{id}/cancel
验收：任务不存在返回 404，取消后的状态一致

Day 19：学习 asyncio，并异步执行 Agent
产出：TaskManager、asyncio.create_task 管理、异常回收
验收：创建接口快速返回；任务在后台变为 RUNNING / DONE / FAILED
说明：理解 BackgroundTasks 适合响应后小任务，不等同于可靠任务队列

Day 20：实现内存事件记录和事件查询接口
产出：最小事件模型、GET /tasks/{id}/events
验收：能看到任务开始、结束和错误事件

Day 21：接口测试、并发基础与本周复盘
产出：API 集成测试、Swagger 演示步骤、后端原理笔记
验收：同时创建多个任务不会互相覆盖；能讲清项目为何需要异步任务
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
uvicorn app.main:app --reload 能启动
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
Day 22：复查 ToolRegistry 与参数 Schema
产出：LLM tool schema 导出、schema 快照测试
验收：工具协议只维护一份，不重复定义参数结构

Day 23：定义风险模型和 PermissionRequest
产出：RiskLevel、PermissionDecision、PermissionRequest
验收：风险等级和审批状态可以 JSON 序列化

Day 24：实现内存 PermissionManager
产出：request、resolve、allow_once、deny_once
验收：未审批的高风险调用无法执行

Day 25：实现 always_allow / always_deny 匹配规则
产出：PermissionPolicy、最小资源匹配策略
验收：说明规则粒度，避免“允许一次 pytest”扩大成“允许所有 Shell”

Day 26：设计 CommandGuard
产出：固定参数列表检查、危险程序 / 参数检测、测试
验收：拦截明显危险调用；文档明确黑名单不是完整安全方案

Day 27：把 run_shell 接入审批链
产出：ToolExecutor 调用 PermissionManager 后执行工具
验收：任务进入 WAITING_PERMISSION，批准后继续，拒绝后返回 ToolResult

Day 28：安全测试与异步等待复盘
产出：权限绕过测试、Prompt Injection 笔记、安全设计文档
验收：能讲清楚审批、策略、命令检测、Sandbox 四层防护
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
Day 29：定义事件协议
产出：BaseEvent、事件类型、task_id、sequence_id、timestamp、payload
验收：事件可 JSON 序列化；同一任务 sequence_id 单调递增

Day 30：实现内存 EventBus
产出：publish、subscribe、unsubscribe、事件历史
验收：一个事件可被多个订阅者收到；失败订阅者不拖垮发布流程

Day 31：AgentRuntime 接入生命周期事件
产出：AgentStarted、LLMCallStarted、LLMCallFinished、AgentFinished、AgentError
验收：成功和失败任务都有完整闭环事件

Day 32：工具与权限流程接入事件
产出：ToolCallStarted / Finished / Failed、PermissionRequested / Resolved
验收：事件 payload 不泄漏 API Key 等敏感信息

Day 33：实现 SSE，再理解 WebSocket
产出：SSE 任务事件流接口
验收：浏览器或 curl 能持续接收服务端事件
说明：本项目主要是服务端单向推送，先做 SSE 更简单；审批需要双向交互时再用普通 HTTP 或 WebSocket

Day 34：实现 WebSocket 和断线重连协议
产出：session stream、last_seen_sequence_id
验收：断线重连后能补发缺失事件，不重复展示已确认事件

Day 35：Trace 回放、网络基础和本周复盘
产出：历史回放接口、事件时序图、SSE/WebSocket 对比笔记
验收：能用一次 task_id 回放完整执行轨迹；能解释本项目为何选择 SSE 或 WebSocket
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
Day 36：设计可重复的 sample_repo 和失败场景
产出：最小代码仓库、失败测试、固定 commit / diff
验收：不调用 Agent 时，人可以手动复现失败并说明根因

Day 37：实现 git_diff 工具
产出：GitDiffTool、参数模型、输出截断、错误处理
验收：合法 commit 返回 diff；非法 commit 返回结构化错误

Day 38：准备 mock CI 数据并实现 get_ci_result
产出：固定 CI JSON、工具实现、Schema 校验
验收：工具能返回失败 job、test case、核心日志，不把整份日志全部塞入上下文

Day 39：实现 search_log
产出：按 task_id / level / keyword 检索的 mock 日志工具
验收：结果按时间排序，支持截断，明确首个异常点

Day 40：设计证据驱动的 CI 诊断流程
产出：CI Prompt、诊断报告模型、至少 3 个测试场景
验收：每个结论引用具体工具证据；缺少证据时明确说明

Day 41：设计日志根因分析流程
产出：时间线整理、首个异常识别、相关代码搜索链路
验收：区分根因、后续连锁错误和推测

Day 42：稳定性测试、Git/CI 基础和 Demo
产出：两个 Demo、失败恢复场景、演示脚本
验收：连续运行 3 次得到可接受结果；完成 Git/CI 面试笔记
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
回答中必须引用具体日志或文件
Demo 可以重复运行
```

---

## 10. 第 7 周：数据库 + Evaluation + 上下文压缩

目标：优先完成持久化和最小 Evaluation。上下文压缩属于进阶任务，如果前两项未完成，不强行赶进度。

本周重点原理：

```text
SQL
SQLAlchemy / SQLModel
数据库迁移
事件落库
工具调用记录
Evaluation
指标统计
上下文窗口
上下文压缩
```

每日任务与验收：

```text
Day 43：学习 SQL、索引和事务，设计数据模型
产出：tasks、events、tool_calls 表设计和关系图
验收：能解释主键、外键、唯一索引、task_id + sequence_id 约束

Day 44：先接入 SQLite 和 SQLAlchemy
产出：ORM Model、Repository、数据库迁移或初始化脚本
验收：业务层不直接散落 SQL；Repository 有测试

Day 45：任务、事件和工具调用落库
产出：持久化 Repository、服务重启后查询
验收：事件顺序一致；敏感参数不会原样落库

Day 46：学习事务与并发一致性，完成 Trace 查询
产出：Trace 查询接口、耗时和失败率统计
验收：同一 task 的 sequence_id 不冲突；能解释何时需要事务

Day 47：设计最小 eval dataset
产出：至少 10 条高质量 eval case，而不是机械凑 20 条
验收：覆盖正确工具、错误恢复、证据引用和权限触发

Day 48：实现 eval runner
产出：Tool Hit Rate、Answer Keyword Hit Rate、Failure Rate、Latency
验收：Mock 模型评测完全可重复；真实模型评测记录模型与 Prompt 版本

Day 49：根据进度二选一
优先项：把 SQLite 切换或兼容 PostgreSQL，并学习索引与 JSONB
进阶项：实现最小上下文压缩，保留目标、关键观察和最近消息
验收：只完成一个但讲清原理，不同时做两个半成品
```

推荐先 SQLite，项目稳定后再 PostgreSQL：

```text
SQLite：上手快，适合学习 ORM 和表设计
PostgreSQL：更接近企业后端，适合最终项目展示
```

原理问题：

```text
为什么事件要落库？
为什么需要 Evaluation？
Agent 评测和普通接口测试有什么区别？
上下文为什么会爆？
为什么上下文压缩不能简单截断？
```

面试问题：

```text
你如何评估 Agent 的效果？
Prompt 修改后如何判断变好了？
长任务上下文太长怎么办？
如何回放和调试一次 Agent 执行？
数据库中存哪些关键数据？
```

验收标准：

```text
任务和事件可以持久化
能运行 eval runner
能输出 Tool Hit Rate、Keyword Hit Rate、Average Latency
长任务触发上下文压缩事件
```

第 7 周最低验收：

```text
必须完成：任务和事件持久化、最小 Evaluation
尽量完成：PostgreSQL 或上下文压缩，二选一
不要求：Redis、向量数据库、复杂任务队列
```

---

## 11. 第 8 周：项目打磨 + 面试准备 + 简历包装

目标：把项目变成秋招能投、能讲、能演示的作品。

本周重点：

```text
README
架构图
Demo 脚本
测试覆盖
简历描述
面试问答
项目复盘
```

每日任务与验收：

```text
Day 50：代码质量与项目清理
产出：删除重复实现、统一命名、配置和错误码、运行完整测试
验收：新用户按 README 可以在 15 分钟内启动项目

Day 51：架构文档
产出：系统架构图、Agent Loop 时序图、权限审批时序图
验收：图和真实代码一致，不画尚未实现的能力

Day 52：测试与失败演练
产出：核心模块测试、超时、工具失败、拒绝权限、断线重连场景
验收：能够现场解释一个真实 bug 是如何被测试发现的

Day 53：Demo 与量化结果
产出：代码问答、CI 诊断、权限审批三个 Demo
验收：记录成功率、平均步骤、平均耗时等真实数据

Day 54：技术面试准备
产出：项目问答 30 题、围绕项目实际实现的 Python / 后端 / Agent 深挖
验收：不看文档口述 10 个项目深挖问题

Day 55：简历与项目表达
产出：真实简历描述、3 分钟和 10 分钟项目讲法
验收：只写已经实现且能被追问的能力，不使用夸大指标

Day 56：模拟面试和缺口修复
产出：至少一次完整模拟面试记录、问题清单、最终修复
验收：现场启动 Demo、讲架构、解释取舍、回答失败案例
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
设计并实现面向研发效能场景的 AI Agent 后端平台，支持代码仓库分析、CI 失败诊断和日志根因分析。系统采用 Agent Runtime + ToolRegistry + PermissionManager + EventBus 架构，实现多轮工具调用、权限审批、流式事件推送、Trace 回放和 Agent Evaluation。
```

项目 3 分钟讲法：

```text
第一段：项目是做什么的，解决什么场景。
第二段：核心架构，Agent Runtime、ToolRegistry、PermissionManager、EventBus。
第三段：技术难点，长任务、工具安全、事件流、Trace、评测。
第四段：Demo 和结果，CI 失败诊断、日志根因分析、代码问答。
```

验收标准：

```text
能本地启动项目
能稳定演示 3 个 Demo
README 清楚
简历描述清楚
能回答 30 个项目相关面试问题
```

---

## 12. 项目相关高频面试问题清单

这里只保留能够从 DevAgent 真实实现继续追问的问题，不承担通用八股复习职责。

### 12.1 项目中的 Python 设计

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

### 12.2 项目中的后端设计

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

### 12.3 项目中的持久化设计

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

### 12.4 Agent 原理

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

### 12.5 工具系统与安全

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

### 12.6 可观测性与评测

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

## 13. 项目面试深挖回答模板

### 13.1 你的项目不是普通 ChatBot 吗？

回答：

```text
不是。普通 ChatBot 通常是用户输入后直接调用 LLM 返回文本，而我的项目实现了 Agent Runtime。它会根据任务多轮调用工具，例如代码搜索、文件读取、CI 查询、日志检索和 Git diff，然后把工具结果重新注入上下文继续推理。系统还有 ToolRegistry、PermissionManager 和 EventBus，分别解决工具扩展、安全审批和执行过程可观测问题。
```

### 13.2 Agent Loop 怎么工作？

回答：

```text
用户创建任务后，Agent Runtime 构造 system prompt 和 user message 调用 LLM。如果 LLM 返回 tool call，系统会通过 ToolRegistry 校验参数并执行工具。工具结果会作为 tool message 放回上下文，然后 Agent 继续下一轮推理。直到模型返回 final answer，或者达到 max_steps、任务超时、用户取消、工具不可恢复错误等结束条件。
```

### 13.3 如何保证工具调用安全？

回答：

```text
我把工具分成 LOW、MEDIUM、HIGH、CRITICAL 风险等级。read_file、search_code 这类只读工具可以直接执行，但 run_shell、文件写入、外部网络请求等高风险工具必须经过 PermissionManager。权限支持 allow_once、always_allow、deny_once、always_deny。同时 Shell 工具有命令黑名单、cwd 限制、timeout、输出截断，文件工具有 workspace 路径限制。
```

### 13.4 为什么需要 EventBus？

回答：

```text
Agent 不是一次性返回结果，而是一个持续执行过程，中间会有 LLM 调用、工具调用、权限审批、错误处理和最终总结。EventBus 把这些过程抽象成事件，Agent Runtime 只负责发布事件，WebSocket、Trace、日志和前端都可以订阅事件。这样 UI 和 Agent 解耦，也方便任务回放和问题定位。
```

### 13.5 如何分析 CI 失败？

回答：

```text
Agent 会先调用 get_ci_result 获取失败 job、测试用例和错误日志；然后提取关键错误，比如失败测试名和异常栈；接着用 search_code 搜索相关模块，用 git_diff 查看本次 commit 改动；最后综合 CI 日志、代码和 diff，输出结论、证据、涉及文件、可能原因、修复建议和验证方式。
```

### 13.6 如何评估 Agent 效果？

回答：

```text
我设计了最小 Evaluation。每个 eval case 包含 question、expected_tools 和 expected_keywords。运行 eval runner 后统计 Tool Hit Rate、Keyword Hit Rate、平均耗时、平均工具调用次数和失败率。这样 Prompt、工具描述或 Agent 策略修改后，可以用固定问题集比较效果，而不是只凭主观感觉。
```

---

## 14. 每周交付物清单

```text
第 1 周交付：read_file、search_code、run_shell、ToolResult、pytest 测试
第 2 周交付：命令行 Agent、ToolRegistry、MockLLMClient、真实 LLMClient
第 3 周交付：FastAPI 服务、任务创建、状态查询、事件查询
第 4 周交付：PermissionManager、风险等级、Shell 审批、危险命令拦截
第 5 周交付：EventBus、WebSocket 事件流、Trace 回放
第 6 周交付：CI 诊断 Demo、日志分析 Demo、mock 数据
第 7 周交付：数据库落库、Evaluation、上下文压缩
第 8 周交付：README、架构图、简历描述、30 个面试问答、Demo 脚本
```

---

## 15. 学习优先级

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

尽量完成：
1. WebSocket
2. Trace 回放
3. search_log
4. git_diff
5. README
6. 测试

有余力再做：
1. PostgreSQL
2. Evaluation
3. 上下文压缩
4. Docker Sandbox
5. 前端页面
6. 多 Agent
7. MCP
```

---

## 16. 最终秋招准备标准

投递前自查：

```text
我能 3 分钟讲清项目背景、架构和亮点
我能 10 分钟讲清 Agent Loop、ToolRegistry、PermissionManager、EventBus
我能现场跑一个 Demo
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
