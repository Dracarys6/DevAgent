import subprocess
from pathlib import Path
from collections.abc import Callable

from .models import ErrorCode, ToolResult
from .file_tools import read_file, MAX_READ_LINES
from .search_tools import search_code, MAX_SEARCH_CHARS, DEFAULT_SEARCH_TIMEOUT
from .run_shell_tools import run_shell, MAX_OUTPUT_CHARS, DEFAULT_SHELL_TIMEOUT


def _error_code_from_exception(
    error: Exception,
    default: ErrorCode,
    message_rules: tuple[tuple[str, ErrorCode], ...] = (),
) -> ErrorCode:
    message = str(error)
    if isinstance(error, FileNotFoundError):
        return ErrorCode.FILE_NOT_FOUND
    if isinstance(error, PermissionError):
        return ErrorCode.PERMISSION_DENIED
    if isinstance(error, UnicodeDecodeError):
        return ErrorCode.READ_FILE_ERROR
    if isinstance(error, subprocess.TimeoutExpired):
        return ErrorCode.COMMAND_TIMEOUT

    for pattern, error_code in message_rules:
        if pattern in message:
            return error_code
    return default


def _read_file_error_code(error: Exception) -> ErrorCode:
    return _error_code_from_exception(
        error,
        default=ErrorCode.READ_FILE_ERROR,
        message_rules=(
            ("工作区之外", ErrorCode.PATH_OUTSIDE_WORKSPACE),
            ("普通文件", ErrorCode.NOT_A_FILE),
            ("start_line", ErrorCode.INVALID_PARAMETER),
            ("end_line", ErrorCode.INVALID_PARAMETER),
            ("max_lines", ErrorCode.INVALID_PARAMETER),
        ),
    )


def _search_code_error_code(error: Exception) -> ErrorCode:
    return _error_code_from_exception(
        error,
        default=ErrorCode.SEARCH_ERROR,
        message_rules=(
            ("query", ErrorCode.INVALID_PARAMETER),
            ("max_chars", ErrorCode.INVALID_PARAMETER),
            ("timeout", ErrorCode.INVALID_PARAMETER),
            ("工作区不存在", ErrorCode.WORKSPACE_NOT_FOUND),
            ("工作区不是目录", ErrorCode.WORKSPACE_NOT_DIR),
            ("未找到 rg", ErrorCode.COMMAND_NOT_FOUND),
            ("超时", ErrorCode.COMMAND_TIMEOUT),
        ),
    )


def _run_shell_error_code(error: Exception) -> ErrorCode:
    return _error_code_from_exception(
        error,
        default=ErrorCode.COMMAND_ERROR,
        message_rules=(
            ("command 命令不能为空", ErrorCode.EMPTY_COMMAND),
            ("每个参数都必须是字符串", ErrorCode.INVALID_COMMAND),
            ("timeout", ErrorCode.INVALID_PARAMETER),
            ("max_chars", ErrorCode.INVALID_PARAMETER),
            ("工作区不存在", ErrorCode.WORKSPACE_NOT_FOUND),
            ("工作区不是目录", ErrorCode.WORKSPACE_NOT_DIR),
            ("工作区之外", ErrorCode.PATH_OUTSIDE_WORKSPACE),
            ("工作目录不存在", ErrorCode.FILE_NOT_FOUND),
            ("工作目录不是目录", ErrorCode.NOT_A_FILE),
            ("未找到命令", ErrorCode.COMMAND_NOT_FOUND),
            ("执行超时", ErrorCode.COMMAND_TIMEOUT),
        ),
    )


def _to_tool_result(
    action: Callable[[], str],
    metadata: dict,
    default_error_code: ErrorCode,
    error_message_prefix: str,
    error_code_mapper: Callable[[Exception], ErrorCode] | None = None,
) -> ToolResult:
    try:
        return ToolResult.ok(content=action(), metadata=metadata)
    except Exception as exc:
        mapper = error_code_mapper or (
            lambda error: _error_code_from_exception(error, default_error_code)
        )
        return ToolResult.fail(
            error_code=mapper(exc),
            error_message=f"{error_message_prefix}: {exc}",
            metadata=metadata,
        )


def read_file_as_tool_result(
    file_path: str | Path,
    start_line: int = 1,
    end_line: int | None = None,
    encoding: str = "utf-8",
    max_lines: int = MAX_READ_LINES,
    workspace: str | Path | None = None,
) -> ToolResult:
    metadata = {
        "path": str(file_path),
        "start_line": start_line,
        "end_line": end_line,
        "encoding": encoding,
        "max_lines": max_lines,
        "workspace": str(workspace) if workspace is not None else None,
    }
    return _to_tool_result(
        action=lambda: read_file(
            file_path,
            start_line=start_line,
            end_line=end_line,
            encoding=encoding,
            max_lines=max_lines,
            workspace=workspace,
        ),
        metadata=metadata,
        default_error_code=ErrorCode.READ_FILE_ERROR,
        error_message_prefix="读取文件失败",
        error_code_mapper=_read_file_error_code,
    )


def search_code_as_tool_result(
    query: str,
    workspace: str | Path,
    file_pattern: str | None = None,
    max_chars: int = MAX_SEARCH_CHARS,
    timeout: float = DEFAULT_SEARCH_TIMEOUT,
) -> ToolResult:
    """"""
    metadata = {
        "query": query,
        "workspace": str(workspace),
        "file_pattern": file_pattern,
        "max_chars": max_chars,
        "timeout": timeout,
    }
    return _to_tool_result(
        action=lambda: search_code(query, workspace, file_pattern, max_chars, timeout),
        metadata=metadata,
        default_error_code=ErrorCode.SEARCH_ERROR,
        error_message_prefix="搜索代码失败",
        error_code_mapper=_search_code_error_code,
    )


def run_shell_as_tool_result(
    command: list[str],
    cwd: str | Path = ".",
    timeout: float = DEFAULT_SHELL_TIMEOUT,
    max_chars: int = MAX_OUTPUT_CHARS,
    workspace: str | Path | None = None,
) -> ToolResult:
    metadata = {
        "command": command,
        "cwd": str(cwd),
        "timeout": timeout,
        "max_chars": max_chars,
        "workspace": str(workspace) if workspace is not None else None,
    }

    def action() -> str:
        result = run_shell(command, cwd, timeout, max_chars, workspace)
        metadata.update(
            {
                "resolved_cwd": result.cwd,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        content = result.stdout if result.stdout else result.stderr
        return content

    return _to_tool_result(
        action=action,
        metadata=metadata,
        default_error_code=ErrorCode.COMMAND_ERROR,
        error_message_prefix="执行命令失败",
        error_code_mapper=_run_shell_error_code,
    )
