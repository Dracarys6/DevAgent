import sys
from pathlib import Path

import pytest

from devagent.tools.run_shell_tools import RunShellError, run_shell


def python_command(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_shell_success_captures_output_and_returncode(tmp_path: Path):
    result = run_shell(python_command("print('hello')"), cwd=tmp_path)

    assert result.success is True
    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""


def test_run_shell_nonzero_returncode_is_preserved(tmp_path: Path):
    result = run_shell(
        python_command("import sys; print('bad', file=sys.stderr); sys.exit(3)"),
        cwd=tmp_path,
    )

    assert result.success is False
    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr == "bad\n"


def test_run_shell_times_out(tmp_path: Path):
    with pytest.raises(RunShellError, match="命令执行超时"):
        run_shell(
            python_command("import time; time.sleep(1)"),
            cwd=tmp_path,
            timeout=0.01,
        )


def test_run_shell_truncates_stdout_and_stderr(tmp_path: Path):
    result = run_shell(
        python_command(
            "import sys; print('a' * 100); print('b' * 100, file=sys.stderr)"
        ),
        cwd=tmp_path,
        max_chars=40,
    )

    assert len(result.stdout) == 40
    assert len(result.stderr) == 40
    assert result.stdout.endswith("... 命令输出过长，已截断 ...")
    assert result.stderr.endswith("... 命令输出过长，已截断 ...")


def test_run_shell_allows_cwd_inside_workspace(tmp_path: Path):
    child = tmp_path / "child"
    child.mkdir()

    result = run_shell(
        python_command("import os; print(os.getcwd())"),
        cwd="child",
        workspace=tmp_path,
    )

    assert result.success is True
    assert result.stdout.strip() == str(child.resolve())


def test_run_shell_blocks_cwd_outside_workspace(tmp_path: Path):
    with pytest.raises(RunShellError, match="工作区之外"):
        run_shell(python_command("print('hello')"), cwd="..", workspace=tmp_path)


def test_run_shell_rejects_missing_command(tmp_path: Path):
    with pytest.raises(RunShellError, match="未找到命令"):
        run_shell(["command-that-does-not-exist-devagent"], cwd=tmp_path)


def test_run_shell_rejects_empty_command(tmp_path: Path):
    with pytest.raises(RunShellError, match="不能为空"):
        run_shell([], cwd=tmp_path)
