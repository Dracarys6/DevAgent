import subprocess
from collections.abc import Callable
from pathlib import Path

from .ci_tools import (
    DEFAULT_CI_DATA_DIR,
    DEFAULT_CI_LOG_CHARS,
    get_ci_result,
)
from .git_tools import (
    DEFAULT_GIT_TIMEOUT,
    MAX_GIT_COMPARE_CHARS,
    MAX_GIT_DIFF_CHARS,
    git_compare,
    git_diff,
)
from .knowledge_tools import KnowledgeRetriever, knowledge_retrieve
from .log_tools import (
    DEFAULT_LOG_DATA_DIR,
    DEFAULT_MAX_LOG_CHARS,
    DEFAULT_MAX_LOG_ENTRIES,
    search_log,
)
from .models import ErrorCode, ToolResult
from .read_file_tools import MAX_READ_LINES, read_file
from .run_shell_tools import DEFAULT_SHELL_TIMEOUT, MAX_OUTPUT_CHARS, run_shell
from .search_code_tools import DEFAULT_SEARCH_TIMEOUT, MAX_SEARCH_CHARS, search_code


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


def _git_diff_error_code(error: Exception) -> ErrorCode:
    return _error_code_from_exception(
        error,
        default=ErrorCode.GIT_DIFF_ERROR,
        message_rules=(
            ("commit_id 不能为空", ErrorCode.INVALID_PARAMETER),
            ("max_chars", ErrorCode.INVALID_PARAMETER),
            ("timeout", ErrorCode.INVALID_PARAMETER),
            ("工作区不存在", ErrorCode.WORKSPACE_NOT_FOUND),
            ("工作区不是目录", ErrorCode.WORKSPACE_NOT_DIR),
            ("未找到 git 命令", ErrorCode.COMMAND_NOT_FOUND),
            ("没有权限执行 git 命令", ErrorCode.PERMISSION_DENIED),
            ("执行超时", ErrorCode.COMMAND_TIMEOUT),
            ("工作区不是 Git 仓库", ErrorCode.COMMAND_EXECUTION_FAILED),
            ("无法读取 Git commit", ErrorCode.COMMAND_EXECUTION_FAILED),
        ),
    )


def _ci_result_error_code(error: Exception) -> ErrorCode:
    return _error_code_from_exception(
        error,
        default=ErrorCode.CI_RESULT_ERROR,
        message_rules=(
            ("commit_id 必须", ErrorCode.INVALID_PARAMETER),
            ("max_log_chars", ErrorCode.INVALID_PARAMETER),
            ("CI 数据目录不存在", ErrorCode.WORKSPACE_NOT_FOUND),
            ("CI 数据路径不是目录", ErrorCode.WORKSPACE_NOT_DIR),
            ("未找到 commit 对应的 CI 数据文件", ErrorCode.FILE_NOT_FOUND),
            ("CI 数据路径不是文件", ErrorCode.NOT_A_FILE),
            ("CI 数据文件位于 data_dir 之外", ErrorCode.PATH_OUTSIDE_WORKSPACE),
            ("没有权限读取 CI 数据文件", ErrorCode.PERMISSION_DENIED),
        ),
    )


def _search_log_error_code(error: Exception) -> ErrorCode:
    return _error_code_from_exception(
        error,
        default=ErrorCode.LOG_SEARCH_ERROR,
        message_rules=(
            ("task_id 只能", ErrorCode.INVALID_PARAMETER),
            ("level", ErrorCode.INVALID_PARAMETER),
            ("keyword", ErrorCode.INVALID_PARAMETER),
            ("max_entries", ErrorCode.INVALID_PARAMETER),
            ("max_chars", ErrorCode.INVALID_PARAMETER),
            ("日志数据目录不存在", ErrorCode.WORKSPACE_NOT_FOUND),
            ("日志数据路径不是目录", ErrorCode.WORKSPACE_NOT_DIR),
            ("未找到 task_id 对应的日志数据文件", ErrorCode.FILE_NOT_FOUND),
            ("日志数据路径不是文件", ErrorCode.NOT_A_FILE),
            ("日志数据文件位于 data_dir 之外", ErrorCode.PATH_OUTSIDE_WORKSPACE),
            ("没有权限读取日志数据文件", ErrorCode.PERMISSION_DENIED),
        ),
    )


def _git_compare_error_code(error: Exception) -> ErrorCode:
    return _error_code_from_exception(
        error,
        default=ErrorCode.GIT_COMPARE_ERROR,
        message_rules=(
            ("base_ref 不能为空", ErrorCode.INVALID_PARAMETER),
            ("head_ref 不能为空", ErrorCode.INVALID_PARAMETER),
            ("不能相同", ErrorCode.INVALID_PARAMETER),
            ("解析到同一 commit", ErrorCode.INVALID_PARAMETER),
            ("首尾空白", ErrorCode.INVALID_PARAMETER),
            ("max_chars", ErrorCode.INVALID_PARAMETER),
            ("timeout", ErrorCode.INVALID_PARAMETER),
            ("工作区不存在", ErrorCode.WORKSPACE_NOT_FOUND),
            ("工作区不是目录", ErrorCode.WORKSPACE_NOT_DIR),
            ("未找到 git 命令", ErrorCode.COMMAND_NOT_FOUND),
            ("没有权限执行 git 命令", ErrorCode.PERMISSION_DENIED),
            ("执行超时", ErrorCode.COMMAND_TIMEOUT),
            ("工作区不是 Git 仓库", ErrorCode.COMMAND_EXECUTION_FAILED),
            ("无法解析 base_ref", ErrorCode.COMMAND_EXECUTION_FAILED),
            ("无法解析 head_ref", ErrorCode.COMMAND_EXECUTION_FAILED),
            ("没有共同祖先", ErrorCode.COMMAND_EXECUTION_FAILED),
        ),
    )


