from pathlib import Path

import pytest

from devagent.integrations.github import (
    FakeGitHubClient,
    GitHubClientError,
    GitHubPullRequestData,
    GitHubPullRequestSource,
)
from devagent.review import PullRequestLocator


def make_data(workspace: Path) -> GitHubPullRequestData:
    return GitHubPullRequestData(
        base_ref="main",
        head_ref="feature/payment",
        head_sha="b" * 40,
        workspace=str(workspace),
    )


def test_github_source_maps_current_pull_request_snapshot(tmp_path: Path) -> None:
    locator = PullRequestLocator(
        platform="github",
        repository="openai/devagent",
        number=42,
    )
    client = FakeGitHubClient({("openai/devagent", 42): make_data(tmp_path)})
    source = GitHubPullRequestSource(client)

    snapshot = source.get_pull_request(locator)

    assert snapshot.locator == locator
    assert snapshot.base_ref == "main"
    assert snapshot.head_ref == "feature/payment"
    assert snapshot.head_sha == "b" * 40
    assert snapshot.workspace == str(tmp_path)
    assert client.get_calls == [{"repository": "openai/devagent", "number": 42}]
    assert client.summary_calls == []
    assert client.inline_calls == []


def test_github_source_rejects_non_github_locator(tmp_path: Path) -> None:
    source = GitHubPullRequestSource(FakeGitHubClient())
    locator = PullRequestLocator(platform="gitlab", repository="team/repo", number=1)

    with pytest.raises(ValueError, match="GitHub"):
        source.get_pull_request(locator)


def test_github_source_sanitizes_client_failure() -> None:
    class RaisingClient(FakeGitHubClient):
        def get_pull_request(self, *, repository: str, number: int):
            raise RuntimeError("token=secret-provider-response")

    source = GitHubPullRequestSource(RaisingClient())
    locator = PullRequestLocator(
        platform="github",
        repository="openai/devagent",
        number=42,
    )

    with pytest.raises(GitHubClientError) as exc_info:
        source.get_pull_request(locator)

    assert "secret-provider-response" not in str(exc_info.value)
