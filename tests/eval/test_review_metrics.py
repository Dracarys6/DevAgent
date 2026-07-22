import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from devagent.diagnosis import Evidence, EvidenceKind
from devagent.eval import (
    ExpectedReviewFinding,
    ReviewEvalCase,
    ReviewEvalConfigurationError,
    ReviewEvalDiffLine,
    evaluate_review_cases,
    load_review_eval_cases,
    render_review_baseline_report,
)
from devagent.review import (
    CodeReviewReport,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)

BASELINE_CASE_DIR = Path(__file__).parents[2] / "eval" / "cases" / "code_review"


def make_evidence() -> Evidence:
    return Evidence(
        evidence_id="E1",
        kind=EvidenceKind.GIT_DIFF,
        tool_name="git_compare",
        source="b" * 40,
        locator="path=src/app.py;line=10",
        excerpt="+ risky_change()",
    )


def make_finding(
    *,
    finding_id: str = "R1",
    category: ReviewCategory = ReviewCategory.CORRECTNESS,
    file_path: str = "src/app.py",
    line_start: int = 10,
    line_end: int | None = None,
) -> ReviewFinding:
    return ReviewFinding(
        finding_id=finding_id,
        severity=ReviewSeverity.HIGH,
        category=category,
        title="边界条件错误",
        description="新增分支会返回错误结果。",
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        side=ReviewLineSide.HEAD,
        evidence_ids=["E1"],
        suggestion="修正边界判断。",
        verification_steps=["运行边界条件测试"],
    )


def make_report(findings: list[ReviewFinding]) -> CodeReviewReport:
    return CodeReviewReport(
        review_id="review-1",
        base_ref="base",
        head_ref="head",
        status=ReviewStatus.REVIEWED,
        summary="固定评测报告。",
        findings=findings,
        evidence=[make_evidence()] if findings else [],
    )


def make_case(
    *,
    case_id: str = "case-1",
    clean: bool = False,
    expected: list[ExpectedReviewFinding] | None = None,
    findings: list[ReviewFinding] | None = None,
    diff_lines: list[ReviewEvalDiffLine] | None = None,
    full_context_chars: int = 1000,
    bounded_context_chars: int = 500,
) -> ReviewEvalCase:
    actual_findings = findings if findings is not None else ([] if clean else [make_finding()])
    actual_expected = expected if expected is not None else (
        []
        if clean
        else [
            ExpectedReviewFinding(
                expected_id="X1",
                severity=ReviewSeverity.HIGH,
                category=ReviewCategory.CORRECTNESS,
                file_path="src/app.py",
                line_start=9,
                line_end=11,
            )
        ]
    )
    actual_diff_lines = diff_lines if diff_lines is not None else [
        ReviewEvalDiffLine(
            file_path="src/app.py",
            line=10,
            side=ReviewLineSide.HEAD,
        )
    ]
    return ReviewEvalCase(
        case_id=case_id,
        description="固定评测样例",
        clean_change=clean,
        full_context_chars=full_context_chars,
        bounded_context_chars=bounded_context_chars,
        expected_findings=actual_expected,
        diff_lines=actual_diff_lines,
        report=make_report(actual_findings),
    )


def test_evaluate_review_cases_calculates_full_match_metrics() -> None:
    metrics = evaluate_review_cases([make_case(), make_case(case_id="clean", clean=True)])

    assert metrics.high_risk_recall == 1
    assert metrics.actionable_precision == 1
    assert metrics.clean_case_false_positive_rate == 0
    assert metrics.evidence_reference_completeness == 1
    assert metrics.diff_location_rate == 1
    assert metrics.average_context_reduction == 0.5
    assert metrics.unmatched_expected_ids == []
    assert metrics.unmatched_finding_ids == []


@pytest.mark.parametrize(
    "finding",
    [
        make_finding(file_path="src/other.py"),
        make_finding(line_start=30),
        make_finding(category=ReviewCategory.SECURITY),
    ],
)
def test_finding_requires_matching_category_file_and_overlapping_line(
    finding: ReviewFinding,
) -> None:
    case = make_case(findings=[finding])
    metrics = evaluate_review_cases([case, make_case(case_id="clean", clean=True)])

    assert metrics.high_risk_recall == 0
    assert metrics.actionable_precision == 0
    assert metrics.unmatched_expected_ids == ["case-1:X1"]
    assert metrics.unmatched_finding_ids == ["case-1:R1"]


def test_one_predicted_finding_cannot_match_two_expected_findings() -> None:
    expected = [
        ExpectedReviewFinding(
            expected_id=expected_id,
            severity=ReviewSeverity.HIGH,
            category=ReviewCategory.CORRECTNESS,
            file_path="src/app.py",
            line_start=9,
            line_end=11,
        )
        for expected_id in ("X1", "X2")
    ]
    case = make_case(expected=expected)

    metrics = evaluate_review_cases([case, make_case(case_id="clean", clean=True)])

    assert metrics.matched_high_risk_count == 1
    assert metrics.high_risk_recall == 0.5
    assert metrics.unmatched_expected_ids == ["case-1:X2"]


