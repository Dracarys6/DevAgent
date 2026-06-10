import sys
from pathlib import Path

from devagent.tools.builtin import (
    ReadFileTool,
    RunShellTool,
    SearchCodeTool,
    create_builtin_registry,
)
from devagent.tools.models import ErrorCode, RiskLevel


def test_read_file_tool_reads_workspace_file(tmp_path: Path):
    (tmp_path / "sample.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = ReadFileTool().invoke(
        {
            "file_path": "sample.txt",
            "start_line": 2,
            "workspace": str(tmp_path),
        }
    )

    assert result.success is True
    assert result.content == "2: beta"


def test_search_code_tool_searches_workspace(tmp_path: Path):
    (tmp_path / "app.py").write_text("needle\n", encoding="utf-8")

    result = SearchCodeTool().invoke(
        {
            "query": "needle",
            "workspace": str(tmp_path),
            "file_pattern": "*.py",
        }
    )

    assert result.success is True
    assert "app.py" in result.content


def test_run_shell_tool_executes_command(tmp_path: Path):
    result = RunShellTool().invoke(
        {
            "command": [sys.executable, "-c", "print('hello')"],
            "cwd": str(tmp_path),
        }
    )

    assert result.success is True
    assert result.content == "hello\n"
    assert result.metadata["returncode"] == 0


def test_builtin_tool_risk_levels():
    assert ReadFileTool.risk_level == RiskLevel.LOW
    assert SearchCodeTool.risk_level == RiskLevel.LOW
    assert RunShellTool.risk_level == RiskLevel.HIGH


def test_builtin_tool_arguments_are_validated_before_execution(tmp_path: Path):
    result = SearchCodeTool().invoke({"query": "", "workspace": str(tmp_path)})

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR


def test_run_shell_tool_rejects_empty_command():
    result = RunShellTool().invoke({"command": []})

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR


def test_create_builtin_registry_registers_all_tools():
    registry = create_builtin_registry()

    assert [tool.name for tool in registry.list()] == [
        "read_file",
        "run_shell",
        "search_code",
    ]
