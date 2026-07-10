from typing import Any, Protocol

from pydantic import BaseModel

from devagent.tools.models import RiskLevel


class ToolSchemaSource(Protocol):
    """描述 schema 转换所需的最小工具接口。

    使用协议可以避免该模块反向导入 ``BaseTool`` 而产生循环依赖。
    """

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
