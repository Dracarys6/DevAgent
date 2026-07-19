import subprocess
from pathlib import Path

import pytest

from devagent.tools.git_tools import (
    GitCompareError,
    GitCompareResult,
    GitDiffError,
    TRUNCATION_MARKER,
    git_compare,
    git_diff,
)


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


def test_git_compare_uses_merge_base_for_feature_range(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, refs = git_repo_for_compare

    result = git_compare("main", "feature", repo)

    assert result.base_sha == refs["main"]
    assert result.head_sha == refs["feature"]
    assert result.merge_base == refs["common"]
    assert "+feature = True" in result.patch
    assert "main_only.py" not in result.patch


def test_git_compare_preserves_file_statuses_and_paths(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, _ = git_repo_for_compare

    result = git_compare("main", "feature", repo)
    files = {item.status: item for item in result.changed_files}

    assert files["A"].old_path is None
    assert files["A"].new_path == "added file.py"
    assert files["M"].old_path == files["M"].new_path == "app.py"
    assert files["D"].old_path == "delete_me.txt"
    assert files["D"].new_path is None
    assert files["R"].old_path == "rename me.txt"
    assert files["R"].new_path == "renamed file.txt"
    assert files["R"].similarity == 100


def test_git_compare_preserves_hunk_locations(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, _ = git_repo_for_compare

    result = git_compare("main", "feature", repo)

    assert "diff --git" in result.patch
    assert "--- " in result.patch
    assert "+++ " in result.patch
    assert "@@ -" in result.patch
    assert result.hunk_count == result.patch.count("@@ -")


def test_git_compare_records_patch_truncation(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, _ = git_repo_for_compare

    result = git_compare("main", "feature", repo, max_chars=120)

    assert result.truncated is True
    assert result.original_patch_chars > 120
    assert result.returned_patch_chars == 120
    assert len(result.patch) == 120
    assert result.hunk_count > 0


def test_git_compare_result_supports_json_round_trip(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, _ = git_repo_for_compare
    result = git_compare("main", "feature", repo)

    restored = GitCompareResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_git_compare_accepts_workspace_inside_repository(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, refs = git_repo_for_compare
    nested = repo / "nested"
    nested.mkdir()

    result = git_compare("main", "feature", nested)

    assert result.merge_base == refs["common"]


@pytest.mark.parametrize(
    ("base_ref", "head_ref", "max_chars", "timeout", "message"),
    [
        (" ", "feature", 20_000, 10.0, "base_ref 不能为空"),
        ("main", " ", 20_000, 10.0, "head_ref 不能为空"),
        (" main", "feature", 20_000, 10.0, "首尾空白"),
        ("main", "main", 20_000, 10.0, "不能相同"),
        ("main", "feature", 0, 10.0, "max_chars"),
        ("main", "feature", 20_000, 0, "timeout"),
    ],
)
def test_git_compare_rejects_invalid_parameters(
    git_repo_for_compare: tuple[Path, dict[str, str]],
    base_ref: str,
    head_ref: str,
    max_chars: int,
    timeout: float,
    message: str,
):
    repo, _ = git_repo_for_compare

    with pytest.raises(GitCompareError, match=message):
        git_compare(base_ref, head_ref, repo, max_chars=max_chars, timeout=timeout)


def test_git_compare_rejects_refs_resolving_to_same_commit(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, _ = git_repo_for_compare
    subprocess.run(["git", "branch", "feature-alias", "feature"], cwd=repo, check=True)

    with pytest.raises(GitCompareError, match="解析到同一 commit"):
        git_compare("feature", "feature-alias", repo)


@pytest.mark.parametrize(
    ("base_ref", "head_ref", "message"),
    [
        ("missing-base", "feature", "无法解析 base_ref"),
        ("main", "missing-head", "无法解析 head_ref"),
        ("--help", "feature", "无法解析 base_ref"),
    ],
)
def test_git_compare_rejects_invalid_or_option_like_refs(
    git_repo_for_compare: tuple[Path, dict[str, str]],
    base_ref: str,
    head_ref: str,
    message: str,
):
    repo, _ = git_repo_for_compare

    with pytest.raises(GitCompareError, match=message):
        git_compare(base_ref, head_ref, repo)


def test_git_compare_rejects_histories_without_common_ancestor(
    git_repo_for_compare: tuple[Path, dict[str, str]],
):
    repo, _ = git_repo_for_compare
    subprocess.run(
        ["git", "switch", "--quiet", "--orphan", "unrelated"],
        cwd=repo,
        check=True,
    )
    (repo / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "unrelated history"],
        cwd=repo,
        check=True,
    )

    with pytest.raises(GitCompareError, match="没有共同祖先"):
        git_compare("main", "unrelated", repo)


def test_git_compare_rejects_invalid_workspaces(tmp_path: Path):
    missing = tmp_path / "missing"
    with pytest.raises(GitCompareError, match="工作区不存在"):
        git_compare("main", "feature", missing)

    workspace_file = tmp_path / "workspace.txt"
    workspace_file.write_text("file", encoding="utf-8")
    with pytest.raises(GitCompareError, match="工作区不是目录"):
        git_compare("main", "feature", workspace_file)

    non_repo = tmp_path / "non-repo"
    non_repo.mkdir()
    with pytest.raises(GitCompareError, match="工作区不是 Git 仓库"):
        git_compare("main", "feature", non_repo)


def test_git_compare_converts_subprocess_timeout(
    git_repo_for_compare: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
):
    repo, _ = git_repo_for_compare

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["git", "rev-parse"], timeout=0.01)

    monkeypatch.setattr("devagent.tools.git_tools.subprocess.run", raise_timeout)

    with pytest.raises(GitCompareError, match="执行超时"):
        git_compare("main", "feature", repo, timeout=0.01)


def test_git_compare_is_read_only_and_uses_safe_commands(
    git_repo_for_compare: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
):
    repo, _ = git_repo_for_compare
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    status_before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    original_run = subprocess.run
    calls: list[tuple[list[str], dict[str, object]]] = []

    def record_run(command, **kwargs):
        calls.append((command, kwargs))
        return original_run(command, **kwargs)

    monkeypatch.setattr("devagent.tools.git_tools.subprocess.run", record_run)

    git_compare("main", "feature", repo)

    assert {command[1] for command, _ in calls} <= {
        "rev-parse",
        "merge-base",
        "diff",
    }
    assert all(not kwargs.get("shell", False) for _, kwargs in calls)
    assert all("--no-ext-diff" in command for command, _ in calls if command[1] == "diff")
    assert all("--no-textconv" in command for command, _ in calls if command[1] == "diff")
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == head_before
    assert subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == status_before
