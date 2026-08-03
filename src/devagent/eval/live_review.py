import re
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.diagnosis import EvidenceKind
from devagent.llm import LLMClient, LLMResponse
from devagent.review import (
    CodeReviewReport,
    CodeReviewService,
    CodeReviewServiceError,
    LocalCodeReviewEvidenceCollector,
    ReviewCategory,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)
from devagent.review.service import CodeReviewEvidenceCollector
from devagent.tools.git_tools import GitCompareResult, git_compare
from devagent.tools.knowledge_tools import KnowledgeRetriever
from devagent.tools.read_file_tools import read_file

MAX_LIVE_REVIEW_ATTEMPTS = 3
LIVE_REVIEW_PATHS = ("src", "tests")
LiveReviewClientFactory = Callable[[], LLMClient]


class LiveReviewModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class LiveReviewExpectedFinding(LiveReviewModel):
    category: ReviewCategory
    severities: list[ReviewSeverity] = Field(min_length=1)
    file_path: str = Field(min_length=1, max_length=1_000)
    line: int = Field(ge=1)
    side: ReviewLineSide = ReviewLineSide.HEAD
    keywords: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_values(self) -> "LiveReviewExpectedFinding":
        if len(self.severities) != len(set(self.severities)):
            raise ValueError("severities 不能重复")
        normalized_keywords = [keyword.strip() for keyword in self.keywords]
        if any(not keyword for keyword in normalized_keywords) or len(
            normalized_keywords
        ) != len(set(normalized_keywords)):
            raise ValueError("keywords 必须是非空且不重复的字符串")
        self.keywords = normalized_keywords
        return self


class LiveCodeReviewMetrics(LiveReviewModel):
    reviewed: bool = Field(strict=True)
    required_evidence_covered: bool = Field(strict=True)
    evidence_references_grounded: bool = Field(strict=True)
    expected_finding_matched: bool = Field(strict=True)
    finding_count: int = Field(ge=0)
    unexpected_finding_count: int = Field(ge=0)
    expected_keyword_hit_count: int = Field(ge=0)
    expected_keyword_count: int = Field(ge=1)
    expected_keyword_hit_rate: float = Field(ge=0, le=1)
    passed: bool = Field(strict=True)


