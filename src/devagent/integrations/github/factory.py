from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from devagent.llm import LLMClient
from devagent.review import LocalCodeReviewEvidenceCollector
from devagent.review.ports import WebhookDeliveryStore
from devagent.review.service import CodeReviewService

from .adapters import GitHubPullRequestSource, GitHubReviewPublisher
from .auth import (
    DEFAULT_GITHUB_API_BASE_URL,
    GitHubAppCredentials,
    GitHubHTTPClient,
    GitHubInstallationTokenProvider,
)
from .real_client import GitHubWorkspaceProvider, RealGitHubClient
from .tasks import (
    GitHubReviewPortFactory,
    GitHubReviewPorts,
    GitHubReviewTaskManager,
)
from .workspace import ControlledGitHubWorkspace


class GitHubIntegrationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_client_id: str = Field(min_length=1, max_length=255)
    app_private_key_path: Path
    allowed_repository: str = Field(min_length=3, max_length=500)
    workspace: Path
    api_base_url: str = DEFAULT_GITHUB_API_BASE_URL
    api_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    git_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    @field_validator("app_client_id", "allowed_repository", "api_base_url")
    @classmethod
    def validate_clean_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("GitHub integration 配置不能包含首尾空白")
        return value


@dataclass(frozen=True)
class RealGitHubReviewPortFactory(GitHubReviewPortFactory):
    token_provider: GitHubInstallationTokenProvider
    workspace_provider: GitHubWorkspaceProvider
    http_client: GitHubHTTPClient
    api_base_url: str = "https://api.github.com"
    timeout_seconds: float = 10.0

    def create(self, installation_id: int) -> GitHubReviewPorts:
        client = RealGitHubClient(
            installation_id=installation_id,
            token_provider=self.token_provider,
            workspace_provider=self.workspace_provider,
            http_client=self.http_client,
            api_base_url=self.api_base_url,
            timeout_seconds=self.timeout_seconds,
        )
        return GitHubReviewPorts(
            source=GitHubPullRequestSource(client),
            publisher=GitHubReviewPublisher(client),
        )


def create_real_github_review_task_manager(
    *,
    settings: GitHubIntegrationSettings,
    llm_client: LLMClient,
    delivery_store: WebhookDeliveryStore,
    http_client: GitHubHTTPClient,
) -> GitHubReviewTaskManager:
    private_key_path = settings.app_private_key_path.expanduser().resolve()
    if not private_key_path.is_file():
        raise ValueError("GitHub App private key 文件不存在")
    workspace = settings.workspace.expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("GitHub workspace 不存在")

    token_provider = GitHubInstallationTokenProvider(
        credentials=GitHubAppCredentials(
            client_id=settings.app_client_id,
            private_key_path=private_key_path,
        ),
        http_client=http_client,
        api_base_url=settings.api_base_url,
        timeout_seconds=settings.api_timeout_seconds,
    )
    workspace_provider = ControlledGitHubWorkspace(
        allowed_repository=settings.allowed_repository,
        workspace=workspace,
        allowed_root=workspace.parent,
        timeout_seconds=settings.git_timeout_seconds,
    )
    port_factory = RealGitHubReviewPortFactory(
        token_provider=token_provider,
        workspace_provider=workspace_provider,
        http_client=http_client,
        api_base_url=settings.api_base_url,
        timeout_seconds=settings.api_timeout_seconds,
    )
    return GitHubReviewTaskManager(
        service=CodeReviewService(
            llm_client=llm_client,
            evidence_collector=LocalCodeReviewEvidenceCollector(),
        ),
        delivery_store=delivery_store,
        port_factory=port_factory,
    )
