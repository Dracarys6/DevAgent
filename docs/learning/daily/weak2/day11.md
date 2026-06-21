# Day 11：AgentRunResult 与 Agent 防失控

## 今天目标

Day 10 的 `AgentRuntime.run()` 已经可以完成最小 Agent Loop，但它现在只返回一个字符串。

今天要把 Runtime 从：

```text
返回 final answer 字符串
```

升级为：

```text
返回一次 Agent 运行的结构化结果
```

也就是说，调用方不仅要知道“答案是什么”，还要知道：

```text
1. Agent 是否成功
2. 为什么停止
3. 一共调用了几次 LLM
4. 一共执行了几次工具
5. 最后有没有错误
6. 是否触发 max_steps / max_tool_calls / 重复工具调用保护
7. 完整 messages 是否可用于调试
```

这是从 Demo Agent 走向工程 Agent 的关键一步。

---

## 今日开发范围

只围绕 `src/devagent/agent/` 做增强，不引入真实 LLM、不做 FastAPI、不做权限系统。

建议新增或修改这些文件：

```text
src/devagent/agent/models.py
src/devagent/agent/runtime.py
src/devagent/agent/__init__.py
tests/agent/test_runtime.py
docs/learning/daily/weak2/day11.md
```

今天先不要拆出太多复杂类。核心目标是让 `AgentRuntime` 的停止状态清晰、可测试、可解释。

---

## 一、核心原理

### 1. 为什么不能只返回字符串

如果 `run()` 只返回字符串，调用方无法区分下面几种情况：

```text
模型正常回答：完成分析
超过最大步数：Agent 超过最大步数限制: 10
工具不存在：无法执行 missing_tool
工具参数错误：file_path 缺失
重复工具调用：模型一直调用同一个 search_code
```

这些情况都可能被包装成文本，但它们的工程含义完全不同。

后端服务、CLI、Web UI、测试系统都更需要结构化结果：

```python
result.success
result.status
result.final_answer
result.steps
result.tool_call_count
result.error_message
```

### 2. Agent 防失控是什么

Agent Loop 本质上是一个循环：

```text
LLM -> tool -> LLM -> tool -> ...
```

只要模型持续返回工具调用，循环就可能失控。

常见失控方式：

```text
1. 一直调用同一个工具和同一组参数
2. 每轮都调用很多工具
3. 工具失败后仍反复调用
4. LLM 永远不给 final answer
5. 上下文越来越长，成本和延迟持续上升
```

所以 Runtime 必须具备硬限制：

```text
max_steps：最多调用多少轮 LLM
max_tool_calls：一次 run 最多执行多少个工具
重复工具调用检测：同一个工具 + 同一参数连续出现时提前停止
```

---

## 二、建议接口设计

### 1. 新增 AgentRunStatus

文件：

```text
src/devagent/agent/models.py
```

建议定义：

```python
from enum import Enum


class AgentRunStatus(str, Enum):
    SUCCESS = "success"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"
    MAX_TOOL_CALLS_EXCEEDED = "max_tool_calls_exceeded"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    LLM_ERROR = "llm_error"
    TOOL_ERROR = "tool_error"
```

设计说明：

```text
SUCCESS：模型返回 final answer
MAX_STEPS_EXCEEDED：达到最大 LLM 调用轮数
MAX_TOOL_CALLS_EXCEEDED：工具调用次数超过预算
REPEATED_TOOL_CALL：检测到重复工具调用
LLM_ERROR：llm_client.chat 抛异常
TOOL_ERROR：工具执行失败并且你选择直接终止
```

注意：今天可以先不使用 `TOOL_ERROR` 终止流程。因为目前工具失败会被写回 messages，让模型有机会恢复。你可以保留这个状态给后续用。

### 2. 新增 AgentRunResult

同一个文件中继续定义：

```python
from typing import Any

from pydantic import BaseModel, Field


class AgentRunResult(BaseModel):
    success: bool
    status: AgentRunStatus
    final_answer: str = ""
    steps: int = 0
    tool_call_count: int = 0
    error_message: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
```

字段含义：

```text
success：这次运行是否正常完成
status：机器可读的结束原因
final_answer：最终回答，失败时可以为空字符串
steps：实际调用 LLM 的次数
tool_call_count：实际执行工具的次数
error_message：失败原因，成功时为 None
messages：完整上下文快照，方便调试和测试
```

为什么 `status` 和 `error_message` 都要有：

```text
status 给程序判断
error_message 给人阅读
```

### 3. 修改 AgentRuntime 初始化参数

文件：

```text
src/devagent/agent/runtime.py
```

