# Day 9：MockLLMClient 与统一 LLM 协议

## 今天目标

实现稳定、离线、可重复的 Mock LLM，为 Day 10 Agent Loop 提供确定性测试环境。

## 完成内容

```text
1. 在 src/devagent/llm/models.py 定义 ToolCall、LLMResponseType、LLMResponse
2. 在 src/devagent/llm/base.py 定义 LLMClient Protocol
3. 在 src/devagent/llm/mock_client.py 实现 MockLLMClient
4. 默认响应依次返回 search_code、read_file、final_answer
5. Mock 支持自定义响应序列
6. Mock 记录每次收到的 messages 深拷贝
7. 响应序列耗尽后重复最后一个响应
8. 增加响应结构校验和 JSON 序列化测试
```

## 验收中发现的问题

### 1. 通用模型不应定义在 Mock 实现中

原始实现把 `ToolCall` 和 `LLMResponse` 放在 `mock_client.py`。

问题：

```text
真实 LLM Client 和 AgentRuntime 后续会依赖 Mock 模块。
通用协议与测试实现耦合。
```

修正：

```text
llm/models.py：通用数据协议
llm/base.py：客户端行为协议
llm/mock_client.py：Mock 实现
```

### 2. Mock 必须记录请求

仅返回固定响应无法验证 Agent Loop 是否把工具结果写回上下文。

现在通过：

```python
client.requests
```

保存每次收到的 messages 深拷贝。Day 10 可以断言第二、第三次请求是否包含 tool message。

### 3. `responses or default` 无法区分 None 与空列表

错误写法：

```python
self._responses = responses or default_mock_responses()
```

空列表也会使用默认响应，导致非法配置被静默接受。

修正：

```python
self._responses = default_mock_responses() if responses is None else responses
```

### 4. Mock 中的工具参数必须真实可执行

原始第二次调用读取：

```text
models.py
```

以项目根目录作为 workspace 时，该文件不存在。

修正为：

```text
src/devagent/tools/models.py
```

这样 Day 10 Agent Loop 可以真正执行默认 Mock 返回的工具调用。

## 关键原理

### 为什么先使用 Mock LLM

```text
真实模型输出不稳定，测试结果难复现。
真实 API 需要网络和密钥。
真实 API 有成本、限流和延迟。
很难稳定构造 max_steps、错误恢复等边界场景。
```

Mock LLM 可以精确控制每一轮响应，从而测试 Agent Runtime 本身。

### tool_call_id 的作用

一次模型响应可能包含多个工具调用。工具结果必须携带对应的 `tool_call_id`，模型才能知道每个结果属于哪个请求。

```text
assistant tool_call id=call_001
tool result tool_call_id=call_001
```

### 为什么需要内部统一协议

不同模型供应商返回格式不同。AgentRuntime 不应该直接理解供应商格式。

```text
供应商响应
  -> 具体 LLMClient 转换
  -> 内部 LLMResponse
  -> AgentRuntime
```

后续替换模型供应商时，AgentRuntime 不需要修改。

## 最终验收

```text
完整测试：68 passed
代码编译：通过
git diff --check：通过
默认三轮响应：通过
自定义响应序列：通过
请求记录：通过
JSON 序列化：通过
MockLLMClient 符合 LLMClient Protocol：通过
```

## 项目深挖问题

```text
Q：如何测试输出不稳定的 Agent？
A：将 AgentRuntime 与真实模型解耦，通过统一 LLMClient 协议注入 MockLLMClient。Mock 按固定序列返回工具调用和最终答案，使工具调用顺序、上下文写回、max_steps 和错误恢复都可以稳定断言。
```

```text
Q：为什么不让 AgentRuntime 直接依赖 OpenAI SDK 的响应类型？
A：这样会让 Runtime 与具体供应商耦合。项目先把供应商响应转换成内部 LLMResponse，Runtime 只处理统一的 ToolCall 和 final answer，后续更换供应商时只需要新增客户端适配。
```

## 明天计划

Day 10 实现最小 `AgentRuntime`：

```text
1. 构造初始 system / user messages
2. 调用 LLMClient.chat
3. 执行 ToolCall
4. 把 assistant tool call 和 tool result 写回 messages
5. 继续循环直到 final_answer
6. 使用 MockLLMClient 稳定测试完整链路
```
