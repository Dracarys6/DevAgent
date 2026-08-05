from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import CodeReviewReport


class ReviewPortModel(BaseModel):
    model_config = ConfigDict(extra="forbid")  # * 拒绝模型返回未知字段


class PullRequestLocator(ReviewPortModel):
    platform: str = Field(min_length=1, max_length=50)
    repository: str = Field(min_length=1, max_length=500)
    number: int = Field(ge=1)

    @field_validator("platform", "repository")
    @classmethod
    def validate_clean_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("平台和仓库标识不能包含首尾空白")
        return value


class PullRequestSnapshot(ReviewPortModel):
    locator: PullRequestLocator
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    head_sha: str = Field(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$")
    workspace: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "PullRequestSnapshot":
        if (
            self.base_ref != self.base_ref.strip()
            or self.head_ref != self.head_ref.strip()
        ):
            raise ValueError("base_ref 和 head_ref 不能包含首尾空白")
        if self.base_ref == self.head_ref:
            raise ValueError("base_ref 和 head_ref 不能相同")
        if self.workspace != self.workspace.strip():
            raise ValueError("workspace 不能包含首尾空白")
        return self


class ReviewPublishResult(ReviewPortModel):
    summary_published: bool
    inline_comment_count: int = Field(ge=0)
    downgraded_finding_count: int = Field(ge=0)
    external_comment_id: str | None = None


class PullRequestSource(Protocol):
    def get_pull_request(
        self,
        locator: PullRequestLocator,
    ) -> PullRequestSnapshot: ...


class ReviewPublisher(Protocol):
    def publish(
        self,
        *,
        pull_request: PullRequestSnapshot,
        report: CodeReviewReport,
    ) -> ReviewPublishResult: ...


class WebhookDeliveryStore(Protocol):
    def claim(
        self,
        delivery_id: str,
    ) -> bool: ...

    def mark_completed(
        self,
        delivery_id: str,
    ) -> None: ...

    def release(self, delivery_id: str) -> None: ...
