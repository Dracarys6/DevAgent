# Day 5：Shell 执行工具 run_shell

## 今天目标

使用 `subprocess.run` 实现基础 Shell 命令执行工具，捕获 `stdout`、`stderr`、`returncode`，并增加超时、工作目录限制和输出截断。

## 自主完成内容

```text
1. 创建 run_shell_tools.py
2. 使用参数列表执行命令，没有启用 shell=True
3. 使用 cwd 设置命令工作目录
4. 使用 timeout 限制执行时间
5. 捕获 stdout 和 stderr
6. 尝试处理非零返回码
7. 编写最小成功命令测试
```

## 验收发现

第一次实现中的问题：

```text
1. _resolve_workspace 失败时返回 RunShellError 对象，而不是 raise 异常
2. timeout 默认值误用了 MAX_SEARCH_CHARS，实际默认超时变成 20000 秒
3. 变量仍使用 SEARCH 命名，没有体现 Shell 工具含义
4. 返回值只有字符串，丢失了 stderr 和 returncode
5. 普通命令返回码 1 被错误当成“无搜索结果”
6. 错误信息仍写成“搜索超时”和“ripgrep 退出码”
7. 没有限制 cwd 必须位于 workspace 内
8. 没有处理命令不存在、权限不足和启动失败
9. 只有一个成功路径测试
```

实际验证：

```text
命令：sh -c "echo bad >&2; exit 1"
第一次实现返回：空字符串

问题：
stderr 和 returncode 被丢失，Agent 无法知道命令失败原因。
```

## 最终完善

```text
1. 定义 RunShellResult，保存 command、cwd、returncode、stdout、stderr
2. 增加 success 属性，returncode == 0 时为 True
3. 非零返回码不抛异常，保留真实执行结果
4. 命令无法启动、超时、cwd 越界时抛 RunShellError
5. 增加 DEFAULT_SHELL_TIMEOUT = 10.0
6. stdout 和 stderr 分别限制最大字符数
7. 支持 workspace 参数并限制 cwd 边界
8. 增加命令不存在、空命令、超时等测试
```

## 今日验收结果

```text
完整测试：23 passed
代码编译：通过
真实非零命令验证：通过
```

测试覆盖：

```text
1. 成功执行并捕获 stdout
2. 非零 returncode 和 stderr
3. 命令执行超时
4. stdout / stderr 输出截断
5. workspace 内 cwd 允许执行
6. workspace 外 cwd 拒绝执行
7. 命令不存在
8. 空命令
```

## 关键原理

### 1. stdout、stderr 和 returncode

```text
stdout：程序正常输出的数据
stderr：程序的错误或诊断信息
returncode：程序退出状态
```

通常：

```text
returncode == 0：命令执行成功
returncode != 0：命令完成了，但业务执行失败
```

非零返回码不代表 Python 无法启动命令。例如：

```bash
pytest tests/not_exists.py
```

`pytest` 程序可以正常启动，但因为测试文件不存在而返回非零退出码。工具应该把退出码和错误输出交给 Agent，由 Agent 决定下一步，而不是丢失信息。

### 2. 执行层错误和命令业务失败

执行层错误，应该抛异常：

```text
命令不存在
没有权限启动命令
cwd 不存在
cwd 位于 workspace 外
执行超时
```

命令业务失败，应该返回结果：

```text
pytest 测试失败
git diff 参数不正确
程序运行后返回退出码 1
编译器发现代码错误
```

区分这两类情况后，Agent 才能根据真实错误继续修正。

### 3. 为什么 timeout 很重要

Agent 可能生成：

```text
永不结束的程序
等待用户输入的命令
长时间运行的测试
死循环脚本
```

如果没有 timeout，Agent 任务可能永远卡住，占用进程和系统资源。

`subprocess.run(..., timeout=10)` 超时后会终止子进程并抛出 `TimeoutExpired`。

### 4. cwd 不是安全沙箱

`cwd` 只设置命令开始执行的位置，并不能阻止命令访问其他目录。

例如，即使 cwd 在项目内，命令仍可能执行：

```bash
cat ~/.ssh/id_rsa
rm -rf ../other-project
curl https://example.com
```

因此当前 Day 5 只完成了基础边界：

```text
限制命令从 workspace 内目录启动
设置 timeout
限制输出大小
不使用 shell=True 拼接字符串
```

后续还需要：

```text
PermissionManager 权限审批
危险命令检测
允许命令白名单
网络访问限制
Docker Sandbox
```

### 5. shell=True 为什么危险

危险写法：

```python
subprocess.run(f"pytest {user_input}", shell=True)
```

如果 `user_input` 是：

```text
tests/; rm -rf /
```

Shell 可能执行两条命令。

当前工具要求传入参数列表：

```python
run_shell(["pytest", "tests/"])
```

参数列表可以避免 Python 自动使用 Shell 解析整条命令字符串。

但需要注意：

```python
run_shell(["sh", "-c", "危险命令"])
```

仍然可以显式启动 Shell，所以参数列表并不等于绝对安全。高风险工具最终仍必须经过权限审批。

### 6. 为什么限制输出大小

测试、编译、日志命令可能输出几十 MB 内容。如果全部保存并放入 LLM 上下文：

```text
内存占用增加
模型调用成本增加
响应速度降低
可能超过上下文窗口
关键错误容易被大量普通日志淹没
```

所以 `stdout` 和 `stderr` 都应该截断。

## 面试问题

```text
Q：Shell 命令返回非零退出码时，为什么不直接抛异常？
A：非零退出码通常表示命令程序已经正常启动并执行完成，但业务操作失败，例如 pytest 发现测试失败。工具应该保留 stdout、stderr 和 returncode 返回给 Agent，让 Agent 根据错误信息修正；只有命令无法启动、超时或工作目录越界等执行层错误才抛异常。
```

```text
Q：如果 Agent 想执行 rm -rf /，系统应该怎么拦截？
A：首先 Shell 工具必须被定义为高风险工具，执行前经过 PermissionManager 审批；其次后端应检测并拒绝危险命令模式，限制 cwd 和可访问路径，设置 timeout 和输出上限。更高安全要求下，应放入限制网络、文件系统和资源的 Docker Sandbox 中执行。
```

```text
Q：使用参数列表并设置 shell=False 后，Shell 工具就绝对安全吗？
A：不是。参数列表可以避免字符串被隐式 Shell 解析，但 Agent 仍然可能显式执行 sh -c、python 脚本或其他危险程序，也可能访问 workspace 外文件。因此还需要权限审批、命令策略和沙箱隔离。
```

```text
Q：如何设计 Shell 工具的安全边界？
A：我会分层设计：参数列表避免隐式命令注入；workspace 限制执行目录；timeout 和输出截断限制资源消耗；PermissionManager 审批高风险调用；命令策略拦截明显危险操作；最终使用 Docker Sandbox 做文件系统、网络和资源隔离。
```

## 明天计划

进入 Day 6：ToolResult 与错误模型。

```text
1. 学习 dataclass 或 Pydantic BaseModel
2. 定义统一 ToolResult
3. 字段包含 success、content、metadata、error_code、error_message
4. 将 read_file、search_code、run_shell 结果统一包装
5. 区分工具执行失败和工具业务失败
6. 补充结构化错误测试
```
