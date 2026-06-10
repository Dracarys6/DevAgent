from pathlib import Path
import sys

from devagent.tools.adapters import (
    read_file_as_tool_result,
    run_shell_as_tool_result,
    search_code_as_tool_result,
)
from devagent.tools.models import ErrorCode


def test_read_file_as_tool_result_success(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\n", encoding="utf-8")

    result = read_file_as_tool_result(file_path, start_line=2)

    assert result.success is True
    assert result.content == "2: beta"
    assert result.error_code is None
    assert result.metadata["path"] == str(file_path)


def test_read_file_as_tool_result_file_not_found(tmp_path: Path):
    file_path = tmp_path / "missing.txt"

    result = read_file_as_tool_result(file_path)

    assert result.success is False
    assert result.error_code == ErrorCode.FILE_NOT_FOUND
    assert result.error_message is not None
    assert "文件不存在" in result.error_message


def test_read_file_as_tool_result_blocks_path_outside_workspace(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    result = read_file_as_tool_result(outside, workspace=tmp_path)

    assert result.success is False
    assert result.error_code == ErrorCode.PATH_OUTSIDE_WORKSPACE


def test_read_file_as_tool_result_invalid_parameter(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    result = read_file_as_tool_result(file_path, start_line=2, end_line=1)

    assert result.success is False
    assert result.error_code == ErrorCode.INVALID_PARAMETER


def test_search_code_as_tool_result_success(tmp_path: Path):
    file_path = tmp_path / "app.py"
    file_path.write_text("needle\n", encoding="utf-8")

    result = search_code_as_tool_result("needle", tmp_path, file_pattern="*.py")

    assert result.success is True
    assert "app.py" in result.content
    assert result.metadata["query"] == "needle"


def test_search_code_as_tool_result_invalid_parameter(tmp_path: Path):
    result = search_code_as_tool_result("", tmp_path)

    assert result.success is False
    assert result.error_code == ErrorCode.INVALID_PARAMETER


def test_search_code_as_tool_result_workspace_not_found(tmp_path: Path):
    result = search_code_as_tool_result("needle", tmp_path / "missing")

    assert result.success is False
    assert result.error_code == ErrorCode.WORKSPACE_NOT_FOUND


def test_run_shell_as_tool_result_success(tmp_path: Path):
    result = run_shell_as_tool_result(
        [sys.executable, "-c", "print('hello')"],
        cwd=tmp_path,
    )

    assert result.success is True
    assert result.content == "hello\n"
    assert result.metadata["returncode"] == 0
    assert result.metadata["stdout"] == "hello\n"


def test_run_shell_as_tool_result_preserves_nonzero_returncode(tmp_path: Path):
    result = run_shell_as_tool_result(
        [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"],
        cwd=tmp_path,
    )

    assert result.success is True
    assert result.content == "bad\n"
    assert result.metadata["returncode"] == 7
    assert result.metadata["stderr"] == "bad\n"


def test_run_shell_as_tool_result_empty_command(tmp_path: Path):
    result = run_shell_as_tool_result([], cwd=tmp_path)

    assert result.success is False
    assert result.error_code == ErrorCode.EMPTY_COMMAND


def test_run_shell_as_tool_result_blocks_cwd_outside_workspace(tmp_path: Path):
    result = run_shell_as_tool_result(
        [sys.executable, "-c", "print('hello')"],
        cwd="..",
        workspace=tmp_path,
    )

    assert result.success is False
    assert result.error_code == ErrorCode.PATH_OUTSIDE_WORKSPACE
