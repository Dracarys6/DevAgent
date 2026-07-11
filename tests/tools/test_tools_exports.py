from devagent.tools import GetCIResultTool, GitDiffTool


def test_tools_package_exports_git_diff_tool():
    assert GitDiffTool.name == "git_diff"


def test_tools_package_exports_get_ci_result_tool():
    assert GetCIResultTool.name == "get_ci_result"
