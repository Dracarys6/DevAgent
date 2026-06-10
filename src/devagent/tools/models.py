from pydantic import BaseModel, Field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ErrorCode(str, Enum):
    READ_FILE_ERROR = "READ_FILE_ERROR"
    SEARCH_ERROR = "SEARCH_ERROR"
    COMMAND_ERROR = "COMMAND_ERROR"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    WORKSPACE_NOT_DIR = "WORKSPACE_NOT_DIR"
    PATH_OUTSIDE_WORKSPACE = "PATH_OUTSIDE_WORKSPACE"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    NOT_A_FILE = "NOT_A_FILE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    COMMAND_EXECUTION_FAILED = "COMMAND_EXECUTION_FAILED"
    EMPTY_COMMAND = "EMPTY_COMMAND"
    INVALID_COMMAND = "INVALID_COMMAND"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    DUPLICATE_TOOL = "DUPLICATE_TOOL"
    ARGUMENT_VALIDATION_ERROR = "ARGUMENT_VALIDATION_ERROR"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"


class ToolResult(BaseModel):
    success: bool
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: ErrorCode | None = None
    error_message: str | None = None

    @classmethod
    def ok(
        cls,
        content: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":  # 加引号是延迟类型解析（因为定义在类内部）
        return cls(  # cls 代表当前类本身
            success=True,
            content=content,
            metadata=metadata or {},
            error_code=None,
            error_message=None,
        )

    @classmethod
    def fail(
        cls,
        error_code: ErrorCode,
        error_message: str,
        content: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            success=False,
            content=content,
            metadata=metadata or {},
            error_code=error_code,
            error_message=error_message,
        )
