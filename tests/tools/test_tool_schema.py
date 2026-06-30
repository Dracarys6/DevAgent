from pydantic import BaseModel, Field

from devagent.tools.base import BaseTool
from devagent.tools.builtin import create_builtin_registry
from devagent.tools.models import RiskLevel, ToolResult
from devagent.tools.schema import tool_to_schema, tools_to_schemas


class DemoArgs(BaseModel):
    query: str = Field(description="查询内容", min_length=1)
    max_results: int = Field(default=10, description="最大结果数", ge=1, le=100)


class DemoTool(BaseTool[DemoArgs]):
    name = "demo_tool"
    description = "这是一个示例工具，用于演示工具的功能。"
    args_model = DemoArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: DemoArgs) -> ToolResult:
        return ToolResult.ok(args.query)


class AlphaTool(DemoTool):
    name = "alpha"


def test_tool_to_schema_uses_pydantic_args_model():
    schema = tool_to_schema(DemoTool())

    assert schema["name"] == "demo_tool"
    assert schema["description"] == "这是一个示例工具，用于演示工具的功能。"
    assert schema["risk_level"] == RiskLevel.LOW.value
    assert schema["parameters"]["properties"]["query"]["description"] == "查询内容"
    assert (
        schema["parameters"]["properties"]["max_results"]["description"]
        == "最大结果数"
    )
    assert "query" in schema["parameters"]["required"]


def test_base_tool_schema_reuses_tool_to_schema():
    tool = DemoTool()

    assert tool.schema() == tool_to_schema(tool)


def test_tools_to_schemas_keeps_input_order():
    schemas = tools_to_schemas([DemoTool(), AlphaTool()])

    assert [schema["name"] for schema in schemas] == ["demo_tool", "alpha"]


def test_builtin_tools_export_expected_risk_levels():
    schemas = create_builtin_registry().schemas()
    risk_levels_by_name = {
        schema["name"]: schema["risk_level"]
        for schema in schemas
    }

    assert risk_levels_by_name == {
        "read_file": RiskLevel.LOW.value,
        "run_shell": RiskLevel.HIGH.value,
        "search_code": RiskLevel.LOW.value,
    }


def test_builtin_tool_schemas_include_parameters_and_description():
    schemas = create_builtin_registry().schemas()

    for schema in schemas:
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"
        assert "properties" in schema["parameters"]
