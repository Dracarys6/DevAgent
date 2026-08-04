from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from pydantic import SecretStr
from unidiff import PatchSet
from unidiff.errors import UnidiffParseError

from .auth import GITHUB_API_VERSION, GitHubHTTPClient
from .client import (
    GitHubClientError,
    GitHubDiffLine,
    GitHubDiffSide,
    GitHubInlineCommentError,
    GitHubPullRequestData,
)

MAX_GITHUB_PAGES = 10
GITHUB_PAGE_SIZE = 100


class GitHubTokenProvider(Protocol):
    def get_token(self, installation_id: int) -> SecretStr: ...


class GitHubWorkspaceProvider(Protocol):
    def prepare(
        self,
        *,
        repository: str,
        pull_number: int,
        base_sha: str,
        head_sha: str,
    ) -> Path: ...


class RealGitHubClient:
    """使用 installation token 实现受限的 GitHub PR 读写能力。"""

    def __init__(
        self,
        *,
        installation_id: int,
        token_provider: GitHubTokenProvider,
        workspace_provider: GitHubWorkspaceProvider,
        http_client: GitHubHTTPClient,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 10.0,
    ) -> None:
        if isinstance(installation_id, bool) or installation_id < 1:
            raise ValueError("installation_id 必须大于或等于 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        normalized_base_url = api_base_url.rstrip("/")
        if not normalized_base_url.startswith("https://"):
            raise ValueError("GitHub API base URL 必须使用 HTTPS")
        self._installation_id = installation_id
        self._token_provider = token_provider
        self._workspace_provider = workspace_provider
        self._http_client = http_client
        self._api_base_url = normalized_base_url
        self._timeout_seconds = timeout_seconds

    def get_pull_request(
        self,
        *,
        repository: str,
        number: int,
    ) -> GitHubPullRequestData:
        owner, repo = _split_repository(repository)
        if isinstance(number, bool) or number < 1:
            raise ValueError("Pull Request number 必须大于或等于 1")
        prefix = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        payload = self._request_json("GET", f"{prefix}/pulls/{number}", {200})
        if not isinstance(payload, dict):
            raise GitHubClientError("GitHub Pull Request 响应格式无效")
        try:
            base_sha = payload["base"]["sha"]
            head_sha = payload["head"]["sha"]
            if not isinstance(base_sha, str) or not isinstance(head_sha, str):
                raise TypeError("PR SHA 必须是字符串")
            workspace = self._workspace_provider.prepare(
                repository=repository,
                pull_number=number,
                base_sha=base_sha,
                head_sha=head_sha,
            )
            files = self._list_pages(f"{prefix}/pulls/{number}/files")
            diff_lines = _extract_diff_lines(files)
            return GitHubPullRequestData(
                base_ref=base_sha,
                head_ref=head_sha,
                head_sha=head_sha,
                workspace=str(workspace),
                diff_lines=diff_lines,
            )
        except GitHubClientError:
            raise
        except Exception as exc:
            raise GitHubClientError("GitHub Pull Request 响应格式无效") from exc

    def upsert_summary_comment(
        self,
        *,
        repository: str,
        number: int,
        marker: str,
        body: str,
    ) -> str:
        owner, repo = _split_repository(repository)
        prefix = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        comments = self._list_pages(f"{prefix}/issues/{number}/comments")
        existing = next(
            (
                item
                for item in comments
                if isinstance(item, dict)
                and isinstance(item.get("body"), str)
                and marker in item["body"]
            ),
            None,
        )
        if existing is None:
            payload = self._request_json(
                "POST",
                f"{prefix}/issues/{number}/comments",
                {201},
                json_body={"body": body},
            )
        else:
            comment_id = existing.get("id")
            if not isinstance(comment_id, int):
                raise GitHubClientError("GitHub 摘要评论响应格式无效")
            payload = self._request_json(
                "PATCH",
                f"{prefix}/issues/comments/{comment_id}",
                {200},
                json_body={"body": body},
            )
        return _response_locator(payload, "GitHub 摘要评论响应格式无效")

    def create_review_comment(
        self,
        *,
        repository: str,
        number: int,
        commit_id: str,
        path: str,
        line: int,
        side: str,
        body: str,
    ) -> str:
        owner, repo = _split_repository(repository)
        prefix = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        payload = self._request_json(
            "POST",
            f"{prefix}/pulls/{number}/comments",
            {201},
            json_body={
                "body": body,
                "commit_id": commit_id,
                "path": path,
                "line": line,
                "side": side,
            },
            inline_comment=True,
        )
        return _response_locator(payload, "GitHub inline comment 响应格式无效")

    def _list_pages(self, path: str) -> list[object]:
        items: list[object] = []
        for page in range(1, MAX_GITHUB_PAGES + 1):
            payload = self._request_json(
                "GET",
                path,
                {200},
                params={"per_page": GITHUB_PAGE_SIZE, "page": page},
            )
            if not isinstance(payload, list):
                raise GitHubClientError("GitHub 分页响应格式无效")
            items.extend(payload)
            if len(payload) < GITHUB_PAGE_SIZE:
                return items
        raise GitHubClientError("GitHub 分页结果超过安全上限")

    def _request_json(
        self,
        method: str,
        path: str,
        expected_statuses: set[int],
        *,
        json_body: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        inline_comment: bool = False,
    ) -> Any:
        try:
            token = self._token_provider.get_token(self._installation_id)
            response = self._http_client.request(
                method,
                f"{self._api_base_url}{path}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token.get_secret_value()}",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                    "User-Agent": "DevAgent/0.1.0",
                },
                json=json_body,
                params=params,
                timeout=self._timeout_seconds,
            )
        except GitHubClientError:
            raise
        except Exception as exc:
            raise GitHubClientError("GitHub REST API 请求失败") from exc
        if response.status_code not in expected_statuses:
            if inline_comment and response.status_code == 422:
                raise GitHubInlineCommentError("GitHub inline comment 定位无效")
            raise GitHubClientError(
                f"GitHub REST API 请求被拒绝: status={response.status_code}"
            )
        try:
            return response.json()
        except Exception as exc:
            raise GitHubClientError("GitHub REST API 响应不是合法 JSON") from exc


