# Day 10：最小 AgentRuntime

## 今天目标

把 `LLMClient`、`ToolRegistry` 和 messages 串成最小 Agent Loop，实现：

```text
用户输入
-> LLM 返回 tool call
-> Registry 执行工具
-> ToolResult 写回 messages
-> LLM 继续推理
-> 返回 final answer
```

## 完成内容

```text
1. 创建 src/devagent/agent/runtime.py
2. 实现 AgentRuntime.run(user_input)
3. 构造 system 和 user 初始消息
4. 调用统一 LLMClient
5. 执行一个或多个 ToolCall
6. 写入 assistant tool_calls 消息
7. 写入带 tool_call_id 的 tool result 消息
8. 循环直到 final_answer
9. 保存最近一次 run 的 messages 和历史快照
10. 提前实现 max_steps 基础限制
```

## 验收中发现的问题

### 1. assistant 拼写错误

原实现：

```python
"role": "assitant"
```

修正：

```python
"role": "assistant"
```

消息角色属于协议字段，拼写错误会导致真实模型无法识别消息。

### 2. Runtime 应依赖 LLMClient 协议

原实现使用：

```python
llm_client: Any
```

修正为：

```python
llm_client: LLMClient
```

这样 Runtime 只依赖 `chat(messages) -> LLMResponse` 协议，可以替换 Mock 或真实客户端。

### 3. messages 历史需要深拷贝

浅拷贝只复制外层列表，内部字典仍共享引用。

```python
snapshot = list(messages)
```

修改某个内部消息后，历史快照也可能变化。

修正为：

```python
snapshot = deepcopy(messages)
```

## Agent Loop 消息顺序

默认 Mock 流程最终产生：

```text
system
user
assistant：请求 search_code
tool：返回 search_code 结果
assistant：请求 read_file
tool：返回 read_file 结果
assistant：final answer
```

最终验证角色顺序：

```python
[
    "system",
    "user",
    "assistant",
    "tool",
    "assistant",
    "tool",
    "assistant",
]
```

## 为什么工具结果必须写回 messages

LLM 本身无法看到后端执行工具后的结果。只有把结果作为 `tool` 消息加入下一次请求，模型才能基于真实代码、日志或命令输出继续推理。

`tool_call_id` 用于把工具结果与对应调用关联：

```text
assistant tool_call id=call_search_code_001
tool result tool_call_id=call_search_code_001
```

## 测试覆盖

```text
1. 默认 Mock 工作流返回最终答案
2. search_code 和 read_file 按预期顺序调用
3. tool result 被写入下一次 LLM 请求
4. 同一响应包含多个工具调用
5. 未知工具错误被写回 messages
6. 达到 max_steps 后停止
7. messages 历史快照互相独立
```

## 最终验收

```text
完整测试：76 passed
代码编译：通过
git diff --check：通过
真实最小 Agent Loop 运行：通过
LLM 调用次数：3
工具调用顺序：search_code -> read_file
最终回答：稳定返回
```

## 当前边界

以下能力留到 Day 11：

```text
结构化 AgentRunResult
重复工具调用检测
更完整的错误状态
用户取消
工具调用数量限制
```

## 项目深挖问题

```text
Q：Agent Loop 的本质是什么？
A：Agent Loop 是一个受限制的状态循环。Runtime 把上下文发给模型，解析模型的工具调用，执行工具并把结果写回上下文，再继续调用模型，直到模型返回最终答案或触发最大步骤等停止条件。
```

```text
Q：为什么 AgentRuntime 不直接调用 read_file 等函数？
A：Runtime 只依赖 ToolRegistry。Registry 统一完成工具查找、参数校验和执行，因此新增工具不需要修改 Runtime，也便于后续统一接入权限审批和事件记录。
```

## 明天计划

Day 11 完善 Agent 防失控与结果模型：

```text
1. 定义 AgentRunResult
2. 记录最终状态、答案、步数和错误
3. 检测重复工具调用
4. 处理参数错误和未知工具后的恢复
5. 增加 max_tool_calls 等限制
```
