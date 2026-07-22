import json
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from devagent.review import (
    CodeReviewReport,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
)


class ReviewEvalConfigurationError(ValueError):
    """Review Evaluation fixture 无法形成可信指标。"""


class ReviewEvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedReviewFinding(ReviewEvalModel):
    expected_id: str = Field(min_length=1, max_length=100)
    severity: ReviewSeverity
    category: ReviewCategory
    file_path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        return _validate_repo_path(value)

    @model_validator(mode="after")
    def validate_line_range(self) -> "ExpectedReviewFinding":
        if self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end 不能小于 line_start")
        return self


class ReviewEvalDiffLine(ReviewEvalModel):
    file_path: str = Field(min_length=1, max_length=1000)
    line: int = Field(ge=1)
    side: ReviewLineSide

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        return _validate_repo_path(value)


class ReviewEvalCase(ReviewEvalModel):
    case_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    clean_change: bool
    full_context_chars: int = Field(ge=1)
    bounded_context_chars: int = Field(ge=0)
    expected_findings: list[ExpectedReviewFinding]
    diff_lines: list[ReviewEvalDiffLine]
    report: CodeReviewReport

    @model_validator(mode="after")
    def validate_case(self) -> "ReviewEvalCase":
        if self.clean_change and self.expected_findings:
            raise ValueError("clean change 不能包含 expected findings")
        if not self.clean_change and not self.expected_findings:
            raise ValueError("缺陷 case 至少需要一个 expected finding")
        if self.bounded_context_chars > self.full_context_chars:
            raise ValueError("bounded context 不能大于 full context")
        expected_ids = [item.expected_id for item in self.expected_findings]
        if len(expected_ids) != len(set(expected_ids)):
            raise ValueError("expected_id 必须在 case 内唯一")
        diff_locations = [
            (item.file_path, item.line, item.side) for item in self.diff_lines
        ]
        if len(diff_locations) != len(set(diff_locations)):
            raise ValueError("diff_lines 不能包含重复定位")
        return self


class ReviewEvalMetrics(ReviewEvalModel):
    case_count: int = Field(ge=1)
    clean_case_count: int = Field(ge=1)
    expected_high_risk_count: int = Field(ge=1)
    matched_high_risk_count: int = Field(ge=0)
    predicted_finding_count: int = Field(ge=0)
    matched_finding_count: int = Field(ge=0)
    high_risk_recall: float = Field(ge=0, le=1)
    actionable_precision: float = Field(ge=0, le=1)
    clean_case_false_positive_rate: float = Field(ge=0, le=1)
    evidence_reference_completeness: float = Field(ge=0, le=1)
    diff_location_rate: float = Field(ge=0, le=1)
    average_context_reduction: float = Field(ge=0, le=1)
    unmatched_expected_ids: list[str]
    unmatched_finding_ids: list[str]


def load_review_eval_cases(case_dir: str | Path) -> list[ReviewEvalCase]:
    root = Path(case_dir).expanduser().resolve()
    if not root.is_dir():
        raise ReviewEvalConfigurationError("Review eval case 目录不存在")

    cases: list[ReviewEvalCase] = []
    for path in sorted(root.glob("*.json")):
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
            items = decoded if isinstance(decoded, list) else [decoded]
            cases.extend(ReviewEvalCase.model_validate(item) for item in items)
        except Exception as exc:
            raise ReviewEvalConfigurationError(
                f"无法加载 Review eval fixture: {path.name}"
            ) from exc
    if not cases:
        raise ReviewEvalConfigurationError("Review eval case 目录没有 JSON fixture")
    _validate_case_collection(cases)
    return cases


