from pathlib import Path
import subprocess
import sys

import pytest

from devagent.tools.adapters import (
    get_ci_result_as_tool_result,
    read_file_as_tool_result,
    run_shell_as_tool_result,
    search_code_as_tool_result,
    git_diff_as_tool_result,
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
        [
            sys.executable,
            "-c",
            "import sys; print('bad', file=sys.stderr); sys.exit(7)",
        ],
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


def test_git_diff_as_tool_result_success(
    git_repo_with_commit: tuple[Path, str],
):
    repo, commit_id = git_repo_with_commit

    result = git_diff_as_tool_result(commit_id, repo)

    assert result.success is True
    assert "diff --git" in result.content
    assert result.metadata["commit_id"] == commit_id
    assert result.error_code is None


def test_git_diff_as_tool_result_invalid_commit(
    git_repo_with_commit: tuple[Path, str],
):
    repo, _ = git_repo_with_commit

    result = git_diff_as_tool_result("invalid_commit_id", repo)

    assert result.success is False
    assert result.error_code == ErrorCode.COMMAND_EXECUTION_FAILED
    assert result.error_message is not None
    assert "invalid_commit_id" in result.error_message


def test_git_diff_as_tool_result_empty_commit_id(
    git_repo_with_commit: tuple[Path, str],
):
    repo, _ = git_repo_with_commit

    result = git_diff_as_tool_result(" ", repo)

    assert result.success is False
    assert result.error_code == ErrorCode.INVALID_PARAMETER


def test_git_diff_as_tool_result_missing_workspace(tmp_path: Path):
    result = git_diff_as_tool_result("commit_id", tmp_path / "missing")

    assert result.success is False
    assert result.error_code == ErrorCode.WORKSPACE_NOT_FOUND


def test_git_diff_as_tool_result_non_git_workspace(tmp_path: Path):
    result = git_diff_as_tool_result("HEAD", tmp_path)

    assert result.success is False
    assert result.error_code == ErrorCode.COMMAND_EXECUTION_FAILED


def test_git_diff_as_tool_result_maps_command_not_found(tmp_path: Path, monkeypatch):
    def raise_command_not_found(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(
        "devagent.tools.git_tools.subprocess.run",
        raise_command_not_found,
    )

    result = git_diff_as_tool_result("HEAD", tmp_path)

    assert result.success is False
    assert result.error_code == ErrorCode.COMMAND_NOT_FOUND


def test_git_diff_as_tool_result_maps_timeout(tmp_path: Path, monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["git", "show"], timeout=0.01)

    monkeypatch.setattr("devagent.tools.git_tools.subprocess.run", raise_timeout)

    result = git_diff_as_tool_result("HEAD", tmp_path, timeout=0.01)

    assert result.success is False
    assert result.error_code == ErrorCode.COMMAND_TIMEOUT


def test_git_diff_as_tool_result_maps_permission_error(tmp_path: Path, monkeypatch):
    def raise_permission_error(*args, **kwargs):
        raise PermissionError("git")

    monkeypatch.setattr(
        "devagent.tools.git_tools.subprocess.run",
        raise_permission_error,
    )

    result = git_diff_as_tool_result("HEAD", tmp_path)

    assert result.success is False
    assert result.error_code == ErrorCode.PERMISSION_DENIED


def test_get_ci_result_as_tool_result_success():
    result = get_ci_result_as_tool_result("abc123")

    assert result.success is True
    assert "test_large_upload_uses_dynamic_timeout" in result.content
    assert result.metadata["commit_id"] == "abc123"
    assert result.metadata["max_log_chars"] == 4_000


@pytest.mark.parametrize(
    ("commit_id", "data_dir", "max_log_chars", "error_code"),
    [
        ("invalid", ".", 4_000, ErrorCode.INVALID_PARAMETER),
        ("abcdef", "missing", 4_000, ErrorCode.WORKSPACE_NOT_FOUND),
        ("ffffff", "examples/sample_ci", 4_000, ErrorCode.FILE_NOT_FOUND),
        ("abc123", "examples/sample_ci", 0, ErrorCode.INVALID_PARAMETER),
    ],
)
def test_get_ci_result_as_tool_result_maps_errors(
    commit_id: str,
    data_dir: str,
    max_log_chars: int,
    error_code: ErrorCode,
):
    result = get_ci_result_as_tool_result(commit_id, data_dir, max_log_chars)

    assert result.success is False
    assert result.content == ""
    assert result.error_code == error_code
    assert result.error_message is not None


def test_get_ci_result_as_tool_result_maps_permission_error(
    tmp_path: Path,
    monkeypatch,
):
    (tmp_path / "abcdef.json").write_text("{}", encoding="utf-8")

    def raise_permission_error(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", raise_permission_error)

    result = get_ci_result_as_tool_result("abcdef", tmp_path)

    assert result.success is False
    assert result.error_code == ErrorCode.PERMISSION_DENIED


def test_get_ci_result_as_tool_result_maps_result_path_directory(tmp_path: Path):
    (tmp_path / "abcdef.json").mkdir()

    result = get_ci_result_as_tool_result("abcdef", tmp_path)

    assert result.success is False
    assert result.error_code == ErrorCode.NOT_A_FILE
