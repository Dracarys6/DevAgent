# Day 4：代码搜索工具 search_code

## 今天目标

学习 `subprocess.run` 和 ripgrep，完成只能在指定 workspace 内执行的代码搜索工具。

## 自主完成内容

```text
1. 使用 subprocess.run 调用 rg
2. 使用参数列表构造命令，没有使用 shell=True
3. 使用 cwd 限制搜索工作目录
4. 支持 file_pattern 文件过滤
5. 区分 rg 返回码 0、1 和其他错误
6. 尝试限制最大输出字符数
```

## 验收发现

第一次实现中发现的问题：

```text
1. 截断后的内容保存在 output 中，但最终返回了 result.stdout，导致截断没有生效
2. search_file 放在 study 中，没有沉淀为正式项目模块
3. 模块 import 时会立即执行搜索和 print
4. 没有校验 workspace 是否存在、是否为目录
5. 没有处理 rg 未安装和执行超时
6. 搜索词如果以 - 开头，可能被 rg 当成命令选项
7. 没有自动化测试
```

最终完善：

```text
1. 正式实现放到 src/devagent/tools/search_tools.py
2. 工具命名统一为 search_code
3. 增加 SearchCodeError
4. 增加 workspace 校验
5. 增加 timeout
6. 增加严格的输出截断
7. 使用 -- 分隔命令选项和搜索参数
8. 增加 6 个 search_code 测试
9. study/search.py 改成无 import 副作用的演示入口
```

## 今日验收结果

```text
完整测试：15 passed

search_code 已覆盖：
1. 正常搜索
2. file_pattern 过滤
3. 无结果返回空字符串
4. 输出截断
5. 非法 workspace
6. 以 - 开头的搜索词
```

## 关键原理

### 1. subprocess.run 做了什么

`subprocess.run` 用于从 Python 启动一个外部进程，并等待它执行结束。

核心参数：

```text
args：命令及参数
cwd：子进程工作目录
capture_output：捕获 stdout 和 stderr
text：把输出解码成字符串
timeout：限制执行时间
check：返回码非 0 时是否自动抛异常
```

在 `search_code` 中：

```python
result = subprocess.run(
    command,
    capture_output=True,
    text=True,
    cwd=root,
    timeout=timeout,
    check=False,
)
```

### 2. 为什么使用参数列表而不是 shell=True

推荐：

```python
subprocess.run(["rg", "--line-number", "--", query, "."])
```

不推荐：

```python
subprocess.run(f"rg {query}", shell=True)
```

原因：

```text
参数列表会直接把每个值作为程序参数传递。
shell=True 会先让 Shell 解析整条字符串。
如果 query 包含 ;、|、$() 等内容，可能造成命令注入。
```

### 3. rg 返回码

```text
0：找到了匹配内容
1：没有找到匹配内容，不属于系统错误
2 或其他值：命令参数、文件访问等执行错误
```

所以无搜索结果应该返回空字符串，而不是抛异常。

### 4. cwd 是什么

`cwd` 设置子进程的当前工作目录。

在本工具中，`rg` 从 workspace 根目录搜索：

```text
cwd = workspace
搜索路径 = .
```

注意：

```text
cwd 只是控制进程从哪里运行，不是真正的安全沙箱。
如果命令参数允许访问 ../ 或绝对路径，进程仍可能访问 workspace 外。
因此工具还必须限制可执行命令和参数。
```

### 5. 为什么使用 --

命令：

```text
rg -- -needle .
```

`--` 表示命令选项到此结束，后面的内容都作为普通位置参数处理。

没有 `--` 时，搜索词 `-needle` 可能被误认为 rg 的命令选项。

### 6. 为什么限制输出大小

Agent 工具结果最终会进入 LLM 上下文。如果搜索结果过大：

```text
1. 占用大量 token
2. 增加调用成本和延迟
3. 可能超过上下文限制
4. 大量无关结果会降低判断质量
```

所以工具层应该在结果进入 Agent 前进行截断。

### 7. 关键词检索和向量检索的区别

关键词检索：

```text
适合搜索类名、函数名、错误码、配置名等精确文本。
结果稳定、速度快、容易解释。
无法很好理解语义相近但用词不同的内容。
```

向量检索：

```text
适合自然语言和语义相似内容。
可以找到用词不同但含义相近的代码或文档。
结果具有不确定性，建立索引也需要额外成本。
```

DevAgent 第一版先使用 `rg`，后续再把关键词检索与向量检索组合成 hybrid search。

## 面试问题

```text
Q：为什么第一版代码检索选择 ripgrep，而不是直接上向量数据库？
A：研发场景中很多搜索目标是函数名、类名、错误码和配置项，关键词检索更准确、稳定、快速，也不需要提前建立索引。第一版先用 ripgrep 跑通工具调用闭环，后续再补向量检索处理语义搜索，并组合成混合检索。
```

```text
Q：subprocess 使用 shell=True 有什么风险？
A：shell=True 会让 Shell 解析命令字符串。如果字符串包含用户或 LLM 生成的内容，攻击者可能通过分号、管道或命令替换执行额外命令。更安全的方式是使用参数列表并保持 shell=False，同时对参数、cwd、timeout 和输出大小进行限制。
```

```text
Q：rg 返回码为 1 时为什么不应该当成错误？
A：对 ripgrep 来说，返回码 1 表示搜索执行成功但没有匹配内容。这是正常业务结果。只有返回码 2 或其他异常返回码才表示真正的执行错误。
```

```text
Q：仅仅设置 cwd 能保证 Agent 不访问 workspace 外吗？
A：不能。cwd 只是子进程的起始工作目录，不是安全沙箱。命令仍可能通过 ../、绝对路径或其他程序访问外部资源。因此还需要固定命令、限制参数、校验路径；高风险命令后续还要经过 PermissionManager 或 Docker Sandbox。
```

## 明天计划

进入 Day 5：Shell 执行基础。

```text
1. 实现 run_shell(command, cwd, timeout)
2. 捕获 stdout、stderr、returncode
3. 处理 TimeoutExpired
4. 限制 cwd 在 workspace 内
5. 限制输出长度
6. 先理解 shell=True 风险，暂不做完整 PermissionManager
7. 补 pytest 测试
```
