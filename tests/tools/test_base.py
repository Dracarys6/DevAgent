import json

from pydantic import BaseModel

from devagent.tools.base import BaseTool
from devagent.tools.models import ErrorCode, RiskLevel, ToolResult


class EchoArgs(BaseModel):
    text: str


class EchoTool(BaseTool[EchoArgs]):
    name = "echo"
    description = "返回输入文本。"
    args_model = EchoArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: EchoArgs) -> ToolResult:
        return ToolResult.ok(content=args.text)


class BrokenTool(EchoTool):
    name = "broken"

    def execute(self, args: EchoArgs) -> ToolResult:
        raise RuntimeError("unexpected")


def test_base_tool_invoke_valid_arguments():
    result = EchoTool().invoke({"text": "hello"})

    assert result.success is True
    assert result.content == "hello"


def test_base_tool_invoke_missing_argument():
    result = EchoTool().invoke({})

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR
    assert result.metadata["tool_name"] == "echo"
    assert result.metadata["validation_errors"]


def test_base_tool_invoke_wrong_argument_type():
    result = EchoTool().invoke({"text": 123})

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR


def test_base_tool_invoke_handles_unexpected_error():
    result = BrokenTool().invoke({"text": "hello"})

    assert result.success is False
    assert result.error_code == ErrorCode.TOOL_EXECUTION_ERROR
    assert "unexpected" in result.error_message


def test_base_tool_schema_is_json_serializable():
    schema = EchoTool().schema()

    assert schema["name"] == "echo"
    assert schema["description"] == "返回输入文本。"
    assert schema["risk_level"] == "LOW"
    assert schema["parameters"]["properties"]["text"]["type"] == "string"
    json.dumps(schema)


def test_validation_failure_tool_result_is_json_serializable():
    result = EchoTool().invoke({})

    json.dumps(result.model_dump(mode="json"))
