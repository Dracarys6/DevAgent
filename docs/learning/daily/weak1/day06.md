# Day 6：ToolResult 与错误模型

## 今天目标

定义统一 `ToolResult`，并为 `read_file`、`search_code`、`run_shell` 提供适配层，让 Agent 后续只处理一种工具结果结构。

## 完成内容

```text
1. 在 src/devagent/tools/models.py 定义 ErrorCode
2. 在 src/devagent/tools/models.py 定义 ToolResult
3. 实现 ToolResult.ok() 和 ToolResult.fail()
4. 在 src/devagent/tools/adapters.py 实现 read_file_as_tool_result
5. 实现 search_code_as_tool_result
6. 实现 run_shell_as_tool_result
7. 为三个 adapter 补充成功和失败测试
8. 验证 ToolResult 可以 JSON 序列化
```

## 今日验收结果

```text
完整测试：34 passed
代码编译：通过
JSON 序列化：通过
```

## 关键设计

### 1. 底层结果和统一工具结果分层

底层工具保持自己的自然返回值：

```text
read_file -> str
search_code -> str
run_shell -> RunShellResult
```

Agent 层统一处理：

```text
read_file_as_tool_result -> ToolResult
search_code_as_tool_result -> ToolResult
run_shell_as_tool_result -> ToolResult
```

这样底层工具更容易测试，Agent 也不用关心每个工具的细节。

### 2. 为什么不让 read_file 直接返回 ToolResult

```text
read_file 的职责是读取文件。
ToolResult 的职责是把工具结果包装成 Agent 可理解的统一协议。
```

如果底层函数直接返回 ToolResult，会让简单工具变复杂，也会破坏已有单元测试。

### 3. 错误码映射如何优化

一开始有三个函数：

```text
_read_file_error_code
_search_code_error_code
_run_shell_error_code
```

它们会重复判断：

```text
FileNotFoundError
PermissionError
UnicodeDecodeError
TimeoutExpired
中文错误信息
默认错误码
```

现在抽成通用函数：

```text
_error_code_from_exception(error, default, message_rules)
```

每个工具只提供自己的默认错误码和少量 message_rules。

### 4. run_shell 的 success 如何理解

`run_shell_as_tool_result` 中，命令返回非零退出码时仍然是：

```text
ToolResult.success = True
metadata.returncode != 0
```

原因：

```text
Shell 程序已经成功启动并执行完成。
returncode 是命令业务结果，不是工具执行层错误。
```

例如 `pytest` 发现测试失败时，Agent 需要看到 stdout、stderr、returncode，然后继续分析和修复。

## 今日踩坑

```text
1. if "query" or "必须大于" in message 永远为 True
2. except () 不会捕获任何异常
3. error_code 不能传函数本身，必须传 ErrorCode 枚举值
4. 三个错误码映射函数会快速重复，需要抽公共逻辑
5. ToolResult.content 需要保持 str，复杂结构放 metadata
```

## 面试问题

```text
Q：为什么要设计 ToolResult？
A：因为 Agent 会调用多种工具，不同工具的底层返回值不同。如果没有统一结构，AgentRuntime 和 ToolRegistry 就要为每个工具写特殊逻辑。ToolResult 统一了 success、content、metadata、error_code 和 error_message，让工具调用、错误恢复、事件记录和 API 返回都更稳定。
```

```text
Q：为什么错误码比中文错误信息更重要？
A：中文错误信息适合人阅读，但程序不应该解析中文字符串做判断。错误码稳定、机器可读，Agent 或上层系统可以根据 FILE_NOT_FOUND、COMMAND_TIMEOUT 等错误码决定下一步恢复策略。
```

```text
Q：为什么命令非零退出码不等于 ToolResult 失败？
A：非零退出码说明命令业务失败，但工具本身成功完成了执行并拿到了 stdout、stderr 和 returncode。比如 pytest 返回 1 表示测试失败，Agent 应该基于这些信息继续修复，而不是把它当作工具执行异常丢掉。
```

## 明天计划

进入 Day 7：工具适配层与统一调用入口。

```text
1. 检查 read_file、search_code、run_shell 的 adapter 是否完整
2. 删除正式模块中的旧练习实现
3. 画底层工具 -> adapter -> ToolResult 调用图
4. 为后续 BaseTool / ToolRegistry 做准备
```
