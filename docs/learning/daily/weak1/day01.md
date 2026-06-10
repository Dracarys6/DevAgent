# Day 1：环境与 Python 基础

## 今天目标

完成 Python 虚拟环境、依赖安装、pytest 基础测试。

## 已完成

```text
1. 创建了虚拟环境 .venv
2. 安装了 pytest、fastapi、uvicorn、pydantic
3. 编写了 add 函数练习
4. 编写了 test_add.py 测试
```

## 需要修正

```text
study/add.py 里有顶层 input()，被测试 import 时会卡住。
正式可复用代码不要在 import 时执行交互逻辑。
```

## 面试问题

```text
Q：为什么 Python 项目需要虚拟环境？
A：虚拟环境可以隔离不同项目的依赖版本，避免全局 Python 包互相污染，也方便复现项目运行环境。
```