class LiveCodeReviewRun(LiveReviewModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    api_mode: str = Field(min_length=1, max_length=100)
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    workspace_label: str = Field(min_length=1, max_length=500)
    expected_finding: LiveReviewExpectedFinding
    latency_ms: float = Field(ge=0)
    attempt_count: int = Field(ge=0, le=MAX_LIVE_REVIEW_ATTEMPTS)
    attempt_errors: list[str] = Field(default_factory=list)
    report: CodeReviewReport | None = None
    metrics: LiveCodeReviewMetrics

    @model_validator(mode="after")
    def validate_run_shape(self) -> "LiveCodeReviewRun":
        if self.metrics.passed and self.report is None:
            raise ValueError("通过的 Local Review live evaluation 必须包含报告")
        return self


class _CountingLLMClient:
    def __init__(self, delegate: LLMClient) -> None:
        self._delegate = delegate
        self.call_count = 0

    def chat(self, messages: list[dict]) -> LLMResponse:
        self.call_count += 1
        return self._delegate.chat(messages)


def run_live_code_review(
    *,
    llm_client_factory: LiveReviewClientFactory,
    base_ref: str,
    head_ref: str,
    workspace: str | Path,
    workspace_label: str,
    provider: str,
    model: str,
    api_mode: str,
    expected_finding: LiveReviewExpectedFinding,
    evidence_collector: CodeReviewEvidenceCollector | None = None,
    max_attempts: int = 2,
) -> LiveCodeReviewRun:
    """通过真实 CodeReviewService 执行固定本地变更审查并评分。"""
    if (
        isinstance(max_attempts, bool)
        or max_attempts < 1
        or max_attempts > MAX_LIVE_REVIEW_ATTEMPTS
    ):
        raise ValueError(f"max_attempts 必须在 1 到 {MAX_LIVE_REVIEW_ATTEMPTS} 之间")
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Live Code Review workspace 不存在或不是目录")

    counting_client = _CountingLLMClient(llm_client_factory())
    service = CodeReviewService(
        llm_client=counting_client,
        evidence_collector=evidence_collector or create_live_review_collector(),
        max_report_attempts=max_attempts,
    )
    report: CodeReviewReport | None = None
    attempt_errors: list[str] = []
    started_at = perf_counter()
    try:
        report = service.review(
            base_ref=base_ref,
            head_ref=head_ref,
            workspace=root,
        )
    except CodeReviewServiceError as exc:
        attempt_errors.append(exc.code.value)
        attempt_errors.extend(exc.details)
    latency_ms = (perf_counter() - started_at) * 1000
    if report is not None:
        report = _sanitize_report(report, root, workspace_label)
    attempt_count = counting_client.call_count
    return LiveCodeReviewRun(
        provider=provider,
        model=model,
        api_mode=api_mode,
        base_ref=base_ref,
        head_ref=head_ref,
        workspace_label=workspace_label,
        expected_finding=expected_finding,
        latency_ms=latency_ms,
        attempt_count=attempt_count,
        attempt_errors=attempt_errors,
        report=report,
        metrics=evaluate_live_code_review(report, expected_finding),
    )


def evaluate_live_code_review(
    report: CodeReviewReport | None,
    expected: LiveReviewExpectedFinding,
) -> LiveCodeReviewMetrics:
    """评分真实 Review 的证据覆盖、缺陷定位、关键词和额外误报。"""
    if report is None:
        return _empty_metrics(expected)

    evidence_ids = {item.evidence_id for item in report.evidence}
    referenced_ids = {
        evidence_id
        for finding in report.findings
        for evidence_id in finding.evidence_ids
    }
    evidence_kinds = {item.kind for item in report.evidence}
    required_evidence_covered = EvidenceKind.GIT_DIFF in evidence_kinds and bool(
        {EvidenceKind.CODE, EvidenceKind.KNOWLEDGE} & evidence_kinds
    )
    evidence_references_grounded = bool(referenced_ids) and (
        referenced_ids <= evidence_ids
    )
    matched_findings = [
        finding
        for finding in report.findings
        if _finding_matches_expected(finding, expected)
    ]
    searchable_text = " ".join(
        [
            report.summary,
            *(finding.title for finding in report.findings),
            *(finding.description for finding in report.findings),
            *(finding.suggestion for finding in report.findings),
        ]
    ).casefold()
    keyword_hits = sum(
        keyword.casefold() in searchable_text for keyword in expected.keywords
    )
    reviewed = report.status == ReviewStatus.REVIEWED
    unexpected_finding_count = len(report.findings) - len(matched_findings)
    passed = all(
        (
            reviewed,
            required_evidence_covered,
            evidence_references_grounded,
            bool(matched_findings),
            unexpected_finding_count == 0,
            keyword_hits == len(expected.keywords),
        )
    )
    return LiveCodeReviewMetrics(
        reviewed=reviewed,
        required_evidence_covered=required_evidence_covered,
        evidence_references_grounded=evidence_references_grounded,
        expected_finding_matched=bool(matched_findings),
        finding_count=len(report.findings),
        unexpected_finding_count=unexpected_finding_count,
        expected_keyword_hit_count=keyword_hits,
        expected_keyword_count=len(expected.keywords),
        expected_keyword_hit_rate=keyword_hits / len(expected.keywords),
        passed=passed,
    )


def create_live_review_collector(
    *,
    knowledge_retriever: KnowledgeRetriever | None = None,
) -> LocalCodeReviewEvidenceCollector:
    """创建排除人工答案、但保留源码行号的固定评测证据采集器。"""
    return LocalCodeReviewEvidenceCollector(
        git_compare_reader=_read_live_review_compare,
        file_reader=_read_live_review_file,
        knowledge_retriever=knowledge_retriever,
    )


def render_live_code_review_report(
    run: LiveCodeReviewRun,
    *,
    generated_at: str,
    commit_id: str,
) -> str:
    """渲染不包含凭据和本机绝对路径的真实 Local Review 报告。"""
    metrics = run.metrics
    lines = [
        "# Live Local Code Review Evaluation",
        "",
        f"- Generated at: `{generated_at}`",
        f"- DevAgent commit: `{commit_id}`",
        f"- Provider: `{run.provider}`",
        f"- Model: `{run.model}`",
        f"- API mode: `{run.api_mode}`",
        f"- Compare: `{run.base_ref}...{run.head_ref}`",
        f"- Workspace: `{run.workspace_label}`",
        f"- Latency: {run.latency_ms:.2f} ms",
        f"- Model attempts: {run.attempt_count}",
        f"- Attempt errors: {_render_values(run.attempt_errors)}",
        "",
        "## Acceptance Metrics",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Reviewed | {metrics.reviewed} |",
        f"| Git + Code Evidence Covered | {metrics.required_evidence_covered} |",
        f"| Evidence References Grounded | {metrics.evidence_references_grounded} |",
        f"| Expected Finding Matched | {metrics.expected_finding_matched} |",
        f"| Findings | {metrics.finding_count} |",
        f"| Unexpected Findings | {metrics.unexpected_finding_count} |",
        (
            "| Expected Keyword Hit Rate | "
            f"{metrics.expected_keyword_hit_rate * 100:.1f}% "
            f"({metrics.expected_keyword_hit_count}/{metrics.expected_keyword_count}) |"
        ),
        f"| End-to-End Passed | {metrics.passed} |",
        "",
    ]
    if run.report is not None:
        lines.extend(
            [
                "## Review Result",
                "",
                f"- Review ID: `{run.report.review_id}`",
                f"- Status: `{run.report.status.value}`",
                f"- Evidence: {_render_values([item.evidence_id for item in run.report.evidence])}",
                "",
                "### Summary",
                "",
                run.report.summary,
                "",
                "### Findings",
                "",
                *[
                    (
                        f"- `{finding.finding_id}` `{finding.severity.value}` / "
                        f"`{finding.category.value}` "
                        f"`{finding.file_path}:{finding.line_start}` "
                        f"[{', '.join(finding.evidence_ids)}]: {finding.title}. "
                        f"{finding.description} Suggestion: {finding.suggestion}"
                    )
                    for finding in run.report.findings
                ],
                "",
            ]
        )
    lines.extend(
        [
            "## Acceptance Boundary",
            "",
            "This report was produced by a live LLM provider through CodeReviewService, "
            "git_compare, and read_file.",
            "The fixed case excludes narrative answer files and comment-only answer lines, "
            "then scores evidence grounding, severity, category, diff location, keywords, "
            "unexpected findings, retries, and latency.",
            "It validates this listed local change and provider run rather than universal "
            "review accuracy or a real GitHub publication path.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_live_review_compare(
    base_ref: str,
    head_ref: str,
    workspace: str | Path,
) -> GitCompareResult:
    result = git_compare(
        base_ref,
        head_ref,
        workspace,
        pathspecs=LIVE_REVIEW_PATHS,
    )
    patch = _strip_comment_only_patch_lines(result.patch)
    original_chars = len(patch) if not result.truncated else result.original_patch_chars
    return result.model_copy(
        update={
            "patch": patch,
            "original_patch_chars": original_chars,
            "returned_patch_chars": len(patch),
        }
    )


def _read_live_review_file(file_path: str | Path, **kwargs) -> str:
    content = read_file(file_path, **kwargs)
    return _strip_numbered_comment_only_lines(content)


def _strip_comment_only_patch_lines(patch: str) -> str:
    lines: list[str] = []
    for line in patch.splitlines(keepends=True):
        is_file_marker = line.startswith(("+++", "---"))
        is_diff_content = line.startswith(("+", "-", " "))
        if is_diff_content and not is_file_marker and line[1:].lstrip().startswith("#"):
            continue
        lines.append(line)
    return "".join(lines)


def _strip_numbered_comment_only_lines(content: str) -> str:
    return "\n".join(
        re.sub(r"^(\d+:)\s*#.*$", r"\1", line) for line in content.splitlines()
    )


def _finding_matches_expected(finding, expected: LiveReviewExpectedFinding) -> bool:
    finding_end = finding.line_end or finding.line_start
    return all(
        (
            finding.category == expected.category,
            finding.severity in expected.severities,
            finding.file_path == expected.file_path,
            finding.side == expected.side,
            finding.line_start <= expected.line <= finding_end,
        )
    )


def _sanitize_report(
    report: CodeReviewReport,
    workspace: Path,
    workspace_label: str,
) -> CodeReviewReport:
    payload = _replace_text(
        report.model_dump(mode="json"), str(workspace), workspace_label
    )
    return CodeReviewReport.model_validate(payload)


def _replace_text(value, target: str, replacement: str):
    if isinstance(value, str):
        return value.replace(target, replacement)
    if isinstance(value, list):
        return [_replace_text(item, target, replacement) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_text(item, target, replacement) for key, item in value.items()
        }
    return value


def _empty_metrics(expected: LiveReviewExpectedFinding) -> LiveCodeReviewMetrics:
    return LiveCodeReviewMetrics(
        reviewed=False,
        required_evidence_covered=False,
        evidence_references_grounded=False,
        expected_finding_matched=False,
        finding_count=0,
        unexpected_finding_count=0,
        expected_keyword_hit_count=0,
        expected_keyword_count=len(expected.keywords),
        expected_keyword_hit_rate=0,
        passed=False,
    )


def _render_values(values: list[str]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{value}`" for value in values)
