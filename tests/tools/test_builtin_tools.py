import json
import sys
from pathlib import Path

import pytest

from devagent.memory import RetrievalResult
from devagent.tools.builtin import (
    GetCIResultTool,
    GitCompareTool,
    GitDiffTool,
    KnowledgeRetrieveTool,
    ReadFileTool,
    RunShellTool,
    SearchCodeTool,
    SearchLogTool,
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


def test_git_diff_tool_returns_commit_patch(
    git_repo_with_commit: tuple[Path, str],
):
    repo, commit_id = git_repo_with_commit

    result = GitDiffTool().invoke({"commit_id": commit_id, "workspace": str(repo)})

    assert result.success is True
    assert "diff --git a/app.py b/app.py" in result.content


def test_git_diff_tool_validates_arguments_before_execution(tmp_path: Path):
    result = GitDiffTool().invoke(
        {"commit_id": "HEAD", "workspace": str(tmp_path), "max_chars": 0}
    )

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR


def test_git_compare_tool_returns_structured_change_evidence(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, refs = git_repo_for_compare

    result = GitCompareTool().invoke(
        {"base_ref": "main", "head_ref": "feature", "workspace": str(repo)}
    )
    content = json.loads(result.content)

    assert result.success is True
    assert content["merge_base"] == refs["common"]
    assert content["changed_files"]


def test_git_compare_tool_validates_arguments_before_execution(tmp_path: Path):
    result = GitCompareTool().invoke(
        {
            "base_ref": "main",
            "head_ref": "feature",
            "workspace": str(tmp_path),
            "max_chars": 0,
        }
    )

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR


def test_get_ci_result_tool_returns_failed_evidence():
    result = GetCIResultTool().invoke({"commit_id": "abc123"})

    assert result.success is True
    assert "unit-tests" in result.content
    assert "assert 3 >= 12" in result.content


def test_get_ci_result_tool_validates_arguments_before_execution():
    result = GetCIResultTool().invoke({"commit_id": "abc123", "max_log_chars": 0})

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR


def test_search_log_tool_returns_first_anomaly():
    result = SearchLogTool().invoke({"task_id": "task_001", "keyword": "retry"})

    assert result.success is True
    content = json.loads(result.content)
    assert content["first_anomaly"]["sequence_id"] == 3
    assert [entry["sequence_id"] for entry in content["entries"]] == [4, 5]


def test_search_log_tool_validates_arguments_before_execution():
    result = SearchLogTool().invoke({"task_id": "task_001", "max_entries": 0})

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR


def test_builtin_tool_risk_levels():
    assert GetCIResultTool.risk_level == RiskLevel.LOW
    assert GitDiffTool.risk_level == RiskLevel.LOW
    assert ReadFileTool.risk_level == RiskLevel.LOW
    assert SearchCodeTool.risk_level == RiskLevel.LOW
    assert SearchLogTool.risk_level == RiskLevel.LOW
    assert RunShellTool.risk_level == RiskLevel.HIGH
    assert GitCompareTool.risk_level == RiskLevel.LOW
    assert KnowledgeRetrieveTool.risk_level == RiskLevel.LOW


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
        "get_ci_result",
        "git_compare",
        "git_diff",
        "knowledge_retrieve",
        "read_file",
        "run_shell",
        "search_code",
        "search_log",
    ]


def test_create_builtin_registry_injects_knowledge_strategy() -> None:
    calls: list[tuple[str, str, int]] = []

    def retrieve(query: str, workspace: str, top_k: int) -> RetrievalResult:
        calls.append((query, workspace, top_k))
        return RetrievalResult(
            query=query,
            top_k=top_k,
            total_candidates=0,
            retrieval_ms=1.0,
        )

    registry = create_builtin_registry(knowledge_retriever=retrieve)

    result = registry.execute(
        "knowledge_retrieve",
        {"query": "runtime", "workspace": "workspace", "top_k": 2},
    )

    assert result.success is True
    assert calls == [("runtime", "workspace", 2)]


def test_knowledge_retrieve_tool_returns_workspace_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "uploader.py").write_text(
        "def build_upload_timeout(): pass\n",
        encoding="utf-8",
    )

    result = KnowledgeRetrieveTool().invoke(
        {
            "query": "upload timeout",
            "workspace": str(tmp_path),
            "top_k": 3,
        }
    )
    content = json.loads(result.content)

    assert result.success is True
    assert content["items"][0]["path"] == "uploader.py"
    assert result.metadata["item_count"] == 1


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "", "workspace": "workspace"},
        {"query": "upload", "workspace": ""},
        {"query": "upload", "workspace": "workspace", "top_k": 0},
        {"query": "upload", "workspace": "workspace", "top_k": 51},
        {"query": "upload", "workspace": "workspace", "top_k": True},
    ],
)
def test_knowledge_retrieve_tool_validates_arguments(
    arguments: dict[str, object],
) -> None:
    result = KnowledgeRetrieveTool().invoke(arguments)

    assert result.success is False
    assert result.error_code == ErrorCode.ARGUMENT_VALIDATION_ERROR
