from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from devagent.integrations.github.client import (
    GitHubClientError,
    GitHubDiffSide,
    GitHubInlineCommentError,
)
from devagent.integrations.github.real_client import RealGitHubClient


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class QueueHTTPClient:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


class FixedTokenProvider:
    def __init__(self, token: str = "opaque-installation-token") -> None:
        self.token = token
        self.calls: list[int] = []

    def get_token(self, installation_id: int) -> SecretStr:
        self.calls.append(installation_id)
        return SecretStr(self.token)


class FixedWorkspaceProvider:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.calls: list[dict[str, object]] = []

    def prepare(self, **kwargs: object) -> Path:
        self.calls.append(kwargs)
        return self.workspace


def make_client(
    tmp_path: Path,
    responses: list[FakeResponse | Exception],
) -> tuple[RealGitHubClient, QueueHTTPClient, FixedTokenProvider, FixedWorkspaceProvider]:
    http = QueueHTTPClient(responses)
    token_provider = FixedTokenProvider()
    workspace_provider = FixedWorkspaceProvider(tmp_path)
    client = RealGitHubClient(
        installation_id=123,
        token_provider=token_provider,
        workspace_provider=workspace_provider,
        http_client=http,
        api_base_url="https://github.example/api/v3",
    )
    return client, http, token_provider, workspace_provider


def test_get_pull_request_uses_exact_shas_and_extracts_diff_lines(
    tmp_path: Path,
) -> None:
    base_sha = "a" * 40
    head_sha = "b" * 40
    client, http, tokens, workspaces = make_client(
        tmp_path,
        [
            FakeResponse(200, {"base": {"sha": base_sha}, "head": {"sha": head_sha}}),
            FakeResponse(
                200,
                [
                    {
                        "filename": "src/app.py",
                        "patch": "@@ -1,2 +1,3 @@\n context\n-old\n+new\n+extra",
                    },
                    {"filename": "assets/logo.png"},
                ],
            ),
        ],
    )

    result = client.get_pull_request(repository="openai/devagent", number=42)

    assert result.base_ref == base_sha
    assert result.head_ref == head_sha
    assert result.head_sha == head_sha
    assert result.workspace == str(tmp_path)
    assert {(item.path, item.line, item.side) for item in result.diff_lines} == {
        ("src/app.py", 1, GitHubDiffSide.LEFT),
        ("src/app.py", 1, GitHubDiffSide.RIGHT),
        ("src/app.py", 2, GitHubDiffSide.LEFT),
        ("src/app.py", 2, GitHubDiffSide.RIGHT),
        ("src/app.py", 3, GitHubDiffSide.RIGHT),
    }
    assert workspaces.calls == [
        {
            "repository": "openai/devagent",
            "pull_number": 42,
            "base_sha": base_sha,
            "head_sha": head_sha,
        }
    ]
    assert tokens.calls == [123, 123]
    assert all(
        call["headers"]["Authorization"] == "Bearer opaque-installation-token"
        for call in http.calls
    )


def test_upsert_summary_updates_existing_marker(tmp_path: Path) -> None:
    marker = "<!-- devagent-code-review -->"
    client, http, _, _ = make_client(
        tmp_path,
        [
            FakeResponse(200, [{"id": 77, "body": f"{marker}\nold"}]),
            FakeResponse(200, {"id": 77, "html_url": "https://github.test/comment/77"}),
        ],
    )

    locator = client.upsert_summary_comment(
        repository="openai/devagent",
        number=42,
        marker=marker,
        body=f"{marker}\nnew",
    )

    assert locator == "https://github.test/comment/77"
    assert http.calls[1]["method"] == "PATCH"
    assert http.calls[1]["url"].endswith("/repos/openai/devagent/issues/comments/77")
    assert http.calls[1]["json"] == {"body": f"{marker}\nnew"}


def test_upsert_summary_creates_comment_when_marker_is_missing(tmp_path: Path) -> None:
    client, http, _, _ = make_client(
        tmp_path,
        [
            FakeResponse(200, []),
            FakeResponse(201, {"id": 88}),
        ],
    )

    locator = client.upsert_summary_comment(
        repository="openai/devagent",
        number=42,
        marker="<!-- marker -->",
        body="<!-- marker -->\nsummary",
    )

    assert locator == "88"
    assert http.calls[1]["method"] == "POST"
    assert http.calls[1]["url"].endswith("/repos/openai/devagent/issues/42/comments")


def test_create_review_comment_uses_line_side_and_commit(tmp_path: Path) -> None:
    client, http, _, _ = make_client(
        tmp_path,
        [FakeResponse(201, {"html_url": "https://github.test/inline/1"})],
    )

    locator = client.create_review_comment(
        repository="openai/devagent",
        number=42,
        commit_id="b" * 40,
        path="src/app.py",
        line=12,
        side="RIGHT",
        body="建议修正边界条件。",
    )

    assert locator == "https://github.test/inline/1"
    assert http.calls[0]["json"] == {
        "body": "建议修正边界条件。",
        "commit_id": "b" * 40,
        "path": "src/app.py",
        "line": 12,
        "side": "RIGHT",
    }
    assert "position" not in http.calls[0]["json"]


def test_inline_422_uses_specific_downgrade_error(tmp_path: Path) -> None:
    client, _, _, _ = make_client(
        tmp_path,
        [FakeResponse(422, {"message": "private-diff-detail"})],
    )

    with pytest.raises(GitHubInlineCommentError) as exc_info:
        client.create_review_comment(
            repository="openai/devagent",
            number=42,
            commit_id="b" * 40,
            path="src/app.py",
            line=12,
            side="RIGHT",
            body="comment",
        )

    assert "private-diff-detail" not in str(exc_info.value)


def test_list_pages_has_a_hard_limit(tmp_path: Path) -> None:
    full_page = [{"id": index, "body": "no marker"} for index in range(100)]
    client, _, _, _ = make_client(
        tmp_path,
        [FakeResponse(200, full_page) for _ in range(10)],
    )

    with pytest.raises(GitHubClientError, match="安全上限"):
        client.upsert_summary_comment(
            repository="openai/devagent",
            number=42,
            marker="<!-- marker -->",
            body="summary",
        )


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(403, {"message": "secret-provider-body"}),
        FakeResponse(200, RuntimeError("invalid-json-secret")),
        RuntimeError("network-token-detail"),
    ],
)
def test_rest_errors_are_sanitized(
    tmp_path: Path,
    response: FakeResponse | Exception,
) -> None:
    client, _, _, _ = make_client(tmp_path, [response])

    with pytest.raises(GitHubClientError) as exc_info:
        client.upsert_summary_comment(
            repository="openai/devagent",
            number=42,
            marker="<!-- marker -->",
            body="summary",
        )

    message = str(exc_info.value)
    assert "secret-provider-body" not in message
    assert "invalid-json-secret" not in message
    assert "network-token-detail" not in message
