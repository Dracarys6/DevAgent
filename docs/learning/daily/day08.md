# Day 8：BaseTool 与 ToolRegistry 开发指引

## 今天目标

把已经实现的三个底层工具接入统一工具系统，使 Agent 后续可以只通过工具名称和字典参数调用工具。

今天完成后的调用方式应该类似：

```python
registry = create_builtin_registry()

result = registry.execute(
    name="read_file",
    arguments={
        "file_path": "plan.md",
        "start_line": 1,
        "end_line": 20,
        "workspace": ".",
    },
)
```

调用方不需要知道：

```text
read_file 函数保存在哪个文件
参数应该如何转换成 Path
底层函数会抛出什么异常
不同工具底层返回值有什么区别
```

调用方只处理统一的 `ToolResult`。

---

## 1. 当前已有能力

目前已有：

```text
src/devagent/tools/file_tools.py
  底层文件读取逻辑

src/devagent/tools/search_tools.py
  底层代码搜索逻辑

src/devagent/tools/run_shell_tools.py
  底层命令执行逻辑

src/devagent/tools/adapters.py
  将底层结果转换成 ToolResult

src/devagent/tools/models.py
  ErrorCode 和 ToolResult

src/devagent/tools/base.py
  BaseTool 初步骨架

src/devagent/tools/registry.py
  当前为空，今天需要实现
```

今天不要重写底层工具。今天的任务是为已有能力建立统一调用协议。

---

## 2. 为什么三个底层工具不要合并

不建议把下面三个文件合并：

```text
file_tools.py
search_tools.py
run_shell_tools.py
```

原因：

```text
1. 三个模块职责不同。
2. 三个模块的错误类型和依赖不同。
3. run_shell 属于高风险能力，后续会接入权限审批和 CommandGuard。
4. search_code 后续可能扩展 glob、排除目录、符号搜索和混合检索。
5. file_tools 后续可能增加文件大小、二进制文件和编码检测。
6. 分开后，测试和代码定位更简单。
```

可以合并的是薄包装层：

```text
src/devagent/tools/builtin.py
```

这个文件可以集中放：

```text
ReadFileTool
SearchCodeTool
RunShellTool
create_builtin_registry
```

因为这些类只负责声明参数模型、工具描述，并调用现有 adapter。

推荐结构：

```text
tools/
  models.py             ToolResult、ErrorCode、RiskLevel
  base.py               BaseTool
  registry.py           ToolRegistry
  builtin.py            三个内置 Tool 包装类和默认注册函数
  adapters.py           底层结果 -> ToolResult
  file_tools.py         底层读取文件
  search_tools.py       底层代码搜索
  run_shell_tools.py    底层命令执行
```

---

## 3. 今天的设计原则

### 3.1 各层职责

```text
底层工具函数：
只完成具体功能。

adapter：
把底层返回值和异常转换成 ToolResult。

BaseTool：
定义所有工具必须遵守的协议。

具体 Tool 类：
定义名称、描述、参数模型、风险等级，并调用 adapter。

ToolRegistry：
按名称注册、查询和执行工具。
```

调用链：

```text
ToolRegistry.execute("read_file", raw_arguments)
  -> ReadFileTool.invoke(raw_arguments)
  -> ReadFileArgs.model_validate(raw_arguments)
  -> ReadFileTool.execute(validated_args)
  -> read_file_as_tool_result(...)
  -> ToolResult
```

### 3.2 参数校验放在哪里

推荐让 `BaseTool.invoke()` 负责统一参数校验。

原因：

```text
每个工具都需要参数校验。
如果在 Registry 中校验，Registry 会知道太多工具执行细节。
如果每个具体 Tool 自己校验，会产生重复代码。
```

因此：

```text
ToolRegistry：负责找到工具。
BaseTool.invoke：负责校验参数并调用 execute。
具体 Tool.execute：只接收校验后的 Pydantic 参数对象。
```

---

## 4. 第一步：完善 models.py

文件：

```text
src/devagent/tools/models.py
```

### 4.1 增加 RiskLevel

建议使用继承 `str` 的 Enum，便于 JSON 序列化：

```python
class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
```

三个工具的风险等级：

```text
read_file：LOW
search_code：LOW
run_shell：HIGH
```

### 4.2 补充工具系统错误码

建议增加：

```python
TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
DUPLICATE_TOOL = "DUPLICATE_TOOL"
ARGUMENT_VALIDATION_ERROR = "ARGUMENT_VALIDATION_ERROR"
TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
```

