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

每天 3 到 5 小时，建议按下面节奏：

```text
30 分钟：复习昨天内容，整理卡点
60 到 90 分钟：学习当天核心原理
90 到 150 分钟：写代码完成当天任务
30 到 60 分钟：写测试、写笔记、准备面试表达
```

每天必须产出至少一个东西：

```text
一个函数
一个类
一个接口
一个测试
一段项目笔记
一个面试问题答案
一个可运行 Demo
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
第 2 周：Agent Loop + Tool Calling
第 3 周：FastAPI 后端 + 任务状态
第 4 周：ToolRegistry + PermissionManager + 安全控制
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

### Day 1：环境与 Python 基础

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
Python 的 list 和 dict 底层大概有什么特点？
Python 为什么需要虚拟环境？
```

验收标准：

```text
pytest 可以跑通
你能解释 venv、pip、pytest 分别解决什么问题
```

### Day 2：文件读取工具 read_file

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

### Day 3：路径安全

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

### Day 4：代码搜索工具 search_code

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

### Day 5：Shell 执行工具 run_shell

学习任务：

```text
1. 学习 subprocess 超时
2. 学习 shell=True 的风险
3. 学习命令输出截断
```

开发任务：

```text
1. 实现 run_shell(command, cwd, timeout)
2. 捕获 stdout、stderr、returncode
3. 设置 timeout
4. 限制 cwd 在 workspace 内
5. 限制输出长度
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
```

### Day 6：ToolResult 与错误模型

学习任务：

```text
1. 学习 dataclass 或 Pydantic BaseModel
2. 学习结构化返回
3. 学习错误码设计
```

开发任务：

```text
1. 定义 ToolResult
2. 字段包括 success、content、metadata、error_code、error_message
3. read_file、search_code、run_shell 都返回 ToolResult
4. 补测试
```

原理理解：

```text
为什么工具不应该直接返回字符串？
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
```

### Day 7：本周复盘

复盘任务：

```text
1. 整理第 1 周代码
2. 补齐测试
3. 写一页学习笔记：工具系统的安全边界
4. 准备 5 个面试问题答案
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

## 5. 第 2 周：Agent Loop + Tool Calling

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

开发任务：

```text
1. 定义 BaseTool
2. 每个工具包含 name、description、args_schema、risk_level、execute
3. 实现 ToolRegistry.register
4. 实现 ToolRegistry.execute
5. 注册 read_file、search_code、run_shell
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

### Day 9：MockLLMClient

开发任务：

```text
1. 定义 LLMResponse
2. 定义 ToolCall
3. 实现 MockLLMClient
4. 第一次返回 search_code tool_call
5. 第二次返回 read_file tool_call
6. 第三次返回 final_answer
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

### Day 10：最小 AgentRuntime

开发任务：

```text
1. 实现 AgentRuntime.run(user_input)
2. 构造 messages
3. 调用 llm_client.chat
4. 如果有 tool_call，执行工具
5. 把工具结果加入 messages
6. 如果没有 tool_call，返回 final answer
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

### Day 11：max_steps、错误处理、重复调用检测

开发任务：

```text
1. 加入 max_steps
2. 工具不存在时返回错误给模型
3. 参数错误时返回错误给模型
4. 记录最近工具调用
5. 简单检测重复调用同一个工具同一参数
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

### Day 12：接入真实 LLM API

开发任务：

```text
1. 编写真实 LLMClient
2. 从环境变量读取 API Key
3. 构造 tools schema
4. 解析 tool_calls
5. 保留 MockLLMClient 用于测试
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

### Day 13：命令行 Demo

开发任务：

```text
1. 实现 app/agent/cli.py
2. 支持命令行输入问题
3. 输出每一步工具调用
4. 输出最终答案
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

### Day 14：本周复盘

复盘任务：

```text
1. 补 AgentRuntime 测试
2. 画一张 Agent Loop 流程图
3. 写 10 个面试问答
4. 整理命令行 Demo 录屏脚本
```

本周必须能讲清楚：

```text
Agent Loop
Tool Calling
工具结果注入上下文
max_steps
mock LLM 的价值
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

每日任务：

```text
Day 15：创建 FastAPI app，实现 GET /health
Day 16：实现 POST /api/v1/agent/tasks 创建任务
Day 17：实现 AgentTask 模型和任务状态机
Day 18：实现 GET /api/v1/agent/tasks/{task_id}
Day 19：用 BackgroundTasks 或 asyncio.create_task 异步执行 Agent
Day 20：实现 GET /api/v1/agent/tasks/{task_id}/events
Day 21：补测试、整理 Swagger 演示流程
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
```