def _knowledge_retrieve_error_code(error: Exception) -> ErrorCode:
    return _error_code_from_exception(
        error,
        default=ErrorCode.KNOWLEDGE_RETRIEVAL_ERROR,
        message_rules=(
            ("query", ErrorCode.INVALID_PARAMETER),
            ("top_k", ErrorCode.INVALID_PARAMETER),
            ("工作区不存在", ErrorCode.WORKSPACE_NOT_FOUND),
            ("工作区不是目录", ErrorCode.WORKSPACE_NOT_DIR),
            ("工作区之外", ErrorCode.PATH_OUTSIDE_WORKSPACE),
            ("不是普通文件", ErrorCode.NOT_A_FILE),
            ("UTF-8", ErrorCode.READ_FILE_ERROR),
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
    # ! 适配器契约要求底层任意异常都转换成统一 ToolResult。
    except Exception as exc:  # noqa: BLE001
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
    """执行代码搜索并把异常统一转换为 ``ToolResult``。"""
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


def git_diff_as_tool_result(
    commit_id: str,
    workspace: str | Path,
    max_chars: int = MAX_GIT_DIFF_CHARS,
    timeout: float = DEFAULT_GIT_TIMEOUT,
) -> ToolResult:
    metadata = {
        "commit_id": commit_id,
        "workspace": str(workspace),
        "max_chars": max_chars,
        "timeout": timeout,
    }
    return _to_tool_result(
        action=lambda: git_diff(commit_id, workspace, max_chars, timeout),
        metadata=metadata,
        default_error_code=ErrorCode.GIT_DIFF_ERROR,
        error_message_prefix="读取 Git diff 失败",
        error_code_mapper=_git_diff_error_code,
    )


def get_ci_result_as_tool_result(
    commit_id: str,
    data_dir: str | Path = DEFAULT_CI_DATA_DIR,
    max_log_chars: int = DEFAULT_CI_LOG_CHARS,
) -> ToolResult:
    metadata = {
        "commit_id": commit_id,
        "data_dir": str(data_dir),
        "max_log_chars": max_log_chars,
    }
    return _to_tool_result(
        action=lambda: get_ci_result(commit_id, data_dir, max_log_chars),
        metadata=metadata,
        default_error_code=ErrorCode.CI_RESULT_ERROR,
        error_message_prefix="读取 CI 结果失败",
        error_code_mapper=_ci_result_error_code,
    )


def search_log_as_tool_result(
    task_id: str,
    level: str | None = None,
    keyword: str | None = None,
    data_dir: str | Path = DEFAULT_LOG_DATA_DIR,
    max_entries: int = DEFAULT_MAX_LOG_ENTRIES,
    max_chars: int = DEFAULT_MAX_LOG_CHARS,
) -> ToolResult:
    metadata = {
        "task_id": task_id,
        "level": level,
        "keyword": keyword,
        "data_dir": str(data_dir),
        "max_entries": max_entries,
        "max_chars": max_chars,
    }
    return _to_tool_result(
        action=lambda: search_log(
            task_id, level, keyword, data_dir, max_entries, max_chars
        ),
        metadata=metadata,
        default_error_code=ErrorCode.LOG_SEARCH_ERROR,
        error_message_prefix="搜索日志失败",
        error_code_mapper=_search_log_error_code,
    )


def git_compare_as_tool_result(
    base_ref: str,
    head_ref: str,
    workspace: str | Path,
    max_chars: int = MAX_GIT_COMPARE_CHARS,
    timeout: float = DEFAULT_GIT_TIMEOUT,
) -> ToolResult:
    metadata = {
        "base_ref": base_ref,
        "head_ref": head_ref,
        "workspace": str(workspace),
        "max_chars": max_chars,
        "timeout": timeout,
    }

    def action() -> str:
        result = git_compare(base_ref, head_ref, workspace, max_chars, timeout)
        metadata.update(
            {
                "base_sha": result.base_sha,
                "head_sha": result.head_sha,
                "merge_base": result.merge_base,
                "changed_file_count": len(result.changed_files),
                "hunk_count": result.hunk_count,
                "truncated": result.truncated,
                "original_patch_chars": result.original_patch_chars,
                "returned_patch_chars": result.returned_patch_chars,
            }
        )
        return result.model_dump_json()

    return _to_tool_result(
        action=action,
        metadata=metadata,
        default_error_code=ErrorCode.GIT_COMPARE_ERROR,
        error_message_prefix="比较 Git 变更失败",
        error_code_mapper=_git_compare_error_code,
    )


def knowledge_retrieve_as_tool_result(
    query: str,
    workspace: str | Path,
    top_k: int = 5,
    *,
    retriever: KnowledgeRetriever = knowledge_retrieve,
) -> ToolResult:
    metadata = {
        "query": query,
        "workspace": str(workspace),
        "top_k": top_k,
    }

    def action() -> str:
        result = retriever(query, workspace, top_k)
        metadata.update(
            {
                "total_candidates": result.total_candidates,
                "item_count": len(result.items),
                "retrieval_ms": result.retrieval_ms,
                "truncated": result.truncated,
            }
        )
        return result.model_dump_json()

    return _to_tool_result(
        action=action,
        metadata=metadata,
        default_error_code=ErrorCode.KNOWLEDGE_RETRIEVAL_ERROR,
        error_message_prefix="检索工作区知识失败",
        error_code_mapper=_knowledge_retrieve_error_code,
    )
