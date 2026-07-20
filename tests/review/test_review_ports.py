import pytest
from pydantic import ValidationError

from devagent.review import (
    PullRequestLocator,
    PullRequestSnapshot,
    ReviewPublishResult,
    WebhookDeliveryStore,
)


def make_locator(**overrides: object) -> PullRequestLocator:
    data: dict[str, object] = {
        "platform": "github",
        "repository": "owner/project",
        "number": 42,
    }
    data.update(overrides)
    return PullRequestLocator.model_validate(data)


def make_snapshot(**overrides: object) -> PullRequestSnapshot:
    data: dict[str, object] = {
        "locator": make_locator(),
        "base_ref": "main",
        "head_ref": "feature/payment",
        "head_sha": "a" * 40,
        "workspace": "/tmp/review-workspace",
    }
    data.update(overrides)
    return PullRequestSnapshot.model_validate(data)


def test_pull_request_snapshot_preserves_platform_identity() -> None:
    snapshot = make_snapshot()

    assert snapshot.locator.repository == "owner/project"
    assert snapshot.locator.number == 42
    assert snapshot.base_ref == "main"
    assert snapshot.head_ref == "feature/payment"
    assert snapshot.head_sha == "a" * 40


@pytest.mark.parametrize(
    "overrides",
    [
        {"platform": ""},
        {"platform": " github"},
        {"repository": ""},
        {"repository": "owner/project "},
        {"number": 0},
    ],
)
def test_pull_request_locator_rejects_invalid_identity(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        make_locator(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_ref": " main"},
        {"head_ref": "feature/payment "},
        {"head_ref": "main"},
        {"head_sha": "not-a-sha"},
        {"head_sha": "a" * 6},
        {"workspace": " workspace"},
    ],
)
def test_pull_request_snapshot_rejects_invalid_review_identity(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        make_snapshot(**overrides)


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (make_locator, "unexpected"),
        (make_snapshot, "unexpected"),
    ],
)
def test_review_port_models_forbid_unknown_fields(model, field: str) -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model(**{field: True})


def test_review_publish_result_tracks_publish_outcomes() -> None:
    result = ReviewPublishResult(
        summary_published=True,
        inline_comment_count=3,
        downgraded_finding_count=1,
    )

    assert result.model_dump() == {
        "summary_published": True,
        "inline_comment_count": 3,
        "downgraded_finding_count": 1,
    }


@pytest.mark.parametrize(
    "field",
    ["inline_comment_count", "downgraded_finding_count"],
)
def test_review_publish_result_rejects_negative_counts(field: str) -> None:
    payload = {
        "summary_published": True,
        "inline_comment_count": 0,
        "downgraded_finding_count": 0,
        field: -1,
    }
    with pytest.raises(ValidationError):
        ReviewPublishResult.model_validate(payload)


class FakeWebhookDeliveryStore:
    def __init__(self) -> None:
        self._claimed: set[str] = set()

    def claim(self, delivery_id: str) -> bool:
        if delivery_id in self._claimed:
            return False
        self._claimed.add(delivery_id)
        return True

    def mark_completed(self, delivery_id: str) -> None:
        self._claimed.add(delivery_id)

    def release(self, delivery_id: str) -> None:
        self._claimed.discard(delivery_id)


def use_delivery_store(store: WebhookDeliveryStore, delivery_id: str) -> bool:
    return store.claim(delivery_id)


def test_webhook_delivery_store_claim_is_idempotent() -> None:
    store = FakeWebhookDeliveryStore()

    assert use_delivery_store(store, "delivery-1") is True
    assert use_delivery_store(store, "delivery-1") is False


def test_webhook_delivery_store_release_allows_retry() -> None:
    store = FakeWebhookDeliveryStore()
    assert store.claim("delivery-1") is True

    store.release("delivery-1")

    assert store.claim("delivery-1") is True
