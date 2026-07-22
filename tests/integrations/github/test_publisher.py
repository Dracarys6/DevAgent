from pathlib import Path

import pytest

from devagent.diagnosis import Evidence, EvidenceKind
from devagent.integrations.github import (
    GITHUB_REVIEW_MARKER,
    FakeGitHubClient,
    GitHubDiffLine,
    GitHubDiffSide,
    GitHubInlineCommentError,
    GitHubPullRequestData,
    GitHubReviewPublisher,
    GitHubReviewPublishError,
)
from devagent.review import (
    CodeReviewReport,
    PullRequestLocator,
    PullRequestSnapshot,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)


def make_snapshot(tmp_path: Path) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        locator=PullRequestLocator(
            platform="github",
            repository="openai/devagent",
            number=42,
        ),
        base_ref="main",
        head_ref="feature/payment",
        head_sha="b" * 40,
        workspace=str(tmp_path),
    )


def make_data(
    tmp_path: Path,
    *,
    head_sha: str = "b" * 40,
    diff_lines: list[GitHubDiffLine] | None = None,
) -> GitHubPullRequestData:
    return GitHubPullRequestData(
        base_ref="main",
        head_ref="feature/payment",
        head_sha=head_sha,
        workspace=str(tmp_path),
        diff_lines=diff_lines or [],
    )


def make_finding(
    finding_id: str,
    *,
    file_path: str,
    line_start: int,
    line_end: int | None = None,
    side: ReviewLineSide = ReviewLineSide.HEAD,
) -> ReviewFinding:
    return ReviewFinding(
        finding_id=finding_id,
        severity=ReviewSeverity.HIGH,
        category=ReviewCategory.CORRECTNESS,
        title=f"问题 {finding_id}",
        description="当前变更会产生错误结果。",
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        side=side,
        evidence_ids=["E1"],
        suggestion="修正当前分支逻辑。",
        verification_steps=["运行对应回归测试"],
    )


def make_report(
    findings: list[ReviewFinding],
    *,
    head_ref: str = "feature/payment",
) -> CodeReviewReport:
    evidence = Evidence(
        evidence_id="E1",
        kind=EvidenceKind.GIT_DIFF,
        tool_name="git_compare",
        source="b" * 40,
        locator="path=src/payment.py;line=12;side=head",
        excerpt="+ return wrong_value",
    )
    return CodeReviewReport(
        review_id="review-42",
        base_ref="main",
        head_ref=head_ref,
        status=ReviewStatus.REVIEWED,
        summary="发现需要处理的代码风险。",
        findings=findings,
        evidence=[evidence],
    )


def test_publisher_maps_head_and_base_findings_to_inline_comments(
    tmp_path: Path,
) -> None:
    snapshot = make_snapshot(tmp_path)
    client = FakeGitHubClient(
        {
            ("openai/devagent", 42): make_data(
                tmp_path,
                diff_lines=[
                    GitHubDiffLine(
                        path="src/payment.py",
                        line=12,
                        side=GitHubDiffSide.RIGHT,
                    ),
                    GitHubDiffLine(
                        path="src/legacy.py",
                        line=5,
                        side=GitHubDiffSide.LEFT,
                    ),
                ],
            )
        }
    )
    report = make_report(
        [
            make_finding(
                "R1",
                file_path="src/payment.py",
                line_start=10,
                line_end=12,
            ),
            make_finding(
                "R2",
                file_path="src/legacy.py",
                line_start=5,
                side=ReviewLineSide.BASE,
            ),
        ]
    )

    result = GitHubReviewPublisher(client).publish(
        pull_request=snapshot,
        report=report,
    )

    assert result.summary_published is True
    assert result.inline_comment_count == 2
    assert result.downgraded_finding_count == 0
    assert client.inline_calls[0]["line"] == 12
    assert client.inline_calls[0]["side"] == "RIGHT"
    assert client.inline_calls[1]["side"] == "LEFT"
    assert client.inline_calls[0]["commit_id"] == "b" * 40
    assert client.summary_calls[0]["marker"] == GITHUB_REVIEW_MARKER
    assert "review-42" in client.summary_calls[0]["body"]
    assert "b" * 40 in client.summary_calls[0]["body"]


