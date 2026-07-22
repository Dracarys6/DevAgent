from devagent.review import (
    CodeReviewReport,
    PullRequestLocator,
    PullRequestSnapshot,
    ReviewFinding,
    ReviewLineSide,
    ReviewPublishResult,
)

from .client import (
    GitHubClient,
    GitHubClientError,
    GitHubDiffSide,
    GitHubInlineCommentError,
    GitHubPullRequestData,
)

GITHUB_REVIEW_MARKER = "<!-- devagent-code-review -->"


class GitHubReviewPublishError(RuntimeError):
    """GitHub 建议发布无法可信完成。"""


class GitHubPullRequestSource:
    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def get_pull_request(self, locator: PullRequestLocator) -> PullRequestSnapshot:
        if locator.platform != "github":
            raise ValueError("仅支持 GitHub 平台的 Pull Request")
        try:
            data = GitHubPullRequestData.model_validate(
                self._client.get_pull_request(
                    repository=locator.repository,
                    number=locator.number,
                )
            )
        except Exception as exc:
            raise GitHubClientError("无法读取 GitHub Pull Request") from exc
        return PullRequestSnapshot(
            locator=locator,
            base_ref=data.base_ref,
            head_ref=data.head_ref,
            head_sha=data.head_sha,
            workspace=data.workspace,
        )


class GitHubReviewPublisher:
    """把结构化报告发布为非阻塞摘要与可定位 inline comments。"""

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def publish(
        self,
        *,
        pull_request: PullRequestSnapshot,
        report: CodeReviewReport,
    ) -> ReviewPublishResult:
        _validate_report_identity(pull_request=pull_request, report=report)
        locator = pull_request.locator
        if locator.platform != "github":
            raise GitHubReviewPublishError("仅支持发布 GitHub Pull Request 建议")

        try:
            current = GitHubPullRequestData.model_validate(
                self._client.get_pull_request(
                    repository=locator.repository,
                    number=locator.number,
                )
            )
        except Exception as exc:
            raise GitHubReviewPublishError("无法确认 GitHub Pull Request 当前状态") from exc

        if (
            current.base_ref != pull_request.base_ref
            or current.head_ref != pull_request.head_ref
            or current.head_sha != pull_request.head_sha
        ):
            raise GitHubReviewPublishError("Pull Request 已更新，拒绝向过期 diff 发布建议")

        locations = {(item.path, item.line, item.side) for item in current.diff_lines}
        downgraded: list[ReviewFinding] = []
        inline_count = 0
        for finding in report.findings:
            side = _to_github_side(finding.side)
            line = finding.line_end or finding.line_start
            if (finding.file_path, line, side) not in locations:
                downgraded.append(finding)
                continue
            try:
                self._client.create_review_comment(
                    repository=locator.repository,
                    number=locator.number,
                    commit_id=pull_request.head_sha,
                    path=finding.file_path,
                    line=line,
                    side=side.value,
                    body=_render_inline_comment(finding),
                )
                inline_count += 1
            except GitHubInlineCommentError:
                downgraded.append(finding)
            except Exception as exc:
                raise GitHubReviewPublishError("发布 GitHub inline comment 失败") from exc

        try:
            self._client.upsert_summary_comment(
                repository=locator.repository,
                number=locator.number,
                marker=GITHUB_REVIEW_MARKER,
                body=_render_summary(
                    report=report,
                    head_sha=pull_request.head_sha,
                    inline_count=inline_count,
                    downgraded=downgraded,
                ),
            )
        except Exception as exc:
            raise GitHubReviewPublishError("发布 GitHub 审查摘要失败") from exc

        return ReviewPublishResult(
            summary_published=True,
            inline_comment_count=inline_count,
            downgraded_finding_count=len(downgraded),
        )


def _validate_report_identity(
    *,
    pull_request: PullRequestSnapshot,
    report: CodeReviewReport,
) -> None:
    if (
        report.base_ref != pull_request.base_ref
        or report.head_ref != pull_request.head_ref
    ):
        raise GitHubReviewPublishError("代码审查报告与 Pull Request refs 不匹配")


def _to_github_side(side: ReviewLineSide) -> GitHubDiffSide:
    if side == ReviewLineSide.BASE:
        return GitHubDiffSide.LEFT
    return GitHubDiffSide.RIGHT


def _render_inline_comment(finding: ReviewFinding) -> str:
    steps = "\n".join(f"- {step}" for step in finding.verification_steps)
    evidence_ids = ", ".join(finding.evidence_ids)
    return (
        f"**[{finding.severity.value.upper()}] {finding.title}**\n\n"
        f"{finding.description}\n\n"
        f"建议：{finding.suggestion}\n\n"
        f"验证步骤：\n{steps}\n\n"
        f"Evidence: {evidence_ids}"
    )


def _render_summary(
    *,
    report: CodeReviewReport,
    head_sha: str,
    inline_count: int,
    downgraded: list[ReviewFinding],
) -> str:
    lines = [
        GITHUB_REVIEW_MARKER,
        "## DevAgent 代码审查建议",
        "",
        report.summary,
        "",
        f"- Review ID: `{report.review_id}`",
        f"- Head SHA: `{head_sha}`",
        f"- Inline comments: {inline_count}",
        f"- Summary-only findings: {len(downgraded)}",
    ]
    if downgraded:
        lines.extend(["", "### 未能稳定定位到当前 diff 的建议"])
        for finding in downgraded:
            line = finding.line_end or finding.line_start
            lines.append(
                f"- **[{finding.severity.value.upper()}] {finding.title}** "
                f"(`{finding.file_path}:{line}`): {finding.suggestion}"
            )
    return "\n".join(lines)
