from typing import Any, Protocol

from pydantic import BaseModel

from devagent.tools.models import RiskLevel


# 避免循环导入，定义一个协议类来表示工具的 schema 来源
class ToolSchemaSource(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]
    risk_level: RiskLevel


def tool_to_schema(tool: ToolSchemaSource) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.args_model.model_json_schema(),
        "risk_level": tool.risk_level.value,
    }


def tools_to_schemas(tools: list[ToolSchemaSource]) -> list[dict[str, Any]]:
    return [tool_to_schema(tool) for tool in tools]
