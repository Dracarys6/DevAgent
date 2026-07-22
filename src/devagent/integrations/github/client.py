from enum import Enum
from pathlib import PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GitHubClientError(RuntimeError):
    pass


class GitHubInlineCommentError(GitHubClientError):
    pass


class GitHubClientModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitHubDiffSide(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class GitHubDiffLine(GitHubClientModel):
    path: str = Field(min_length=1, max_length=1000)
    line: int = Field(ge=1)
    side: GitHubDiffSide

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            value != value.strip()
            or value in {"", "."}
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in value
        ):
            raise ValueError("diff path 必须是仓库内 POSIX 相对路径")
        return value


class GitHubPullRequestData(GitHubClientModel):
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    head_sha: str = Field(pattern=r"^[0-9a-fA-F]{40,64}$")
    workspace: str = Field(min_length=1, max_length=2000)
    diff_lines: list[GitHubDiffLine] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pull_request(self) -> "GitHubPullRequestData":
        if (
            self.base_ref != self.base_ref.strip()
            or self.head_ref != self.head_ref.strip()
            or self.workspace != self.workspace.strip()
        ):
            raise ValueError("PR refs 和 workspace 不能包含首尾空白")
        if self.base_ref == self.head_ref:
            raise ValueError("PR base_ref 和 head_ref 不能相同")
        locations = {(item.path, item.line, item.side) for item in self.diff_lines}
        if len(locations) != len(self.diff_lines):
            raise ValueError("diff_lines 不能包含重复定位")
        return self


class GitHubClient(Protocol):
    def get_pull_request(
        self, *, repository: str, number: int
    ) -> GitHubPullRequestData:
        # * 获取当前 PR refs、SHA、受控 workspace 和可评论 diff 行。
        ...

    def upsert_summary_comment(
        self, *, repository: str, number: int, marker: str, body: str
    ) -> str: ...

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
    ) -> str: ...


class FakeGitHubClient(GitHubClient):
    """用于测试和本地演示的纯内存 GitHub 客户端。"""

    def __init__(
        self,
        pull_requests: dict[tuple[str, int], GitHubPullRequestData] | None = None,
    ) -> None:
        self.pull_requests = dict(pull_requests or {})
        self.get_calls: list[dict[str, object]] = []
        self.summary_calls: list[dict[str, object]] = []
        self.inline_calls: list[dict[str, object]] = []
        self.summary_comments: dict[tuple[str, int, str], str] = {}

    def get_pull_request(
        self, *, repository: str, number: int
    ) -> GitHubPullRequestData:
        self.get_calls.append({"repository": repository, "number": number})
        try:
            return self.pull_requests[(repository, number)].model_copy(deep=True)
        except KeyError as exc:
            raise GitHubClientError("Fake GitHub Pull Request 不存在") from exc

    def upsert_summary_comment(
        self, *, repository: str, number: int, marker: str, body: str
    ) -> str:
        call = {
            "repository": repository,
            "number": number,
            "marker": marker,
            "body": body,
        }
        self.summary_calls.append(call)
        self.summary_comments[(repository, number, marker)] = body
        return f"fake-summary-{repository}-{number}"

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
        self.inline_calls.append(
            {
                "repository": repository,
                "number": number,
                "commit_id": commit_id,
                "path": path,
                "line": line,
                "side": side,
                "body": body,
            }
        )
        return f"fake-inline-{len(self.inline_calls)}"
