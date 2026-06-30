from __future__ import annotations

from typing import Any

from .base import BaseTool
from .models import ToolResult, ErrorCode
from .schema import tools_to_schemas


class ToolRegistryError(Exception):
    """工具注册配置错误。"""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        注册工具，如果同名工具存在，直接抛 ToolRegistryError。
        """
        if not tool.name.strip():
            raise ToolRegistryError("工具名不能为空")
        if tool.name in self._tools:
            raise ToolRegistryError(f"工具已注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list(self) -> list[BaseTool]:
        return sorted(self._tools.values(), key=lambda tool: tool.name)

    def schemas(self) -> list[dict[str, Any]]:
        return tools_to_schemas(self.list())

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.fail(
                ErrorCode.TOOL_NOT_FOUND,
                error_message=f"未知工具:{name}",
                metadata={
                    "tool_name": name,
                    "available_tools": [tool.name for tool in self.list()],
                },
            )

        return tool.invoke(arguments)