def test_clean_case_false_positive_rate_is_case_based() -> None:
    clean_with_two_findings = make_case(
        case_id="clean-with-findings",
        clean=True,
        findings=[make_finding(), make_finding(finding_id="R2")],
    )
    clean_without_findings = make_case(case_id="clean-empty", clean=True)

    metrics = evaluate_review_cases(
        [make_case(), clean_with_two_findings, clean_without_findings]
    )

    assert metrics.clean_case_false_positive_rate == 0.5


def test_zero_predictions_have_zero_precision_and_complete_empty_contracts() -> None:
    defect = make_case(findings=[])
    metrics = evaluate_review_cases([defect, make_case(case_id="clean", clean=True)])

    assert metrics.actionable_precision == 0
    assert metrics.evidence_reference_completeness == 1
    assert metrics.diff_location_rate == 1


def test_context_reduction_is_averaged_per_case() -> None:
    first = make_case(full_context_chars=1000, bounded_context_chars=500)
    second = make_case(
        case_id="clean",
        clean=True,
        full_context_chars=100,
        bounded_context_chars=10,
    )

    metrics = evaluate_review_cases([first, second])

    assert metrics.average_context_reduction == pytest.approx(0.7)


def test_eval_requires_high_risk_and_clean_cases() -> None:
    medium = ExpectedReviewFinding(
        expected_id="X1",
        severity=ReviewSeverity.MEDIUM,
        category=ReviewCategory.CORRECTNESS,
        file_path="src/app.py",
        line_start=10,
    )
    with pytest.raises(ReviewEvalConfigurationError, match="HIGH"):
        evaluate_review_cases(
            [make_case(expected=[medium]), make_case(case_id="clean", clean=True)]
        )
    with pytest.raises(ReviewEvalConfigurationError, match="clean"):
        evaluate_review_cases([make_case()])


def test_eval_rejects_duplicate_case_ids() -> None:
    with pytest.raises(ReviewEvalConfigurationError, match="case_id"):
        evaluate_review_cases([make_case(), make_case()])


def test_case_model_rejects_invalid_contracts() -> None:
    with pytest.raises(ValidationError, match="clean change"):
        make_case(clean=True, expected=[make_case().expected_findings[0]])
    with pytest.raises(ValidationError, match="bounded context"):
        make_case(bounded_context_chars=1001)
    with pytest.raises(ValidationError, match="line_end"):
        ExpectedReviewFinding(
            expected_id="X1",
            severity=ReviewSeverity.HIGH,
            category=ReviewCategory.CORRECTNESS,
            file_path="src/app.py",
            line_start=10,
            line_end=9,
        )


def test_loader_is_sorted_repeatable_and_sanitizes_fixture_errors(
    tmp_path: Path,
) -> None:
    clean = make_case(case_id="clean", clean=True)
    defect = make_case(case_id="defect")
    (tmp_path / "z.json").write_text(clean.model_dump_json(), encoding="utf-8")
    (tmp_path / "a.json").write_text(defect.model_dump_json(), encoding="utf-8")

    first = load_review_eval_cases(tmp_path)
    second = load_review_eval_cases(tmp_path)

    assert [case.case_id for case in first] == ["defect", "clean"]
    assert first == second

    (tmp_path / "bad.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(ReviewEvalConfigurationError) as exc_info:
        load_review_eval_cases(tmp_path)
    assert "not-json" not in str(exc_info.value)


def test_loader_accepts_a_json_list(tmp_path: Path) -> None:
    payload = [
        make_case().model_dump(mode="json"),
        make_case(case_id="clean", clean=True).model_dump(mode="json"),
    ]
    (tmp_path / "cases.json").write_text(json.dumps(payload), encoding="utf-8")

    assert len(load_review_eval_cases(tmp_path)) == 2


def test_baseline_report_renders_metrics_and_unmatched_ids() -> None:
    metrics = evaluate_review_cases(
        [make_case(findings=[]), make_case(case_id="clean", clean=True)]
    )

    report = render_review_baseline_report(
        metrics,
        commit_id="abc123",
        generated_at="2026-07-22T00:00:00Z",
    )

    assert "HIGH / CRITICAL recall | 0.0%" in report
    assert "`case-1:X1`" in report
    assert "abc123" in report


def test_fixed_baseline_cases_meet_day49_targets() -> None:
    cases = load_review_eval_cases(BASELINE_CASE_DIR)

    first = evaluate_review_cases(cases)
    second = evaluate_review_cases(load_review_eval_cases(BASELINE_CASE_DIR))

    assert first == second
    assert first.case_count == 10
    assert first.expected_high_risk_count == 7
    assert first.high_risk_recall == pytest.approx(6 / 7)
    assert first.actionable_precision == pytest.approx(6 / 7)
    assert first.clean_case_false_positive_rate == 0
    assert first.evidence_reference_completeness == 1
    assert first.diff_location_rate == 1
    assert first.average_context_reduction == 0.5
    assert first.unmatched_expected_ids == ["security-permission-order:X1"]
    assert first.unmatched_finding_ids == ["security-permission-order:R1"]