使用场景：

```text
调用不存在的工具 -> TOOL_NOT_FOUND
重复注册同名工具 -> DUPLICATE_TOOL
Pydantic 参数校验失败 -> ARGUMENT_VALIDATION_ERROR
具体 Tool 出现未预期异常 -> TOOL_EXECUTION_ERROR
```

验收：

```python
assert RiskLevel.HIGH.value == "HIGH"
assert ErrorCode.TOOL_NOT_FOUND.value == "TOOL_NOT_FOUND"
```

---

## 5. 第二步：完成 BaseTool

文件：

```text
src/devagent/tools/base.py
```

建议接口：

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .models import ErrorCode, RiskLevel, ToolResult

ArgsT = TypeVar("ArgsT", bound=BaseModel)


class BaseTool(ABC, Generic[ArgsT]):
    name: str
    description: str
    args_model: type[ArgsT]
    risk_level: RiskLevel

    def invoke(self, raw_arguments: dict) -> ToolResult:
        ...

    @abstractmethod
    def execute(self, args: ArgsT) -> ToolResult:
        ...
```

### 5.1 invoke 应完成什么

```text
1. 使用 self.args_model.model_validate(raw_arguments) 校验参数。
2. 参数错误时返回 ToolResult.fail(ARGUMENT_VALIDATION_ERROR)。
3. 校验成功后调用 self.execute(args)。
4. 捕获未预期异常，返回 TOOL_EXECUTION_ERROR。
5. 不捕获 BaseException，只捕获 Exception。
```

参数校验失败时，metadata 建议保留：

```python
{
    "tool_name": self.name,
    "validation_errors": exc.errors(),
}
```

注意：

```text
Pydantic ValidationError.errors() 可能包含复杂对象。
后续写测试时需要验证它能够 model_dump(mode="json")。
```

### 5.2 增加 schema 方法

建议增加：

```python
def schema(self) -> dict:
    return {
        "name": self.name,
        "description": self.description,
        "parameters": self.args_model.model_json_schema(),
        "risk_level": self.risk_level.value,
    }
```

这个方法以后会用于：

```text
向 LLM 提供工具描述
前端展示工具能力
调试 ToolRegistry
```

今天暂时使用内部统一格式。接入真实 LLM 时，再转换成具体供应商要求的格式。

---

## 6. 第三步：实现三个内置 Tool 包装类

新建文件：

```text
src/devagent/tools/builtin.py
```

### 6.1 ReadFileArgs 与 ReadFileTool

参数模型：

```python
class ReadFileArgs(BaseModel):
    file_path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    encoding: str = "utf-8"
    max_lines: int = Field(default=200, ge=1, le=1000)
    workspace: str | None = None
```

工具类：

```python
class ReadFileTool(BaseTool[ReadFileArgs]):
    name = "read_file"
    description = "读取工作区内文本文件的指定行，并返回带行号的内容。"
    args_model = ReadFileArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: ReadFileArgs) -> ToolResult:
        return read_file_as_tool_result(**args.model_dump())
```

需要思考：

```text
end_line 小于 start_line 时，Pydantic 单字段约束无法直接发现。
当前可以交给底层 read_file 判断。
后续可以学习 model_validator 做跨字段校验。
```

### 6.2 SearchCodeArgs 与 SearchCodeTool

参数模型：

```python
class SearchCodeArgs(BaseModel):
    query: str = Field(min_length=1)
    workspace: str
    file_pattern: str | None = None
    max_chars: int = Field(default=20_000, ge=1, le=100_000)
    timeout: float = Field(default=10.0, gt=0, le=60)
```

工具类执行：

```python
return search_code_as_tool_result(**args.model_dump())
```

风险等级：

```text
LOW
```

### 6.3 RunShellArgs 与 RunShellTool

参数模型：

```python
class RunShellArgs(BaseModel):
    command: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout: float = Field(default=10.0, gt=0, le=300)
    max_chars: int = Field(default=20_000, ge=1, le=100_000)
    workspace: str | None = None
```

工具类执行：

```python
return run_shell_as_tool_result(**args.model_dump())
```

风险等级：

```text
HIGH
```

重要：

```text
今天只声明 HIGH 风险等级。
今天不实现 PermissionManager。
后续 ToolExecutor 会在执行 HIGH 工具前请求审批。
```

---

## 7. 第四步：实现 ToolRegistry

文件：

```text
src/devagent/tools/registry.py
```

建议接口：

```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        ...

    def get(self, name: str) -> BaseTool | None:
        ...

    def list(self) -> list[BaseTool]:
        ...

    def schemas(self) -> list[dict]:
        ...

    def execute(self, name: str, arguments: dict) -> ToolResult:
        ...
