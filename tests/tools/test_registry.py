import pytest
from pydantic import BaseModel

from devagent.tools.base import BaseTool
from devagent.tools.models import ErrorCode, RiskLevel, ToolResult
from devagent.tools.registry import ToolRegistry, ToolRegistryError


class EchoArgs(BaseModel):
    text: str


class EchoTool(BaseTool[EchoArgs]):
    name = "echo"
    description = "返回输入文本。"
    args_model = EchoArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: EchoArgs) -> ToolResult:
        return ToolResult.ok(args.text)


class AlphaTool(EchoTool):
    name = "alpha"


class EmptyNameTool(EchoTool):
    name = " "


def test_registry_register_and_get():
    registry = ToolRegistry()
    tool = EchoTool()

    registry.register(tool)

    assert registry.get("echo") is tool
    assert registry.get("missing") is None


def test_registry_rejects_duplicate_name():
    registry = ToolRegistry()
    registry.register(EchoTool())

    with pytest.raises(ToolRegistryError, match="工具已注册"):
        registry.register(EchoTool())


def test_registry_rejects_empty_name():
    registry = ToolRegistry()

    with pytest.raises(ToolRegistryError, match="工具名不能为空"):
        registry.register(EmptyNameTool())


def test_registry_list_is_sorted_by_name():
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(AlphaTool())

    assert [tool.name for tool in registry.list()] == ["alpha", "echo"]


def test_registry_schemas_are_sorted():
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(AlphaTool())

    assert [schema["name"] for schema in registry.schemas()] == ["alpha", "echo"]
    assert [schema["risk_level"] for schema in registry.schemas()] == [
        RiskLevel.LOW.value,
        RiskLevel.LOW.value,
    ]
    assert [schema["description"] for schema in registry.schemas()] == [
        "返回输入文本。",
        "返回输入文本。",
    ]
    assert [
        schema["parameters"]["properties"]["text"]["title"]
        for schema in registry.schemas()
    ] == [
        "Text",
        "Text",
    ]


def test_registry_execute_existing_tool():
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = registry.execute("echo", {"text": "hello"})

    assert result.success is True
    assert result.content == "hello"


def test_registry_execute_unknown_tool():
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = registry.execute("missing", {})

    assert result.success is False
    assert result.error_code == ErrorCode.TOOL_NOT_FOUND
    assert result.metadata == {
        "tool_name": "missing",
        "available_tools": ["echo"],
    }


def test_registry_execute_invalid_arguments():
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = registry.execute("echo", {})

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR
