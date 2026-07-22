import pytest
from pydantic import ValidationError

from devagent.integrations.github import (
    GitHubPullRequestWebhook,
    GitHubWebhookResponse,
    GitHubWebhookStatus,
)


def make_payload() -> dict:
    return {
        "action": "opened",
        "repository": {"full_name": "openai/devagent", "ignored": True},
        "pull_request": {
            "number": 42,
            "draft": False,
            "base": {"ref": "main", "sha": "a" * 40},
            "head": {"ref": "feature", "sha": "b" * 40},
            "ignored": "field",
        },
        "installation": {"id": 123},
        "sender": {"login": "octocat"},
    }


def test_webhook_model_accepts_minimal_subset_and_ignores_github_extras() -> None:
    payload = GitHubPullRequestWebhook.model_validate(make_payload())

    assert payload.repository.full_name == "openai/devagent"
    assert payload.pull_request.number == 42
    assert payload.pull_request.head.sha == "b" * 40


def test_webhook_model_rejects_invalid_sha_and_missing_installation() -> None:
    payload = make_payload()
    payload["pull_request"]["head"]["sha"] = "not-sha"
    payload.pop("installation")

    with pytest.raises(ValidationError):
        GitHubPullRequestWebhook.model_validate(payload)


def test_webhook_response_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GitHubWebhookResponse.model_validate(
            {
                "delivery_id": "delivery-1",
                "status": GitHubWebhookStatus.ACCEPTED,
                "unknown": True,
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"delivery_id": "delivery-1", "status": "accepted", "task_id": None},
        {"delivery_id": "delivery-1", "status": "duplicate", "task_id": "task-1"},
        {"delivery_id": "delivery-1", "status": "ignored", "task_id": "task-1"},
    ],
)
def test_webhook_response_requires_task_only_for_accepted(payload: dict) -> None:
    with pytest.raises(ValidationError):
        GitHubWebhookResponse.model_validate(payload)
