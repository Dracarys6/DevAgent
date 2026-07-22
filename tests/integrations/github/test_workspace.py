from pathlib import Path

import pytest

from devagent.integrations.github.client import GitHubClientError
from devagent.integrations.github.workspace import ControlledGitHubWorkspace


class RecordingGitRunner:
    def __init__(self, workspace: Path, remote: str) -> None:
        self.workspace = workspace
        self.remote = remote
        self.calls: list[tuple[list[str], Path, float]] = []

    def __call__(self, args: list[str], cwd: Path, timeout: float) -> str:
        self.calls.append((args, cwd, timeout))
        if args == ["rev-parse", "--show-toplevel"]:
            return str(self.workspace)
        if args == ["remote", "get-url", "origin"]:
            return self.remote
        return ""


def test_workspace_fetches_pr_ref_and_verifies_exact_commits(tmp_path: Path) -> None:
    workspace = tmp_path / "repos" / "devagent"
    workspace.mkdir(parents=True)
    runner = RecordingGitRunner(workspace, "git@github.com:openai/devagent.git")
    provider = ControlledGitHubWorkspace(
        allowed_repository="openai/devagent",
        workspace=workspace,
        allowed_root=tmp_path / "repos",
        git_runner=runner,
    )

    result = provider.prepare(
        repository="openai/devagent",
        pull_number=42,
        base_sha="a" * 40,
        head_sha="b" * 40,
    )

    assert result == workspace
    commands = [call[0] for call in runner.calls]
    assert commands == [
        ["rev-parse", "--show-toplevel"],
        ["remote", "get-url", "origin"],
        [
            "fetch",
            "--no-tags",
            "origin",
            "+refs/pull/42/head:refs/devagent/pull/42/head",
        ],
        ["cat-file", "-e", f"{'a' * 40}^{{commit}}"],
        ["cat-file", "-e", f"{'b' * 40}^{{commit}}"],
    ]
    assert not any(command[0] in {"checkout", "commit", "merge", "push"} for command in commands)


def test_workspace_rejects_repository_before_running_git(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    runner = RecordingGitRunner(workspace, "https://github.com/openai/devagent.git")
    provider = ControlledGitHubWorkspace(
        allowed_repository="openai/devagent",
        workspace=workspace,
        git_runner=runner,
    )

    with pytest.raises(GitHubClientError, match="allowlist"):
        provider.prepare(
            repository="attacker/repo",
            pull_number=1,
            base_sha="a" * 40,
            head_sha="b" * 40,
        )

    assert runner.calls == []


def test_workspace_rejects_mismatched_origin(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    runner = RecordingGitRunner(workspace, "https://github.com/other/repo.git")
    provider = ControlledGitHubWorkspace(
        allowed_repository="openai/devagent",
        workspace=workspace,
        git_runner=runner,
    )

    with pytest.raises(GitHubClientError, match="origin"):
        provider.prepare(
            repository="openai/devagent",
            pull_number=1,
            base_sha="a" * 40,
            head_sha="b" * 40,
        )


def test_workspace_rejects_path_outside_allowed_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allowed_root"):
        ControlledGitHubWorkspace(
            allowed_repository="openai/devagent",
            workspace=tmp_path / "outside",
            allowed_root=tmp_path / "allowed",
        )
