from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GitHubModel(BaseModel):
    """GitHub webhook 中当前业务关心的最小字段集合。"""

    model_config = ConfigDict(extra="ignore")


class GitHubRepository(GitHubModel):
    full_name: str = Field(min_length=1, max_length=500)


class GitHubRef(GitHubModel):
    ref: str = Field(min_length=1, max_length=255)
    sha: str = Field(pattern=r"^[0-9a-fA-F]{40,64}$")


class GitHubPullRequest(GitHubModel):
    number: int = Field(ge=1)
    draft: bool = False
    base: GitHubRef
    head: GitHubRef


class GitHubInstallation(GitHubModel):
    id: int = Field(ge=1)


class GitHubPullRequestWebhook(GitHubModel):
    action: str = Field(min_length=1, max_length=100)
    repository: GitHubRepository
    pull_request: GitHubPullRequest
    installation: GitHubInstallation


class GitHubWebhookStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class GitHubWebhookResponse(BaseModel):
    """GitHub webhook 接收结果；202 仅表示接收决定，不表示审查完成。"""

    model_config = ConfigDict(extra="forbid")

    delivery_id: str = Field(min_length=1, max_length=255)
    status: GitHubWebhookStatus
    task_id: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("delivery_id")
    @classmethod
    def validate_delivery_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("delivery_id 不能包含首尾空白")
        return value

    @model_validator(mode="after")
    def validate_task_id(self) -> "GitHubWebhookResponse":
        if self.status == GitHubWebhookStatus.ACCEPTED and self.task_id is None:
            raise ValueError("accepted webhook 必须包含 task_id")
        if self.status != GitHubWebhookStatus.ACCEPTED and self.task_id is not None:
            raise ValueError("非 accepted webhook 不能包含 task_id")
        return self
