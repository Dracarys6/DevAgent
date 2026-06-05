# Day 3：路径安全

## 今天目标

为 `read_file` 增加 workspace 边界检查，防止 Agent 读取项目目录外的文件。

## 完成内容

```text
1. 实现 ensure_workspace_path(workspace, path)
2. 使用 Path.resolve() 解析真实路径
3. 使用 Path.is_relative_to() 判断目标路径是否在 workspace 内
4. read_file 支持 workspace 参数
5. read_file_safe 支持 workspace 参数
6. 补充 workspace 内读取、../ 路径穿越、绝对路径越界等测试
```

## 今日验收结果

```text
第一次 pytest 暴露了 2 个失败：
1. workspace 被写死为全局路径，导致 tmp_path 测试文件被误判为越界
2. workspace 写成了相对路径 Users/...，少了开头 /

修正方案：
1. 不把 workspace 写死在模块全局变量中
2. 把 workspace 作为 read_file 的可选参数
3. 普通函数测试不传 workspace
4. Agent 场景调用时必须传 workspace
```

## 关键原理

### 1. 为什么不能硬编码 workspace

```text
硬编码路径会让函数只能在一台机器、一个目录下工作。
测试时 pytest 会创建临时目录 tmp_path，如果函数强制只允许固定 workspace，正常测试文件也会被拒绝。
```

更好的设计：

```text
workspace 由调用方传入。
Agent 执行用户任务时，TaskManager 或 ToolExecutor 知道当前 workspace，然后传给工具。
```

### 2. 路径穿越是什么

路径穿越是指用户通过 `../` 跳出允许访问的目录，例如：

```text
workspace = /project
用户传入 = ../../.ssh/id_rsa
最终可能指向 /Users/xxx/.ssh/id_rsa
```

如果不检查，Agent 可能读取 SSH 密钥、系统配置、环境变量等敏感文件。

### 3. 为什么不能只用字符串判断

错误做法：

```python
if str(path).startswith(str(workspace)):
    allow()
```

问题：

```text
/project_bad 也可能 startswith /project
../ 会在字符串层面伪装在目录内
符号链接可能指向 workspace 外
```

更好的做法：

```python
root = Path(workspace).resolve()
target = (root / path).resolve()
target.is_relative_to(root)
```

### 4. resolve() 的作用

`resolve()` 会把路径规范化：

```text
处理 .
处理 ..
处理符号链接
得到绝对路径
```

所以它适合安全判断前使用。

## 今天踩到的坑

```text
1. workspace = Path("Users/dracarys/projects/DevAgent") 是相对路径，不是 /Users/...
2. 安全检查写死全局变量会破坏测试
3. read_file 的职责是读文件，workspace 安全边界应该由参数控制
4. 测试应该覆盖“允许”和“拒绝”两种路径
```

## 面试问题

```text
Q：如果用户传入 ../../.ssh/id_rsa，你怎么防止 Agent 读取？
A：我会为每个任务传入 workspace 根目录，工具执行前先把 workspace 和用户传入路径都 resolve 成绝对路径。如果目标路径不在 workspace 内，就拒绝执行。不能只做字符串 startswith 判断，因为 ../、相似前缀目录和符号链接都可能绕过。
```

```text
Q：为什么 workspace 不应该写死在工具模块里？
A：因为同一个 Agent 平台可能同时服务多个用户、多个项目、多个 session。workspace 是任务上下文的一部分，应该由 TaskManager 或 ToolExecutor 在调用工具时传入。写死路径会导致工具不可复用，也难以测试。
```

```text
Q：路径安全检查应该发生在 Agent 调用 LLM 前还是工具执行前？
A：必须发生在工具执行前。LLM 的输出不可信，任何工具参数都要经过后端校验。即使 Prompt 要求模型不要越权，也不能依赖模型自觉。
```

## 明天计划

```text
进入 Day 4：实现 search_code
1. 学习 subprocess.run
2. 学习 rg 基础用法
3. 实现 search_code(query, workspace, file_pattern=None)
4. 限制搜索范围在 workspace 内
5. 限制输出长度
6. 补 pytest 测试
```