```

### 7.1 register

规则：

```text
工具名不能为空。
同名工具不能重复注册。
重复注册建议抛 ToolRegistryError。
```

为什么注册错误适合抛异常：

```text
重复注册通常是程序配置错误，不是 Agent 执行过程中的业务失败。
应用启动时应该尽早暴露，而不是静默覆盖旧工具。
```

### 7.2 get

推荐返回：

```python
BaseTool | None
```

不要让 `get()` 自己返回 `ToolResult`，因为它只是查询集合。

### 7.3 list

建议按工具名排序返回，保证测试和工具 Schema 顺序稳定：

```python
return sorted(self._tools.values(), key=lambda tool: tool.name)
```

### 7.4 schemas

```python
return [tool.schema() for tool in self.list()]
```

稳定排序非常重要，否则后续：

```text
测试快照不稳定
传给 LLM 的工具顺序变化
调试时结果难比较
```

### 7.5 execute

流程：

```text
1. 根据名称查询工具。
2. 工具不存在时返回 ToolResult.fail(TOOL_NOT_FOUND)。
3. 工具存在时调用 tool.invoke(arguments)。
4. Registry 不解析具体工具参数。
```

工具不存在时建议 metadata：

```python
{
    "tool_name": name,
    "available_tools": [tool.name for tool in self.list()],
}
```

---

## 8. 第五步：创建默认 Registry

在 `builtin.py` 增加：

```python
def create_builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(SearchCodeTool())
    registry.register(RunShellTool())
    return registry
```

作用：

```text
测试和 CLI 可以快速获得默认工具集合。
新增内置工具时只改一个组装位置。
ToolRegistry 本身仍不依赖任何具体工具。
```

这体现了依赖倒置：

```text
ToolRegistry 依赖 BaseTool 协议。
具体工具在应用组装阶段注入 Registry。
```

---

## 9. 第六步：编写测试

建议新建：

```text
tests/tools/test_base.py
tests/tools/test_registry.py
tests/tools/test_builtin_tools.py
```

### 9.1 BaseTool 测试

创建测试专用工具：

```python
class EchoArgs(BaseModel):
    text: str


class EchoTool(BaseTool[EchoArgs]):
    name = "echo"
    description = "返回输入文本。"
    args_model = EchoArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: EchoArgs) -> ToolResult:
        return ToolResult.ok(content=args.text)