def _extract_diff_lines(files: list[object]) -> list[GitHubDiffLine]:
    lines: list[GitHubDiffLine] = []
    seen: set[tuple[str, int, GitHubDiffSide]] = set()
    for item in files:
        if not isinstance(item, dict):
            continue
        path = item.get("filename")
        patch = item.get("patch")
        if not isinstance(path, str) or not isinstance(patch, str):
            continue
        try:
            parsed = PatchSet(f"--- a/{path}\n+++ b/{path}\n{patch}\n")
        except UnidiffParseError:
            # * GitHub 可能省略二进制或过大 patch；对应 finding 将降级到摘要。
            continue
        for patched_file in parsed:
            for hunk in patched_file:
                for line in hunk:
                    candidates: list[tuple[int | None, GitHubDiffSide]] = []
                    if line.is_removed or line.is_context:
                        candidates.append((line.source_line_no, GitHubDiffSide.LEFT))
                    if line.is_added or line.is_context:
                        candidates.append((line.target_line_no, GitHubDiffSide.RIGHT))
                    for line_number, side in candidates:
                        if line_number is None:
                            continue
                        location = (path, line_number, side)
                        if location in seen:
                            continue
                        seen.add(location)
                        lines.append(
                            GitHubDiffLine(path=path, line=line_number, side=side)
                        )
    return lines


def _split_repository(repository: str) -> tuple[str, str]:
    if not isinstance(repository, str) or repository != repository.strip():
        raise ValueError("repository 格式无效")
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("repository 必须使用 owner/repo 格式")
    return parts[0], parts[1]


def _response_locator(payload: Any, error_message: str) -> str:
    if not isinstance(payload, dict):
        raise GitHubClientError(error_message)
    html_url = payload.get("html_url")
    if isinstance(html_url, str) and html_url:
        return html_url
    comment_id = payload.get("id")
    if isinstance(comment_id, int):
        return str(comment_id)
    raise GitHubClientError(error_message)
