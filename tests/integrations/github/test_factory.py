from pathlib import Path
from typing import Any

import pytest

from devagent.integrations.github import (
    GitHubIntegrationSettings,
    GitHubReviewTaskManager,
    InMemoryWebhookDeliveryStore,
    create_real_github_review_task_manager,
)
from devagent.llm import LLMResponse


class UnusedLLMClient:
    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        raise AssertionError("factory test 不应调用 LLM")


class UnusedHTTPClient:
    def request(self, method: str, url: str, **kwargs: object):
        raise AssertionError("factory test 不应访问网络")


def make_settings(tmp_path: Path) -> GitHubIntegrationSettings:
    key_path = tmp_path / "app.pem"
    key_path.write_text("not-read-until-authentication", encoding="utf-8")
    workspace = tmp_path / "repo"
    workspace.mkdir(exist_ok=True)
    return GitHubIntegrationSettings(
        app_client_id="Iv1.devagent",
        app_private_key_path=key_path,
        allowed_repository="openai/devagent",
        workspace=workspace,
    )


def test_factory_builds_manager_without_network_access(tmp_path: Path) -> None:
    manager = create_real_github_review_task_manager(
        settings=make_settings(tmp_path),
        llm_client=UnusedLLMClient(),
        delivery_store=InMemoryWebhookDeliveryStore(),
        http_client=UnusedHTTPClient(),
    )

    assert isinstance(manager, GitHubReviewTaskManager)


def test_factory_rejects_missing_private_key_and_workspace(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.app_private_key_path.unlink()

    with pytest.raises(ValueError, match="private key"):
        create_real_github_review_task_manager(
            settings=settings,
            llm_client=UnusedLLMClient(),
            delivery_store=InMemoryWebhookDeliveryStore(),
            http_client=UnusedHTTPClient(),
        )

    settings = make_settings(tmp_path)
    settings.workspace.rmdir()
    with pytest.raises(ValueError, match="workspace"):
        create_real_github_review_task_manager(
            settings=settings,
            llm_client=UnusedLLMClient(),
            delivery_store=InMemoryWebhookDeliveryStore(),
            http_client=UnusedHTTPClient(),
        )