建议把构造函数改成：

```python
def __init__(
    self,
    llm_client: LLMClient,
    tool_registry: ToolRegistry,
    system_prompt: str = "你是一个可以调用工具的代码助手",
    max_steps: int = 10,
    max_tool_calls: int = 20,
    stop_on_repeated_tool_call: bool = True,
) -> None:
```

新增字段：

```text
max_tool_calls：一次 run 最多允许执行多少个工具
stop_on_repeated_tool_call：是否启用重复工具调用保护
```

### 4. 修改 run 返回类型

原来：

```python
def run(self, user_input: str) -> str:
```

建议修改为：

```python
def run(self, user_input: str) -> AgentRunResult:
```

这会导致 Day10 测试需要一起更新。不要害怕，这是合理演进。

如果你担心兼容性，可以额外提供一个便捷方法：

```python
def run_text(self, user_input: str) -> str:
    return self.run(user_input).final_answer
```

但今天不是必须。

---

## 三、推荐实现步骤

### Step 1：创建 agent/models.py

先实现：

```text
AgentRunStatus
AgentRunResult
```

然后在：

```text
src/devagent/agent/__init__.py
```

导出：

```python
from devagent.agent.models import AgentRunResult, AgentRunStatus
from devagent.agent.runtime import AgentRuntime

__all__ = ["AgentRuntime", "AgentRunResult", "AgentRunStatus"]
```

### Step 2：让成功路径返回 AgentRunResult

先只改成功路径，不急着处理所有异常。

原来：

```python
return final_answer
```

改成类似：

```python
self._save_messages(messages)
return AgentRunResult(
    success=True,
    status=AgentRunStatus.SUCCESS,
    final_answer=final_answer,
    steps=step,
    tool_call_count=tool_call_count,
    messages=deepcopy(messages),
)
```

注意：`step` 需要来自循环变量。

循环建议写成：

```python
for step in range(1, self.max_steps + 1):
```

不要用 `_step`，因为今天需要把它放进结果里。

### Step 3：统计工具调用次数

在 `run()` 开始时增加：

```python
tool_call_count = 0
```

每执行一个工具前，先判断是否超限：

```python
if tool_call_count >= self.max_tool_calls:
    return self._finish_with_error(
        messages=messages,
        status=AgentRunStatus.MAX_TOOL_CALLS_EXCEEDED,
        steps=step,
        tool_call_count=tool_call_count,
        error_message=f"Agent 超过最大工具调用次数限制: {self.max_tool_calls}",
    )
```

执行成功或失败都算一次工具调用：

```python
tool_result = self._execute_tool_call(tool_call)
tool_call_count += 1
```

### Step 4：处理 max_steps

循环结束后，不再返回字符串，而是返回：

```python
return self._finish_with_error(
    messages=messages,
    status=AgentRunStatus.MAX_STEPS_EXCEEDED,
    steps=self.max_steps,
    tool_call_count=tool_call_count,
    error_message=f"Agent 超过最大步数限制: {self.max_steps}",
)
```

同时可以继续把错误文本追加到 messages：

```python
messages.append({"role": "assistant", "content": error_message})
```

### Step 5：封装错误结束方法

建议新增私有方法，避免重复写返回结构：

```python
def _finish_with_error(
    self,
    messages: list[dict[str, Any]],
    status: AgentRunStatus,
    steps: int,
    tool_call_count: int,
    error_message: str,
) -> AgentRunResult:
    messages.append({"role": "assistant", "content": error_message})
    self._save_messages(messages)
    return AgentRunResult(
        success=False,
        status=status,
        final_answer="",
        steps=steps,
        tool_call_count=tool_call_count,
        error_message=error_message,
        messages=deepcopy(messages),
    )
```

这个方法的好处：

```text
所有异常停止都使用同一套结构
测试更容易写
后续加入事件记录时入口更集中
```

### Step 6：检测重复工具调用

重复工具调用的定义建议先简单一点：

```text
连续两次出现相同 tool name 和相同 arguments，就认为重复。
```

不要跨很多轮做复杂检测，今天先做最小可解释版本。

可以在 `run()` 中维护：

```python
last_tool_signature: tuple[str, str] | None = None
```

由于 `arguments` 是 dict，不能直接稳定比较字符串顺序，建议用 JSON 标准化：

```python
import json


def _tool_signature(self, tool_call: ToolCall) -> tuple[str, str]:
    return (
        tool_call.name,
        json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False),
    )
```

执行工具前判断：