def test_publisher_downgrades_unmapped_finding_into_summary(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    client = FakeGitHubClient(
        {("openai/devagent", 42): make_data(tmp_path, diff_lines=[])}
    )
    report = make_report(
        [make_finding("R1", file_path="src/missing.py", line_start=99)]
    )

    result = GitHubReviewPublisher(client).publish(
        pull_request=snapshot,
        report=report,
    )

    assert result.inline_comment_count == 0
    assert result.downgraded_finding_count == 1
    assert client.inline_calls == []
    assert "src/missing.py:99" in client.summary_calls[0]["body"]
    assert "问题 R1" in client.summary_calls[0]["body"]
    assert result.inline_comment_count + result.downgraded_finding_count == len(
        report.findings
    )


def test_publisher_downgrades_inline_location_rejection(tmp_path: Path) -> None:
    class RejectingInlineClient(FakeGitHubClient):
        def create_review_comment(self, **kwargs: object) -> str:
            raise GitHubInlineCommentError("provider-response-secret")

    snapshot = make_snapshot(tmp_path)
    client = RejectingInlineClient(
        {
            ("openai/devagent", 42): make_data(
                tmp_path,
                diff_lines=[
                    GitHubDiffLine(
                        path="src/payment.py",
                        line=12,
                        side=GitHubDiffSide.RIGHT,
                    )
                ],
            )
        }
    )
    report = make_report(
        [make_finding("R1", file_path="src/payment.py", line_start=12)]
    )

    result = GitHubReviewPublisher(client).publish(
        pull_request=snapshot,
        report=report,
    )

    assert result.inline_comment_count == 0
    assert result.downgraded_finding_count == 1
    assert "问题 R1" in client.summary_calls[0]["body"]


def test_publisher_rejects_stale_pull_request_and_report_refs(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path)
    stale_client = FakeGitHubClient(
        {
            ("openai/devagent", 42): make_data(
                tmp_path,
                head_sha="c" * 40,
            )
        }
    )

    with pytest.raises(GitHubReviewPublishError, match="已更新"):
        GitHubReviewPublisher(stale_client).publish(
            pull_request=snapshot,
            report=make_report([]),
        )

    current_client = FakeGitHubClient(
        {("openai/devagent", 42): make_data(tmp_path)}
    )
    with pytest.raises(GitHubReviewPublishError, match="refs 不匹配"):
        GitHubReviewPublisher(current_client).publish(
            pull_request=snapshot,
            report=make_report([], head_ref="other-feature"),
        )

    assert stale_client.summary_calls == []
    assert current_client.summary_calls == []


def test_publisher_sanitizes_summary_client_error(tmp_path: Path) -> None:
    class RaisingSummaryClient(FakeGitHubClient):
        def upsert_summary_comment(self, **kwargs: object) -> str:
            raise RuntimeError("token=secret-provider-response")

    snapshot = make_snapshot(tmp_path)
    client = RaisingSummaryClient(
        {("openai/devagent", 42): make_data(tmp_path)}
    )

    with pytest.raises(GitHubReviewPublishError) as exc_info:
        GitHubReviewPublisher(client).publish(
            pull_request=snapshot,
            report=make_report([]),
        )

    assert "secret-provider-response" not in str(exc_info.value)


def test_publisher_uses_stable_summary_marker_and_has_no_merge_capability(
    tmp_path: Path,
) -> None:
    snapshot = make_snapshot(tmp_path)
    client = FakeGitHubClient(
        {("openai/devagent", 42): make_data(tmp_path)}
    )
    publisher = GitHubReviewPublisher(client)

    publisher.publish(pull_request=snapshot, report=make_report([]))
    publisher.publish(pull_request=snapshot, report=make_report([]))

    assert [call["marker"] for call in client.summary_calls] == [
        GITHUB_REVIEW_MARKER,
        GITHUB_REVIEW_MARKER,
    ]
    assert len(client.summary_comments) == 1
    assert not hasattr(client, "approve")
    assert not hasattr(client, "merge")
