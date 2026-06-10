from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .models import ToolResult, ErrorCode, RiskLevel

ArgsT = TypeVar("ArgsT", bound=BaseModel)


class BaseTool(ABC, Generic[ArgsT]):
    """
    所有工具的抽象基类。

    每个工具必须提供:
    1. name: 工具名
    2. description: 工具描述
    3. args_model: Pydantic 参数模型
    4. risk_level: 风险等级
    """

    name: str
    description: str
    args_model: type[ArgsT]
    risk_level: RiskLevel

    # 校验参数并调用
    def invoke(self, raw_arguments: dict[str, Any]) -> ToolResult:
        metadata = {"tool_name": self.name}
        try:
            args = self.args_model.model_validate(raw_arguments)
            return self.execute(args)
        except ValidationError as exc:
            return ToolResult.fail(
                ErrorCode.ARGUMENT_VALIDATION_ERROR,
                error_message="工具参数校验失败",
                metadata={**metadata, "validation_errors": exc.errors()},
            )
        except Exception as exc:
            return ToolResult.fail(
                ErrorCode.TOOL_EXECUTION_ERROR,
                error_message=f"工具执行失败: {exc}",
                metadata=metadata,
            )

    @abstractmethod
    def execute(self, args: ArgsT) -> ToolResult:
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_model.model_json_schema(),
            "risk_level": self.risk_level.value,
        }
