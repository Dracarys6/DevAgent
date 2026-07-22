import hashlib
import hmac
import json
from pathlib import Path
import subprocess
from typing import Any

from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes.github_webhooks import (
    get_delivery_store,
    get_github_review_task_manager,
    get_github_webhook_secret,
)
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
    LocalCodeReviewEvidenceCollector,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)

WEBHOOK_SECRET = "integration-webhook-secret"
WEBHOOK_URL = "/api/v1/integrations/github/webhooks"
REPOSITORY = "openai/devagent-review-smoke"


class EvidenceEchoLLMClient:
    """从 Prompt 读取真实采集证据，返回固定 finding。"""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        self.calls.append(messages)
        content = messages[1]["content"]
        start = content.index("代码审查输入：\n") + len("代码审查输入：\n")
        end = content.index("\nCodeReviewReport JSON Schema：", start)
        review_input = CodeReviewInput.model_validate_json(content[start:end])
        report = CodeReviewReport(
            review_id=review_input.review_id,
            base_ref=review_input.base_ref,
            head_ref=review_input.head_ref,
            status=ReviewStatus.REVIEWED,
            summary="发现除零保护被删除。",
            findings=[
                ReviewFinding(
                    finding_id="R1",
                    severity=ReviewSeverity.HIGH,
                    category=ReviewCategory.CORRECTNESS,
                    title="除零保护被删除",
                    description="count 为零时会抛出 ZeroDivisionError。",
                    file_path="calculator.py",
                    line_start=2,
                    side=ReviewLineSide.HEAD,
                    evidence_ids=["E1"],
                    suggestion="恢复 count == 0 的显式校验。",
                    verification_steps=["运行 count=0 的回归测试"],
                )
            ],
            evidence=review_input.evidence,
            missing_evidence=review_input.missing_evidence,
        )
        return LLMResponse.final_answer(report.model_dump_json())


def run_git(workspace: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def commit_file(workspace: Path, content: str, message: str) -> str:
    (workspace / "calculator.py").write_text(content, encoding="utf-8")
    run_git(workspace, "add", "calculator.py")
    run_git(workspace, "commit", "-m", message)
    return run_git(workspace, "rev-parse", "HEAD")


def make_repository(tmp_path: Path) -> tuple[Path, str, str, str]:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run_git(workspace, "init")
    run_git(workspace, "config", "user.email", "devagent@example.test")
    run_git(workspace, "config", "user.name", "DevAgent Test")
    base_sha = commit_file(
        workspace,
        "def divide(total, count):\n    if count == 0:\n        raise ValueError('count')\n    return total / count\n",
        "safe base",
    )
    first_head = commit_file(
        workspace,
        "def divide(total, count):\n    return total / count\n",
        "remove zero guard",
    )
    second_head = commit_file(
        workspace,
        "def divide(total, count):\n    return float(total) / count\n",
        "update implementation",
    )
    return workspace, base_sha, first_head, second_head


def make_payload(base_sha: str, head_sha: str, action: str) -> bytes:
    return json.dumps(
        {
            "action": action,
            "repository": {"full_name": REPOSITORY},
            "pull_request": {
                "number": 42,
                "draft": False,
                "base": {"ref": "main", "sha": base_sha},
                "head": {"ref": "feature/review", "sha": head_sha},
            },
            "installation": {"id": 123},
        },
        separators=(",", ":"),
    ).encode()


def webhook_headers(body: bytes, delivery_id: str) -> dict[str, str]:
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={signature}",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "Content-Type": "application/json",
    }


def test_fixed_github_pr_review_runs_opened_duplicate_and_synchronize(
    tmp_path: Path,
) -> None:
    workspace, base_sha, first_head, second_head = make_repository(tmp_path)
    fake_github = FakeGitHubClient(
        {
            (REPOSITORY, 42): GitHubPullRequestData(
                base_ref=base_sha,
                head_ref=first_head,
                head_sha=first_head,
                workspace=str(workspace),
                diff_lines=[
                    GitHubDiffLine(
                        path="calculator.py",
                        line=2,
                        side=GitHubDiffSide.RIGHT,
                    )
                ],
            )
        }
    )
    llm = EvidenceEchoLLMClient()
    store = InMemoryWebhookDeliveryStore()
    manager = GitHubReviewTaskManager(
        source=GitHubPullRequestSource(fake_github),
        service=CodeReviewService(
            llm_client=llm,
            evidence_collector=LocalCodeReviewEvidenceCollector(),
        ),
        publisher=GitHubReviewPublisher(fake_github),
        delivery_store=store,
    )
    app.dependency_overrides[get_github_webhook_secret] = lambda: WEBHOOK_SECRET
    app.dependency_overrides[get_delivery_store] = lambda: store
    app.dependency_overrides[get_github_review_task_manager] = lambda: manager

    try:
        opened_body = make_payload(base_sha, first_head, "opened")
        with TestClient(app) as client:
            opened = client.post(
                WEBHOOK_URL,
                content=opened_body,
                headers=webhook_headers(opened_body, "delivery-opened"),
            )
            opened_status = client.get(
                "/api/v1/integrations/github/review-tasks/"
                f"{opened.json()['task_id']}"
            )
            duplicate = client.post(
                WEBHOOK_URL,
                content=opened_body,
                headers=webhook_headers(opened_body, "delivery-opened"),
            )

            fake_github.pull_requests[(REPOSITORY, 42)] = GitHubPullRequestData(
                base_ref=base_sha,
                head_ref=second_head,
                head_sha=second_head,
                workspace=str(workspace),
                diff_lines=[
                    GitHubDiffLine(
                        path="calculator.py",
                        line=2,
                        side=GitHubDiffSide.RIGHT,
                    )
                ],
            )
            synchronize_body = make_payload(base_sha, second_head, "synchronize")
            synchronize = client.post(
                WEBHOOK_URL,
                content=synchronize_body,
                headers=webhook_headers(
                    synchronize_body, "delivery-synchronize"
                ),
            )
    finally:
        app.dependency_overrides.clear()

    assert opened.status_code == 202
    assert duplicate.json()["status"] == "duplicate"
    assert synchronize.status_code == 202
    first_task = manager.get_task(opened.json()["task_id"])
    second_task = manager.get_task(synchronize.json()["task_id"])
    assert first_task.status == GitHubReviewTaskStatus.COMPLETED
    assert second_task.status == GitHubReviewTaskStatus.COMPLETED
    assert first_task.installation_id == 123
    assert first_task.report_id
    assert second_task.report_id
    assert opened_status.status_code == 200
    assert opened_status.json()["report_id"] == first_task.report_id
    assert len(llm.calls) == 2
    assert len(fake_github.inline_calls) == 2
    assert fake_github.inline_calls[0]["commit_id"] == first_head
    assert fake_github.inline_calls[1]["commit_id"] == second_head
    assert len(fake_github.summary_calls) == 2
    assert len(fake_github.summary_comments) == 1
    latest_summary = next(iter(fake_github.summary_comments.values()))
    assert second_task.report_id in latest_summary
    assert second_head in latest_summary
