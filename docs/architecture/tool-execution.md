# Agent 工具执行与权限恢复

## 目标

Agent 的所有工具调用必须经过同一条后端执行链。LLM 只能提出工具调用，
不能绕过风险分类、命令防护或权限审批直接调用 `ToolRegistry`。

```text
AgentRuntime
  -> ToolExecutor
  -> CommandGuard / PermissionPolicyStore / PermissionManager
  -> ToolRegistry
  -> ToolResult
```

这条链路同时承担三个工程目标：

1. HIGH / CRITICAL 工具在没有允许策略时进入 `WAITING_PERMISSION`。
2. 工具执行结果始终以 `ToolResult` 写回 LLM messages。
3. Runtime、工具和权限事件共享 task_id、EventBus 和 sequence allocator。

## 低风险工具

LOW / MEDIUM 工具由 `ToolExecutor` 直接执行。即使不需要审批，也必须经过
Executor，以便统一产生 `ToolCallStarted` 和 `ToolCallFinished` 或
`ToolCallFailed` 事件。

```text
LLM tool call
  -> ToolExecutor.execute
  -> ToolRegistry.execute
  -> ToolResult
  -> Runtime messages
```

## 高风险工具暂停与恢复

高风险工具没有匹配策略时，`ToolExecutor` 创建 `PermissionRequest`，但不执行
工具。Runtime 使用生成器 checkpoint 保留 messages、step、工具预算、重复调用
签名和当前 tool call，然后返回 `AgentRunStatus.WAITING_PERMISSION`。

```text
RUNNING
  -> ToolCallStarted
  -> PermissionRequested
  -> WAITING_PERMISSION
```

Permission API 处理请求后，TaskManager 使用同一个 `permission_request_id` 恢复
暂停的 Runtime：

```text
PermissionResolved
  -> ToolExecutor.resume
  -> ToolCallFinished / ToolCallFailed
  -> ToolResult 写回 messages
  -> Agent Loop 继续
```

批准只对原始 task_id、tool_call_id、工具名和参数生效。请求不能跨任务恢复，也
不能重复消费。`run_shell` 在真正恢复执行前再次经过 `CommandGuard`，防止审批
与执行之间安全条件发生变化。

拒绝不会抛出原始工具异常，也不会执行工具。Executor 返回
`PERMISSION_DENIED` ToolResult，Runtime 把拒绝结果交给 LLM，使 Agent 可以解释
降级结果或结束任务。

## 依赖共享边界

API 组合层为 TaskManager、ToolExecutor 和 Permission API 提供同一组实例：

```text
InMemoryEventBus
InMemorySequenceAllocator
InMemoryPermissionManager
InMemoryPermissionPolicyStore
```

不能在 Permission 路由中单独创建 PermissionManager，否则浏览器审批的请求与
Runtime 等待的请求不属于同一个存储，任务无法恢复。

## 失败与安全边界

- 未处理的 PermissionRequest 不能恢复工具。
- request 的 task_id 或 tool_call_id 与暂停点不一致时拒绝恢复。
- 同一 PermissionRequest 最多恢复一次工具调用。
- Guard 或策略拒绝产生结构化 ToolResult 和 ToolCallFailed 事件。
- EventBus 订阅者异常不改变工具执行结果。
- 当前 checkpoint 保存在进程内；跨进程恢复需要后续持久化任务保存 Runtime
  状态或可重建 checkpoint。

## 验证指标

```text
HIGH / CRITICAL 未审批执行率：0%
审批前工具执行次数：0
单次批准后的工具执行次数：1
跨任务 PermissionRequest 恢复拦截率：100%
工具与权限事件 sequence_id 单调递增率：100%
批准和拒绝路径均能形成终态任务：100%
```

## 面试说明

为什么不能只把高风险工具从 tools schema 中移除？

```text
移除只能禁用能力，不能形成用户可控的审批闭环。统一 Executor 既保留能力，
又把风险判断、暂停、审计和恢复放在确定性的后端状态机中。
```

为什么恢复时不重新调用前一轮 LLM？

```text
重新调用可能生成不同参数、重复计费或重复执行其他工具。checkpoint 保留原始
tool call 和上下文，审批只决定这一次确定调用是否继续。
```
