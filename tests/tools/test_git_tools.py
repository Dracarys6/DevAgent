import subprocess
from pathlib import Path

import pytest

from devagent.tools.git_tools import GitDiffError, TRUNCATION_MARKER, git_diff


def test_git_diff_returns_commit_patch(
    git_repo_with_commit: tuple[Path, str],
):
    repo, commit_id = git_repo_with_commit

    result = git_diff(commit_id=commit_id, workspace=repo)

    assert "diff --git a/app.py b/app.py" in result
    assert "-value = 1" in result
    assert "+value = 2" in result


def test_git_diff_accepts_workspace_inside_git_tree(
    git_repo_with_commit: tuple[Path, str],
):
    repo, commit_id = git_repo_with_commit
    nested = repo / "src"
    nested.mkdir()

    result = git_diff(commit_id=commit_id, workspace=nested)

    assert "diff --git a/app.py b/app.py" in result


def test_git_diff_returns_empty_string_for_commit_without_patch(
    git_repo_with_commit: tuple[Path, str],
):
    repo, _ = git_repo_with_commit
    subprocess.run(
        ["git", "commit", "--quiet", "--allow-empty", "-m", "empty commit"],
        cwd=repo,
        check=True,
    )
    empty_commit_id = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()

    assert git_diff(empty_commit_id, repo) == ""


@pytest.mark.parametrize(
    ("commit_id", "max_chars", "timeout", "message"),
    [
        (" ", 20_000, 10.0, "commit_id 不能为空"),
        ("HEAD", 0, 10.0, "max_chars"),
        ("HEAD", 20_000, 0, "timeout"),
    ],
)
def test_git_diff_rejects_invalid_parameters(
    git_repo_with_commit: tuple[Path, str],
    commit_id: str,
    max_chars: int,
    timeout: float,
    message: str,
):
    repo, _ = git_repo_with_commit

    with pytest.raises(GitDiffError, match=message):
        git_diff(commit_id, repo, max_chars=max_chars, timeout=timeout)


def test_git_diff_rejects_missing_workspace(tmp_path: Path):
    with pytest.raises(GitDiffError, match="工作区不存在"):
        git_diff("HEAD", tmp_path / "missing")


def test_git_diff_rejects_workspace_file(tmp_path: Path):
    workspace_file = tmp_path / "workspace.txt"
    workspace_file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(GitDiffError, match="工作区不是目录"):
        git_diff("HEAD", workspace_file)


def test_git_diff_rejects_non_git_workspace(tmp_path: Path):
    workspace = tmp_path / "not-a-repo"
    workspace.mkdir()

    with pytest.raises(GitDiffError, match="工作区不是 Git 仓库"):
        git_diff("HEAD", workspace)


def test_git_diff_rejects_invalid_commit(
    git_repo_with_commit: tuple[Path, str],
):
    repo, _ = git_repo_with_commit

    with pytest.raises(GitDiffError, match="无法读取 Git commit"):
        git_diff("missing-commit", repo)


def test_git_diff_treats_option_like_commit_as_revision(
    git_repo_with_commit: tuple[Path, str],
):
    repo, _ = git_repo_with_commit

    with pytest.raises(GitDiffError, match="无法读取 Git commit"):
        git_diff("--help", repo)


def test_git_diff_truncates_long_diff(
    git_repo_with_commit: tuple[Path, str],
):
    repo, _ = git_repo_with_commit
    (repo / "long_file.txt").write_text("a" * 1_000, encoding="utf-8")
    subprocess.run(["git", "add", "long_file.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "add long file"],
        cwd=repo,
        check=True,
    )
    commit_id = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()

    result = git_diff(commit_id, repo, max_chars=200)

    assert len(result) == 200
    assert result.endswith(TRUNCATION_MARKER)
