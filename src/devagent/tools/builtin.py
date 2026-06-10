from pydantic import BaseModel, Field
from .base import BaseTool
from .models import RiskLevel, ToolResult
from .adapters import (
    read_file_as_tool_result,
    search_code_as_tool_result,
    run_shell_as_tool_result,
)
from .registry import ToolRegistry


class ReadFileArgs(BaseModel):
    file_path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    encoding: str = "utf-8"
    max_lines: int = Field(default=200, ge=1, le=1000)
    workspace: str | None = None


class ReadFileTool(BaseTool[ReadFileArgs]):
    name = "read_file"
    description = "读取工作区内文本文件的指定行，并返回带行号的内容。"
    args_model = ReadFileArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: ReadFileArgs) -> ToolResult:
        return read_file_as_tool_result(**args.model_dump())


class SearchCodeArgs(BaseModel):
    query: str = Field(min_length=1)
    workspace: str
    file_pattern: str | None = None
    max_chars: int = Field(default=20_000, ge=1, le=100_000)
    timeout: float = Field(default=10.0, gt=0, le=60)


class SearchCodeTool(BaseTool[SearchCodeArgs]):
    name = "search_code"
    description = "在工作区内搜索指定代码文本，并返回匹配结果。"
    args_model = SearchCodeArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: SearchCodeArgs) -> ToolResult:
        return search_code_as_tool_result(**args.model_dump())


class RunShellArgs(BaseModel):
    command: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout: float = Field(default=10.0, gt=0, le=300)
    max_chars: int = Field(default=20_000, ge=1, le=100_000)
    workspace: str | None = None


class RunShellTool(BaseTool[RunShellArgs]):
    name = "run_shell"
    description = "在指定工作目录执行 Shell 命令，并返回输出与退出状态。"
    args_model = RunShellArgs
    risk_level = RiskLevel.HIGH

    def execute(self, args: RunShellArgs) -> ToolResult:
        return run_shell_as_tool_result(**args.model_dump())


def create_builtin_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(SearchCodeTool())
    registry.register(RunShellTool())
    return registry