```

测试：

```text
合法参数能够调用 execute
缺少 text 返回 ARGUMENT_VALIDATION_ERROR
错误参数类型返回 ARGUMENT_VALIDATION_ERROR
execute 出现未预期异常返回 TOOL_EXECUTION_ERROR
schema 包含 name、description、parameters、risk_level
schema 可以 JSON 序列化
```

### 9.2 Registry 测试

测试：

```text
注册工具后可以 get
重复注册同名工具会失败
list 按名称稳定排序
schemas 返回全部工具 Schema
执行存在工具成功
执行不存在工具返回 TOOL_NOT_FOUND
Registry 不直接依赖 ReadFileTool 等具体类型
```

### 9.3 内置工具测试

测试：

```text
ReadFileTool 可以读取 tmp_path 内文件
SearchCodeTool 可以搜索 tmp_path
RunShellTool 可以执行 Python 命令
ReadFileTool 和 SearchCodeTool 风险为 LOW
RunShellTool 风险为 HIGH
参数错误在进入底层函数前被 Pydantic 拦截
```

---

## 10. 推荐开发顺序

按这个顺序做，遇到问题更容易定位：

```text
1. models.py 增加 RiskLevel 和工具系统错误码
2. 完成 BaseTool.invoke 和 BaseTool.schema
3. 为 BaseTool 编写测试
4. 实现 ToolRegistry
5. 为 ToolRegistry 编写测试
6. 新建 builtin.py
7. 实现 ReadFileTool
8. 实现 SearchCodeTool
9. 实现 RunShellTool
10. 实现 create_builtin_registry
11. 编写内置工具集成测试
12. 运行完整 pytest
```

不要一次写完全部代码后再测试。建议每完成一个步骤就运行对应测试。

---

## 11. 常见错误提醒

```text
1. 不要在 ToolRegistry 中写 if name == "read_file"。
2. 不要让 Registry import 并创建所有具体工具。
3. 不要重复注册时静默覆盖旧工具。
4. 不要让每个具体 Tool 重复写参数校验 try/except。
5. 不要让 BaseTool 依赖某个具体工具。
6. 不要把 run_shell 的 HIGH 风险等级等同于已经完成权限审批。
7. 不要把 Pydantic ValidationError 的完整内部对象直接发给 LLM。
8. 不要为了文件数量少，把不同职责的底层工具合并到一个文件。
```

---

## 12. 今日验收标准

基础通过：

```text
BaseTool 可以定义工具协议
ToolRegistry 可以注册、查询和执行工具
三个内置工具可以通过 Registry 调用
```

工程通过：

```text
参数由 Pydantic 校验
重复注册被拒绝
未知工具返回 TOOL_NOT_FOUND
schemas 顺序稳定且可 JSON 序列化
所有执行结果都是 ToolResult
完整 pytest 通过
```

面试通过：

```text
能解释 ToolRegistry 解决了什么问题
能解释为什么 Registry 不应该依赖具体工具
能解释 BaseTool.invoke 与 execute 的职责区别
能解释为什么参数模型使用 Pydantic
能解释为什么三个底层工具不合并
```

---

## 13. 今日项目深挖问题

```text
Q：新增一个工具需要修改哪些地方？
A：新增参数模型和 BaseTool 实现，然后在应用组装处注册。ToolRegistry 和 AgentRuntime 不需要修改。
```

```text
Q：为什么不直接使用函数名字典，而要设计 BaseTool？
A：函数名字典只能解决名称到函数的映射。BaseTool 还统一了工具描述、参数 Schema、风险等级、参数校验和执行结果，为 LLM Tool Calling、权限审批和可观测性提供稳定协议。
```

```text
Q：为什么 ToolRegistry 不直接处理权限审批？
A：Registry 的职责是管理和调用工具。权限审批属于执行策略，后续应放在 ToolExecutor 中。这样 Registry 可以保持简单，也便于在测试或低风险场景下复用。
```

## 明天计划

Day 9 将实现 `MockLLMClient`，用固定响应稳定复现：

```text
模型请求 search_code
模型请求 read_file
模型返回 final_answer
```

---

## Day 8 实际验收记录

### 自主实现中发现的问题

```text
1. BaseTool.invoke 调用了 execute，但没有 return，合法调用会返回 None。
2. 测试在调用 invoke 前手动构造非法 Pydantic 模型，导致测试准备阶段直接失败。
3. BaseTool metadata 保存了 args_model 类对象，不利于 JSON 序列化。
4. SearchCodeArgs.file_pattern 默认值误写成 (None,)，实际是 tuple。
5. SearchCodeArgs.workspace 允许 None，但底层搜索必须指定工作区。
6. RunShellArgs.command 没有限制至少一个参数。
7. test_registry.py 和 test_builtin_tools.py 尚未覆盖实际行为。
8. ToolRegistry.list 方法名遮蔽内置 list，导致类作用域中的 list[dict] 注解解析失败。
```

### 修正内容

```text
1. BaseTool.invoke 返回 execute(args) 的 ToolResult。
2. invoke 统一捕获 Pydantic ValidationError 和未预期执行异常。
3. validation_errors 和 tool_name 作为可序列化 metadata 返回。
4. ToolRegistry 增加 ToolRegistryError、空名称检查、重复注册检查。
5. list 和 schemas 按工具名称稳定排序。
6. 完善 ReadFileArgs、SearchCodeArgs、RunShellArgs 的 Pydantic 约束。
7. 恢复 src/devagent/tools/__init__.py。
8. 补齐 BaseTool、ToolRegistry、内置工具测试。
9. 使用 from __future__ import annotations 解决 list 方法遮蔽类型注解问题。
```

### 最终验收

```text
完整测试：55 passed
代码编译：通过
git diff --check：通过
默认 Registry：read_file、run_shell、search_code
工具 Schema JSON 序列化：通过
```

### 今日最重要的理解

```text
BaseTool.invoke：
负责原始参数校验和异常保护。

具体 Tool.execute：
只处理已经通过校验的参数模型。

ToolRegistry.execute：
只根据名称找到工具并调用 invoke，不了解具体工具参数。
```