```python
signature = self._tool_signature(tool_call)
if self.stop_on_repeated_tool_call and signature == last_tool_signature:
    return self._finish_with_error(
        messages=messages,
        status=AgentRunStatus.REPEATED_TOOL_CALL,
        steps=step,
        tool_call_count=tool_call_count,
        error_message=f"检测到重复工具调用: {tool_call.name}",
    )
last_tool_signature = signature
```

注意这个判断应该发生在实际执行工具之前。否则重复调用已经造成副作用了。

### Step 7：捕获 LLM 异常

真实 LLM 后续可能出现：

```text
网络错误
认证失败
限流
响应解析失败
```

今天可以先在 `llm_client.chat(messages)` 外面包一层：

```python
try:
    response = self.llm_client.chat(messages)
except Exception as exc:
    return self._finish_with_error(
        messages=messages,
        status=AgentRunStatus.LLM_ERROR,
        steps=step,
        tool_call_count=tool_call_count,
        error_message=f"LLM 调用失败: {exc}",
    )
```

这属于兜底保护。后续接真实 API 时会非常有用。

---

## 四、测试任务

文件：

```text
tests/agent/test_runtime.py
```

建议修改现有 Day10 测试，让它们断言 `AgentRunResult`。

### 必做测试 1：成功返回结构化结果

测试点：

```text
result.success is True
result.status == AgentRunStatus.SUCCESS
result.final_answer == "已完成代码搜索和文件读取，这是最终回答。"
result.steps == 3
result.tool_call_count == 2
result.error_message is None
```

### 必做测试 2：messages 写入 result

测试点：

```text
result.messages == runtime.messages
result.messages 的 role 顺序仍然正确
```

### 必做测试 3：max_steps 返回失败状态

测试点：

```text
result.success is False
result.status == AgentRunStatus.MAX_STEPS_EXCEEDED
result.final_answer == ""
result.error_message == "Agent 超过最大步数限制: 2"
result.steps == 2
```

### 必做测试 4：max_tool_calls 返回失败状态

构造一个 response，一次返回两个工具调用，然后设置：

```python
max_tool_calls=1
```

预期：

```text
第一个工具执行
准备执行第二个工具时触发限制
result.status == AgentRunStatus.MAX_TOOL_CALLS_EXCEEDED
result.tool_call_count == 1
```

### 必做测试 5：重复工具调用提前停止

构造连续重复调用：

```python
responses = [
    LLMResponse.tool_calls_response([
        ToolCall(id="call_1", name="search_code", arguments={"query": "x", "workspace": "."})
    ]),
    LLMResponse.tool_calls_response([
        ToolCall(id="call_2", name="search_code", arguments={"workspace": ".", "query": "x"})
    ]),
]
```

注意这里故意调换参数顺序，用来验证 `sort_keys=True`。

预期：

```text
result.success is False
result.status == AgentRunStatus.REPEATED_TOOL_CALL
result.tool_call_count == 1
```

### 必做测试 6：LLM 异常返回 LLM_ERROR

可以在测试里写一个很小的 fake client：

```python
class FailingLLMClient:
    def chat(self, messages):
        raise RuntimeError("boom")
```

预期：

```text
result.success is False
result.status == AgentRunStatus.LLM_ERROR
result.error_message == "LLM 调用失败: boom"
```

---

## 五、今日不建议做的事

今天先不要做：

```text
1. 不接真实 OpenAI API
2. 不做 FastAPI
3. 不引入异步 async
4. 不做数据库记录
5. 不设计复杂状态机
6. 不把 Runtime 拆成很多文件
7. 不实现用户取消
```

原因：

```text
Day11 的重点是把 Agent Loop 的结果和停止原因定义清楚。
先把同步 Runtime 做扎实，后面接 API 和异步任务会轻松很多。
```

---

## 六、推荐实现顺序

建议按这个顺序写代码：

```text
1. 新建 src/devagent/agent/models.py
2. 定义 AgentRunStatus
3. 定义 AgentRunResult
4. 修改 AgentRuntime.run 返回 AgentRunResult
5. 修复成功路径测试
6. 增加 max_steps 失败结果
7. 增加 max_tool_calls
8. 增加重复工具调用检测
9. 增加 LLM 异常捕获
10. 更新 __init__.py 导出
11. 运行 pytest
12. 回来补充本 day11.md 的“完成内容”和“验收结果”
```

每完成一小步就跑一次相关测试：

```bash
.venv/bin/pytest tests/agent/test_runtime.py -q
```

全部完成后跑完整测试：

```bash
.venv/bin/pytest -q
python -m compileall src tests
git diff --check
```

---

## 七、验收标准

### 基础通过