def evaluate_review_cases(cases: list[ReviewEvalCase]) -> ReviewEvalMetrics:
    if not cases:
        raise ReviewEvalConfigurationError("Review eval cases 不能为空")
    _validate_case_collection(cases)

    expected_high_risk_count = sum(
        1
        for case in cases
        for item in case.expected_findings
        if item.severity in {ReviewSeverity.HIGH, ReviewSeverity.CRITICAL}
    )
    if expected_high_risk_count == 0:
        raise ReviewEvalConfigurationError("Eval 集至少需要一个 HIGH / CRITICAL finding")

    clean_cases = [case for case in cases if case.clean_change]
    if not clean_cases:
        raise ReviewEvalConfigurationError("Eval 集至少需要一个 clean case")

    matched_expected: set[tuple[str, str]] = set()
    matched_predicted: set[tuple[str, str]] = set()
    all_predicted: list[tuple[ReviewEvalCase, ReviewFinding]] = []

    for case in cases:
        all_predicted.extend((case, finding) for finding in case.report.findings)
        available = list(case.report.findings)
        used_indexes: set[int] = set()
        for expected in case.expected_findings:
            for index, predicted in enumerate(available):
                if index in used_indexes or not _findings_match(expected, predicted):
                    continue
                used_indexes.add(index)
                matched_expected.add((case.case_id, expected.expected_id))
                matched_predicted.add((case.case_id, predicted.finding_id))
                break

    matched_high_risk_count = sum(
        1
        for case in cases
        for item in case.expected_findings
        if item.severity in {ReviewSeverity.HIGH, ReviewSeverity.CRITICAL}
        and (case.case_id, item.expected_id) in matched_expected
    )
    predicted_count = len(all_predicted)
    complete_evidence_count = sum(
        _has_complete_evidence(case.report, finding)
        for case, finding in all_predicted
    )
    located_count = sum(
        _is_diff_located(case, finding) for case, finding in all_predicted
    )
    actionable_count = sum(
        (case.case_id, finding.finding_id) in matched_predicted
        and _has_complete_evidence(case.report, finding)
        and bool(finding.suggestion.strip())
        and bool(finding.verification_steps)
        for case, finding in all_predicted
    )
    clean_false_positive_count = sum(bool(case.report.findings) for case in clean_cases)
    context_reductions = [
        1 - case.bounded_context_chars / case.full_context_chars for case in cases
    ]

    unmatched_expected_ids = [
        f"{case.case_id}:{item.expected_id}"
        for case in cases
        for item in case.expected_findings
        if (case.case_id, item.expected_id) not in matched_expected
    ]
    unmatched_finding_ids = [
        f"{case.case_id}:{finding.finding_id}"
        for case, finding in all_predicted
        if (case.case_id, finding.finding_id) not in matched_predicted
    ]

    return ReviewEvalMetrics(
        case_count=len(cases),
        clean_case_count=len(clean_cases),
        expected_high_risk_count=expected_high_risk_count,
        matched_high_risk_count=matched_high_risk_count,
        predicted_finding_count=predicted_count,
        matched_finding_count=len(matched_predicted),
        high_risk_recall=matched_high_risk_count / expected_high_risk_count,
        actionable_precision=(actionable_count / predicted_count if predicted_count else 0),
        clean_case_false_positive_rate=clean_false_positive_count / len(clean_cases),
        evidence_reference_completeness=(
            complete_evidence_count / predicted_count if predicted_count else 1
        ),
        diff_location_rate=(located_count / predicted_count if predicted_count else 1),
        average_context_reduction=sum(context_reductions) / len(context_reductions),
        unmatched_expected_ids=unmatched_expected_ids,
        unmatched_finding_ids=unmatched_finding_ids,
    )


def render_review_baseline_report(
    metrics: ReviewEvalMetrics,
    *,
    commit_id: str,
    generated_at: str,
) -> str:
    """把确定性指标渲染为可提交的 Markdown baseline。"""

    def percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    unmatched_expected = _render_identifier_list(metrics.unmatched_expected_ids)
    unmatched_findings = _render_identifier_list(metrics.unmatched_finding_ids)
    return "\n".join(
        [
            "# Code Review Evaluation Baseline",
            "",
            f"- Generated at: `{generated_at}`",
            f"- Commit: `{commit_id}`",
            f"- Cases: {metrics.case_count}",
            f"- Clean cases: {metrics.clean_case_count}",
            "",
            "## Quality Metrics",
            "",
            "| Metric | Result | Target |",
            "| --- | ---: | ---: |",
            f"| HIGH / CRITICAL recall | {percent(metrics.high_risk_recall)} | >= 85% |",
            f"| Actionable finding precision | {percent(metrics.actionable_precision)} | >= 70% |",
            f"| Clean-case false-positive rate | {percent(metrics.clean_case_false_positive_rate)} | <= 20% |",
            f"| Evidence reference completeness | {percent(metrics.evidence_reference_completeness)} | 100% |",
            f"| Diff location rate | {percent(metrics.diff_location_rate)} | 100% |",
            f"| Average context reduction | {percent(metrics.average_context_reduction)} | >= 40% |",
            "",
            "## Coverage",
            "",
            f"- Matched high-risk findings: {metrics.matched_high_risk_count}/{metrics.expected_high_risk_count}",
            f"- Matched predicted findings: {metrics.matched_finding_count}/{metrics.predicted_finding_count}",
            "",
            "## Unmatched Expected Findings",
            "",
            unmatched_expected,
            "",
            "## Unmatched Predicted Findings",
            "",
            unmatched_findings,
            "",
            "## Interpretation",
            "",
            "This deterministic baseline measures the scoring pipeline and fixed review cases. It does not represent a live-provider benchmark.",
            "",
        ]
    )


def _validate_case_collection(cases: list[ReviewEvalCase]) -> None:
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ReviewEvalConfigurationError("case_id 必须在 Eval 集内唯一")


def _findings_match(
    expected: ExpectedReviewFinding,
    predicted: ReviewFinding,
) -> bool:
    expected_end = expected.line_end or expected.line_start
    predicted_end = predicted.line_end or predicted.line_start
    return (
        expected.category == predicted.category
        and expected.file_path == predicted.file_path
        and max(expected.line_start, predicted.line_start)
        <= min(expected_end, predicted_end)
    )


def _has_complete_evidence(
    report: CodeReviewReport,
    finding: ReviewFinding,
) -> bool:
    known_ids = {item.evidence_id for item in report.evidence}
    return bool(finding.evidence_ids) and set(finding.evidence_ids) <= known_ids


def _is_diff_located(case: ReviewEvalCase, finding: ReviewFinding) -> bool:
    line = finding.line_end or finding.line_start
    return any(
        item.file_path == finding.file_path
        and item.line == line
        and item.side == finding.side
        for item in case.diff_lines
    )


def _validate_repo_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        value != value.strip()
        or value in {"", "."}
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
    ):
        raise ValueError("file_path 必须是仓库内 POSIX 相对路径")
    return value


def _render_identifier_list(values: list[str]) -> str:
    if not values:
        return "- None"
    return "\n".join(f"- `{value}`" for value in values)
