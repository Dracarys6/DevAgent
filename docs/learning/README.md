# DevAgent 学习区规范

这个仓库同时承担两个角色：学习仓库和项目作品仓库。为了后续两个月不乱，建议按下面方式放文件。

## 目录约定

```text
src/devagent/
  正式项目源码。能被测试、后端服务、命令行 Demo 复用的代码都放这里。

tests/
  自动化测试。每写一个核心函数或类，尽量配 2 到 3 个 pytest 测试。

docs/learning/
  学习笔记、每日复盘、面试问题答案。

docs/learning/daily/
  每天一份学习记录，例如 day01.md、day02.md。

examples/
  项目演示样例，例如 mock CI、mock 日志、sample repo。

input/
  临时练习输入。可以保留，但不要让正式代码依赖这里。

study/
  纯学习草稿。可以写小实验，但不要让 tests 或正式项目依赖交互式脚本。
```

## 编码规则

```text
1. 正式模块不要在 import 时执行 input()、print()、写文件等副作用。
2. 可以执行的演示代码放到 if __name__ == "__main__": 里面。
3. 工具函数失败时不要直接崩溃，优先返回结构化错误。
4. 路径相关代码优先使用 pathlib.Path。
5. 每天至少补一个测试或一段复盘笔记。
6. 类名、函数名、变量名和参数名使用英文。
7. 面向用户的错误信息、执行提示和截断提示使用中文。
```

## 本地开发环境

首次创建虚拟环境或重新拉取项目后，在项目根目录执行：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

`python -m pip install -e .` 会把当前项目以 editable 模式安装到虚拟环境中。安装后，修改 `src/devagent` 内的源码会立即生效，不需要重复安装。

此后可以直接运行：

```bash
python study/search.py
pytest -q
```

如果没有激活虚拟环境，也可以明确使用虚拟环境中的命令：

```bash
.venv/bin/python study/search.py
.venv/bin/pytest -q
```

不要在脚本中通过修改 `sys.path` 解决导入问题。正式 Python 项目应使用打包配置和 editable install 管理源码导入。

## 每日学习记录模板

```text
# Day N：主题

## 今天目标

## 完成内容

## 关键原理

## 遇到的问题

## 面试问题

## 明天计划
```
