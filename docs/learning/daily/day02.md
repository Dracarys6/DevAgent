# Day 2：文件读取工具 read_file

## 今天目标

使用 pathlib 实现文件读取工具，并开始理解文件工具的安全边界。

## 已完成

```text
1. 使用 pathlib.Path 判断文件是否存在
2. 使用 Path.read_text 读取文本
3. 能处理文件不存在和非普通文件
```

## 需要完善

```text
1. read_file 需要支持 start_line 和 end_line
2. 返回值需要结构化，方便 Agent 理解成功和失败
3. 不能在模块 import 时 print 或写文件
4. 需要补 pytest 测试
5. 后续需要限制只能读取 workspace 内文件
```

## 面试问题

```text
Q：为什么 Agent 读取文件要限制行数？
A：因为工具结果会进入 LLM 上下文。如果一次读取过多内容，会导致上下文变长、成本升高、响应变慢，还可能淹没真正关键的信息。
```
