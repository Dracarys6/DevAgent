from devagent.tools import GitDiffTool


def test_tools_package_exports_git_diff_tool():
    assert GitDiffTool.name == "git_diff"
