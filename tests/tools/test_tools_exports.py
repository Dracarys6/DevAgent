from devagent.tools import (
    GetCIResultTool,
    GitCompareTool,
    GitDiffTool,
    SearchLogTool,
    KnowledgeRetrieveTool,
    RunShellTool,
)


def test_tools_package_exports_git_diff_tool():
    assert GitDiffTool.name == "git_diff"


def test_tools_package_exports_get_ci_result_tool():
    assert GetCIResultTool.name == "get_ci_result"


def test_tools_package_exports_search_log_tool():
    assert SearchLogTool.name == "search_log"


def test_tools_package_exports_git_compare_tool():
    assert GitCompareTool.name == "git_compare"


def test_tools_package_exports_run_shell_tool():
    assert RunShellTool.name == "run_shell"


def test_tools_package_exports_knowledge_retrieve_tool() -> None:
    assert KnowledgeRetrieveTool.name == "knowledge_retrieve"