验收标准：

```text
uvicorn app.main:app --reload 能启动
Swagger 可以创建 Agent 任务
任务状态能从 PENDING -> RUNNING -> DONE
events 接口能返回执行记录
```

---

## 7. 第 4 周：ToolRegistry + PermissionManager + 安全控制

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

每日任务：

```text
Day 22：把工具参数改成 Pydantic args_schema
Day 23：ToolRegistry 生成 LLM tool schema
Day 24：定义 risk_level：LOW / MEDIUM / HIGH / CRITICAL
Day 25：实现 PermissionManager，支持 allow_once / deny_once
Day 26：支持 always_allow / always_deny 策略
Day 27：run_shell 接入权限审批和危险命令拦截
Day 28：补权限测试，整理安全设计文档
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

每日任务：

```text
Day 29：定义 BaseEvent 和事件类型
Day 30：实现内存版 EventBus
Day 31：AgentRuntime 发布 AgentStarted / AgentFinished / AgentError
Day 32：工具调用发布 ToolCallStarted / ToolCallFinished / ToolCallFailed
Day 33：权限流程发布 PermissionRequested / PermissionResolved
Day 34：实现 WebSocket 事件推送
Day 35：实现事件回放，补测试和演示脚本
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

每日任务：

```text
Day 36：准备 examples/sample_repo
Day 37：实现 git_diff 工具
Day 38：准备 mock CI 数据，实现 get_ci_result
Day 39：准备 mock 日志，实现 search_log
Day 40：设计 CI 失败诊断 Prompt
Day 41：设计日志根因分析 Prompt
Day 42：完成两个稳定 Demo，录制演示流程
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

目标：把项目从 Demo 提升为真实后端工程。

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

每日任务：

```text
Day 43：学习 SQL 基础，设计 tasks、events、tool_calls 表
Day 44：接入 SQLite 或 PostgreSQL
Day 45：事件落库，支持服务重启后查询历史事件
Day 46：工具调用记录落库，统计耗时和失败率
Day 47：准备 20 条 eval cases
Day 48：实现 eval runner，统计工具命中率和关键词命中率
Day 49：实现最小上下文压缩，补测试和文档
```

推荐先 SQLite 后 PostgreSQL：

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

每日任务：

```text
Day 50：整理项目目录和 README
Day 51：画架构图和 Agent Loop 流程图
Day 52：补核心测试：ToolRegistry、PermissionManager、EventBus
Day 53：整理 3 个 Demo：代码问答、CI 诊断、权限审批
Day 54：写项目面试问答 30 题
Day 55：写简历项目描述，准备 3 分钟版本
Day 56：模拟面试，查漏补缺
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

## 12. 高频面试问题清单

### 12.1 Python 基础

```text
1. list 和 tuple 的区别是什么？
2. dict 的查询为什么通常很快？
3. Python 中可变对象和不可变对象有什么区别？
4. 深拷贝和浅拷贝有什么区别？
5. 装饰器是什么？
6. 生成器是什么？有什么优势？
7. async / await 的作用是什么？
8. Python 的 GIL 是什么？
9. dataclass 和普通 class 有什么区别？
10. Pydantic 解决什么问题？
```

### 12.2 后端基础

```text
1. HTTP GET 和 POST 有什么区别？
2. RESTful API 是什么？
3. FastAPI 为什么适合 AI 应用后端？
4. 同步接口和异步接口有什么区别？
5. 长任务为什么不能阻塞 HTTP 请求？
6. WebSocket 和 SSE 有什么区别？
7. 后端如何管理任务状态？
8. 如何设计错误码？
9. 如何做接口参数校验？
10. 如何设计一个可回放的任务系统？
```

### 12.3 数据库基础

```text
1. 主键和索引有什么区别？
2. 为什么事件表需要 sequence_id？
3. JSONB 适合存什么，不适合存什么？
4. 事务是什么？
5. 数据库迁移是什么？
6. 为什么不能所有状态都只放内存？
7. PostgreSQL 相比 SQLite 的优势是什么？
8. 如何查询某个 task 的完整 Trace？
9. tool_calls 表应该存哪些字段？
10. 如何统计工具失败率和平均耗时？
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
