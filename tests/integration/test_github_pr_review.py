import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes.github_webhooks import (
    get_delivery_store,
    get_github_review_task_manager,
    get_github_webhook_secret,
)
from devagent.diagnosis import Evidence, EvidenceKind
from devagent.integrations.github import (
    FakeGitHubClient,
    GitHubDiffLine,
    GitHubDiffSide,
    GitHubPullRequestData,
    GitHubPullRequestSource,
    GitHubReviewPublisher,
    GitHubReviewTaskManager,
    GitHubReviewTaskStatus,
    InMemoryWebhookDeliveryStore,
)
from devagent.llm import LLMResponse
from devagent.review import (
    CodeReviewInput,
    CodeReviewReport,
    CodeReviewService,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)

WEBHOOK_SECRET = "integration-webhook-secret"
WEBHOOK_URL = "/api/v1/integrations/github/webhooks"
REPOSITORY = "openai/devagent"
BASE_SHA = "a" * 40
FIRST_HEAD_SHA = "b" * 40
SECOND_HEAD_SHA = "c" * 40


class DynamicCollector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def collect(self, **kwargs: object) -> CodeReviewInput:
        self.calls.append(kwargs)
        head_ref = str(kwargs["head_ref"])
        return CodeReviewInput(
            review_id=str(kwargs["review_id"]),
            base_ref=str(kwargs["base_ref"]),
            head_ref=head_ref,
            workspace=str(kwargs["workspace"]),
            evidence=[
                Evidence(
                    evidence_id="E1",
                    kind=EvidenceKind.GIT_DIFF,
                    tool_name="git_compare",
                    source=head_ref,
                    locator="path=src/app.py;line=12",
                    excerpt="+ return unsafe_value",
                )
            ],
        )


class SequenceLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse.final_answer(self.responses[len(self.calls) - 1])


def make_report(*, review_id: str, head_sha: str) -> str:
    evidence = Evidence(
        evidence_id="E1",
        kind=EvidenceKind.GIT_DIFF,
        tool_name="git_compare",
        source=head_sha,
        locator="path=src/app.py;line=12",
        excerpt="+ return unsafe_value",
    )
    report = CodeReviewReport(
        review_id=review_id,
        base_ref=BASE_SHA,
        head_ref=head_sha,
        status=ReviewStatus.REVIEWED,
        summary="发现一个需要修正的正确性问题。",
        findings=[
            ReviewFinding(
                finding_id="R1",
                severity=ReviewSeverity.HIGH,
                category=ReviewCategory.CORRECTNESS,
                title="错误返回未经过校验的值",
                description="新增返回路径绕过了必要校验。",
                file_path="src/app.py",
                line_start=12,
                side=ReviewLineSide.HEAD,
                evidence_ids=["E1"],
                suggestion="在返回前执行既有校验。",
                verification_steps=["运行非法输入回归测试"],
            )
        ],
        evidence=[evidence],
    )
    return report.model_dump_json()


def make_pr_data(tmp_path: Path, head_sha: str) -> GitHubPullRequestData:
    return GitHubPullRequestData(
        base_ref=BASE_SHA,
        head_ref=head_sha,
        head_sha=head_sha,
        workspace=str(tmp_path),
        diff_lines=[
            GitHubDiffLine(
                path="src/app.py",
                line=12,
                side=GitHubDiffSide.RIGHT,
            )
        ],
    )


def make_payload(action: str, head_sha: str) -> bytes:
    payload = {
        "action": action,
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": 42,
            "draft": False,
            "base": {"ref": "main", "sha": BASE_SHA},
            "head": {"ref": "feature/review", "sha": head_sha},
        },
        "installation": {"id": 123},
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def make_headers(body: bytes, delivery_id: str) -> dict[str, str]:
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={signature}",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "Content-Type": "application/json",
    }


def test_github_pr_review_opened_duplicate_and_synchronize(tmp_path: Path) -> None:
    fake_client = FakeGitHubClient(
        {(REPOSITORY, 42): make_pr_data(tmp_path, FIRST_HEAD_SHA)}
    )
    collector = DynamicCollector()
    llm_client = SequenceLLMClient(
        [
            make_report(review_id="review-opened", head_sha=FIRST_HEAD_SHA),
            make_report(review_id="review-sync", head_sha=SECOND_HEAD_SHA),
        ]
    )
    review_ids = iter(["review-opened", "review-sync"])
    service = CodeReviewService(
        llm_client=llm_client,
        evidence_collector=collector,
        review_id_factory=lambda: next(review_ids),
    )
    store = InMemoryWebhookDeliveryStore()
    manager = GitHubReviewTaskManager(
        source=GitHubPullRequestSource(fake_client),
        service=service,
        publisher=GitHubReviewPublisher(fake_client),
        delivery_store=store,
    )
    app.dependency_overrides[get_github_webhook_secret] = lambda: WEBHOOK_SECRET
    app.dependency_overrides[get_delivery_store] = lambda: store
    app.dependency_overrides[get_github_review_task_manager] = lambda: manager

    try:
        with TestClient(app) as client:
            opened_body = make_payload("opened", FIRST_HEAD_SHA)
            opened = client.post(
                WEBHOOK_URL,
                content=opened_body,
                headers=make_headers(opened_body, "delivery-opened"),
            )
            opened_status = client.get(
                "/api/v1/integrations/github/review-tasks/"
                f"{opened.json()['task_id']}"
            )
            duplicate = client.post(
                WEBHOOK_URL,
                content=opened_body,
                headers=make_headers(opened_body, "delivery-opened"),
            )

            fake_client.pull_requests[(REPOSITORY, 42)] = make_pr_data(
                tmp_path, SECOND_HEAD_SHA
            )
            sync_body = make_payload("synchronize", SECOND_HEAD_SHA)
            synchronized = client.post(
                WEBHOOK_URL,
                content=sync_body,
                headers=make_headers(sync_body, "delivery-sync"),
            )
    finally:
        app.dependency_overrides.clear()

    assert opened.status_code == 202
    assert opened.json()["status"] == "accepted"
    opened_task = manager.get_task(opened.json()["task_id"])
    assert opened_task.status == GitHubReviewTaskStatus.COMPLETED
    assert opened_task.installation_id == 123
    assert opened_task.report_id == "review-opened"
    assert opened_status.status_code == 200
    assert opened_status.json()["status"] == "completed"
    assert opened_status.json()["report_id"] == "review-opened"

    assert duplicate.status_code == 202
    assert duplicate.json()["status"] == "duplicate"

    assert synchronized.status_code == 202
    assert synchronized.json()["status"] == "accepted"
    sync_task = manager.get_task(synchronized.json()["task_id"])
    assert sync_task.status == GitHubReviewTaskStatus.COMPLETED
    assert sync_task.report_id == "review-sync"

    assert len(llm_client.calls) == 2
    assert len(collector.calls) == 2
    assert len(fake_client.summary_calls) == 2
    assert len(fake_client.summary_comments) == 1
    assert len(fake_client.inline_calls) == 2
    assert fake_client.inline_calls[0]["commit_id"] == FIRST_HEAD_SHA
    assert fake_client.inline_calls[1]["commit_id"] == SECOND_HEAD_SHA
    latest_summary = next(iter(fake_client.summary_comments.values()))
    assert "review-sync" in latest_summary
    assert SECOND_HEAD_SHA in latest_summary
