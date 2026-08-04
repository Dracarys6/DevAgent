from pathlib import Path

import pytest

from devagent.diagnosis import Evidence, EvidenceKind
from devagent.integrations.github import (
    DeliveryState,
    GitHubReviewPorts,
    GitHubReviewTaskManager,
    GitHubReviewTaskStatus,
    InMemoryWebhookDeliveryStore,
)
from devagent.review import (
    CodeReviewReport,
    PullRequestLocator,
    PullRequestSnapshot,
    ReviewPublishResult,
    ReviewStatus,
)


def make_locator() -> PullRequestLocator:
    return PullRequestLocator(
        platform="github",
        repository="openai/devagent",
        number=42,
    )


def make_snapshot(tmp_path: Path) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        locator=make_locator(),
        base_ref="main",
        head_ref="feature/payment",
        head_sha="b" * 40,
        workspace=str(tmp_path),
    )


def make_report() -> CodeReviewReport:
    return CodeReviewReport(
        review_id="review-42",
        base_ref="main",
        head_ref="feature/payment",
        status=ReviewStatus.REVIEWED,
        summary="未发现问题。",
        findings=[],
        evidence=[
            Evidence(
                evidence_id="E1",
                kind=EvidenceKind.GIT_DIFF,
                tool_name="git_compare",
                source="b" * 40,
                locator="hunks=1",
                excerpt="+ safe_change = True",
            )
        ],
    )


class FixedSource:
    def __init__(self, snapshot: PullRequestSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[PullRequestLocator] = []

    def get_pull_request(self, locator: PullRequestLocator) -> PullRequestSnapshot:
        self.calls.append(locator)
        return self.snapshot


class FixedService:
    def __init__(self, report: CodeReviewReport) -> None:
        self.report = report
        self.calls: list[dict[str, str]] = []

    def review(self, **kwargs: str) -> CodeReviewReport:
        self.calls.append(kwargs)
        return self.report


class FixedPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish(self, **kwargs: object) -> ReviewPublishResult:
        self.calls.append(kwargs)
        return ReviewPublishResult(
            summary_published=True,
            inline_comment_count=0,
            downgraded_finding_count=0,
        )


class RecordingPortFactory:
    def __init__(self, source: FixedSource, publisher: FixedPublisher) -> None:
        self.source = source
        self.publisher = publisher
        self.calls: list[int] = []

    def create(self, installation_id: int) -> GitHubReviewPorts:
        self.calls.append(installation_id)
        return GitHubReviewPorts(source=self.source, publisher=self.publisher)


def make_manager(tmp_path: Path):
    store = InMemoryWebhookDeliveryStore()
    store.claim("delivery-1")
    source = FixedSource(make_snapshot(tmp_path))
    service = FixedService(make_report())
    publisher = FixedPublisher()
    manager = GitHubReviewTaskManager(
        source=source,
        service=service,
        publisher=publisher,
        delivery_store=store,
    )
    return manager, store, source, service, publisher


def test_task_manager_completes_review_pipeline(tmp_path: Path) -> None:
    manager, store, source, service, publisher = make_manager(tmp_path)

    created = manager.create_task(
        delivery_id="delivery-1",
        installation_id=123,
        locator=make_locator(),
    )
    completed = manager.run_task(created.task_id)

    assert created.status == GitHubReviewTaskStatus.PENDING
    assert completed.status == GitHubReviewTaskStatus.COMPLETED
    assert completed.report_id == "review-42"
    assert completed.error_message is None
    assert source.calls == [make_locator()]
    assert service.calls == [
        {
            "base_ref": "main",
            "head_ref": "feature/payment",
            "workspace": str(tmp_path),
        }
    ]
    assert publisher.calls[0]["pull_request"] == make_snapshot(tmp_path)
    assert publisher.calls[0]["report"] == make_report()
    assert store.get_state("delivery-1") == DeliveryState.COMPLETED


def test_task_manager_builds_ports_for_task_installation(tmp_path: Path) -> None:
    store = InMemoryWebhookDeliveryStore()
    store.claim("delivery-1")
    source = FixedSource(make_snapshot(tmp_path))
    publisher = FixedPublisher()
    factory = RecordingPortFactory(source, publisher)
    manager = GitHubReviewTaskManager(
        port_factory=factory,
        service=FixedService(make_report()),
        delivery_store=store,
    )
    task = manager.create_task(
        delivery_id="delivery-1",
        installation_id=987,
        locator=make_locator(),
    )

    completed = manager.run_task(task.task_id)

    assert completed.status == GitHubReviewTaskStatus.COMPLETED
    assert factory.calls == [987]


def test_task_manager_does_not_repeat_terminal_task(tmp_path: Path) -> None:
    manager, _, source, service, publisher = make_manager(tmp_path)
    task = manager.create_task(
        delivery_id="delivery-1", installation_id=123, locator=make_locator()
    )

    first = manager.run_task(task.task_id)
    second = manager.run_task(task.task_id)

    assert first == second
    assert len(source.calls) == 1
    assert len(service.calls) == 1
    assert len(publisher.calls) == 1


def test_task_manager_failure_is_sanitized_and_releases_delivery(
    tmp_path: Path,
) -> None:
    class RaisingSource(FixedSource):
        def get_pull_request(self, locator: PullRequestLocator) -> PullRequestSnapshot:
            raise RuntimeError("token=secret-provider-response")

    store = InMemoryWebhookDeliveryStore()
    store.claim("delivery-1")
    manager = GitHubReviewTaskManager(
        source=RaisingSource(make_snapshot(tmp_path)),
        service=FixedService(make_report()),
        publisher=FixedPublisher(),
        delivery_store=store,
    )
    task = manager.create_task(
        delivery_id="delivery-1", installation_id=123, locator=make_locator()
    )

    failed = manager.run_task(task.task_id)

    assert failed.status == GitHubReviewTaskStatus.FAILED
    assert "secret-provider-response" not in failed.error_message
    assert store.get_state("delivery-1") is None
    assert store.claim("delivery-1") is True
    retry = manager.create_task(
        delivery_id="delivery-1", installation_id=123, locator=make_locator()
    )
    assert retry.status == GitHubReviewTaskStatus.PENDING
    assert retry.task_id != task.task_id


def test_task_manager_rejects_duplicate_delivery_and_unknown_task(
    tmp_path: Path,
) -> None:
    manager, _, _, _, _ = make_manager(tmp_path)
    manager.create_task(
        delivery_id="delivery-1", installation_id=123, locator=make_locator()
    )

    with pytest.raises(ValueError, match="delivery_id"):
        manager.create_task(
            delivery_id="delivery-1", installation_id=123, locator=make_locator()
        )
    with pytest.raises(KeyError, match="不存在"):
        manager.get_task("unknown")
    with pytest.raises(KeyError, match="不存在"):
        manager.run_task("unknown")