```text
1. AgentRuntime.run 返回 AgentRunResult
2. 成功路径可以正常返回 final_answer
3. Day10 原有 Agent Loop 行为没有坏
4. tests/agent/test_runtime.py 通过
```

### 工程通过

```text
1. max_steps 返回 MAX_STEPS_EXCEEDED
2. max_tool_calls 返回 MAX_TOOL_CALLS_EXCEEDED
3. 重复工具调用返回 REPEATED_TOOL_CALL
4. LLM 异常返回 LLM_ERROR
5. messages 使用深拷贝保存，避免被外部修改污染
6. 完整 pytest 通过
```

### 面试通过

你需要能回答：

```text
1. 为什么 Agent Runtime 不能只返回字符串？
2. Agent Loop 有哪些失控风险？
3. max_steps 和 max_tool_calls 分别解决什么问题？
4. 如何检测重复工具调用？为什么要标准化 arguments？
5. 工具执行失败时，应该直接终止还是写回模型继续推理？
6. 为什么 status 适合给程序判断，error_message 适合给人阅读？
```

---

## 八、面试表达模板

### Q1：为什么要设计 AgentRunResult？

```text
因为 Agent 运行结果不仅包含最终回答，还包含运行过程状态。只返回字符串无法区分正常完成、超过最大步数、工具调用过多、重复调用或 LLM 异常。AgentRunResult 把 success、status、final_answer、steps、tool_call_count、error_message 和 messages 结构化，方便后端接口返回、测试断言、日志追踪和后续可观测性建设。
```

### Q2：Agent Loop 如何防止失控？

```text
我主要做了三层限制。第一层是 max_steps，限制 LLM 最多推理多少轮，避免模型永远不给最终答案。第二层是 max_tool_calls，限制一次任务最多执行多少个工具，避免成本和副作用失控。第三层是重复工具调用检测，如果连续出现相同工具和相同参数，说明模型可能陷入循环，可以提前终止并返回明确状态。
```

### Q3：为什么重复工具调用要对 arguments 做 JSON 标准化？

```text
因为 Python dict 的语义不依赖键顺序，{"query": "x", "workspace": "."} 和 {"workspace": ".", "query": "x"} 应该被认为是同一次调用。使用 json.dumps(arguments, sort_keys=True) 可以生成稳定签名，避免因为参数顺序不同漏掉重复调用。
```

### Q4：工具失败后为什么不一定立刻终止？

```text
工具失败不一定意味着 Agent 任务失败。例如 read_file 找不到文件后，模型可能根据错误信息改用 search_code 查找正确路径。所以更合理的默认策略是把 ToolResult 写回 messages，让模型有机会恢复。只有达到工具调用预算、重复调用或安全限制时，Runtime 才主动终止。
```

---

## 九、今日完成记录

```text
完成内容：
- 新增 AgentRunStatus 与 AgentRunResult
- AgentRuntime.run 从返回字符串升级为返回结构化结果
- 成功路径记录 success、status、final_answer、steps、tool_call_count、messages
- 失败路径统一使用 _finish_with_error 返回结构化错误
- 增加 max_tool_calls 工具调用预算
- 增加连续重复工具调用检测
- 使用 json.dumps(sort_keys=True) 标准化工具参数签名
- 捕获 llm_client.chat 异常并返回 LLM_ERROR
- 更新 agent/__init__.py 导出 AgentRuntime、AgentRunResult、AgentRunStatus
- 补全 tests/agent/test_runtime.py 的 Day11 边界测试

遇到的问题：
- agent/models.py 反向导入 runtime.py，导致循环导入
- last_tool_signature 没有初始化，第一次工具调用会触发运行时错误
- 部分测试仍然把 runtime.run() 的返回值当字符串比较
- max_tool_calls 需要在每个工具执行前检查，不能只在每轮 LLM 响应前检查
- 重复调用检测会影响“同一响应内重复调用相同工具”的场景，需要提供关闭开关并写清测试语义

最终测试：
- tests/agent/test_runtime.py：12 passed
- 完整 pytest：81 passed
- compileall：通过
- git diff --check：通过

今天最重要的理解：
- Agent Runtime 不应该只返回文本答案，还应该返回可被程序判断的停止原因。success、status、error_message、steps 和 tool_call_count 是后续 API、任务系统、日志追踪和面试表达的基础。
```

---

## 明天计划预告

Day 12 可以开始做 Runtime 的事件记录雏形：

```text
1. 定义 AgentEvent
2. 记录 llm_start / llm_end
3. 记录 tool_start / tool_end
4. 把 events 放入 AgentRunResult
5. 为后续 Trace、WebSocket 和任务状态接口做准备
```
