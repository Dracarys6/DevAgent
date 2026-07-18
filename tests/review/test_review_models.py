import pytest
from pydantic import ValidationError

from devagent.diagnosis import Evidence, EvidenceKind, MissingEvidence
from devagent.review import (
    CodeReviewInput,
    CodeReviewReport,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)


def make_evidence(evidence_id: str = "E1") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=EvidenceKind.GIT_DIFF,
        tool_name="git_diff",
        source="feature-branch",
        locator="src/sample_app/uploader.py:24",
        excerpt="return MIN_UPLOAD_TIMEOUT",
    )


def make_finding(**overrides: object) -> ReviewFinding:
    data: dict[str, object] = {
        "finding_id": "R1",
        "severity": ReviewSeverity.HIGH,
        "category": ReviewCategory.CORRECTNESS,
        "title": "大文件上传仍固定使用最小超时",
        "description": "修改后的实现忽略文件大小和带宽，可能提前超时。",
        "file_path": "src/sample_app/uploader.py",
        "line_start": 24,
        "line_end": 26,
        "side": ReviewLineSide.HEAD,
        "evidence_ids": ["E1"],
        "suggestion": "根据预计上传耗时计算超时，并保留最小值下限。",
        "verification_steps": ["运行上传超时参数化测试"],
    }
    data.update(overrides)
    return ReviewFinding.model_validate(data)


def make_report(**overrides: object) -> CodeReviewReport:
    data: dict[str, object] = {
        "review_id": "review-1",
        "base_ref": "main",
        "head_ref": "feature-branch",
        "status": ReviewStatus.REVIEWED,
        "summary": "发现一个需要修复的正确性问题。",
        "findings": [make_finding()],
        "evidence": [make_evidence()],
        "missing_evidence": [],
    }
    data.update(overrides)
    return CodeReviewReport.model_validate(data)


def test_review_taxonomy_has_expected_values() -> None:
    assert {item.value for item in ReviewSeverity} == {
        "critical",
        "high",
        "medium",
        "low",
    }
    assert {item.value for item in ReviewCategory} == {
        "correctness",
        "security",
        "compatibility",
        "performance",
        "maintainability",
        "test_gap",
    }


@pytest.mark.parametrize("severity", list(ReviewSeverity))
def test_review_finding_accepts_each_severity(
    severity: ReviewSeverity,
) -> None:
    assert make_finding(severity=severity).severity == severity


@pytest.mark.parametrize("category", list(ReviewCategory))
def test_review_finding_accepts_each_category(
    category: ReviewCategory,
) -> None:
    assert make_finding(category=category).category == category


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("severity", "unknown"), ("category", "style")],
)
def test_review_finding_rejects_unknown_taxonomy_value(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError, match=field_name):
        make_finding(**{field_name: value})


def test_code_review_report_accepts_actionable_finding() -> None:
    report = make_report()

    finding = report.findings[0]
    assert finding.file_path == "src/sample_app/uploader.py"
    assert finding.line_start == 24
    assert finding.evidence_ids == ["E1"]
    assert finding.suggestion
    assert finding.verification_steps


def test_review_finding_supports_base_side_and_single_line() -> None:
    finding = make_finding(side=ReviewLineSide.BASE, line_end=None)

    assert finding.side == ReviewLineSide.BASE
    assert finding.line_end is None


def test_code_review_report_supports_json_round_trip() -> None:
    report = make_report()

    restored = CodeReviewReport.model_validate_json(report.model_dump_json())

    assert restored == report


def test_code_review_report_accepts_clean_review() -> None:
    report = make_report(
        summary="未发现可行动问题。",
        findings=[],
        evidence=[],
    )

    assert report.status == ReviewStatus.REVIEWED
    assert report.findings == []


def test_code_review_report_accepts_insufficient_evidence() -> None:
    report = make_report(
        status=ReviewStatus.INSUFFICIENT_EVIDENCE,
        summary="缺少目标分支的 Git diff。",
        findings=[],
        evidence=[],
        missing_evidence=[
            MissingEvidence(
                needed="目标分支 Git diff",
                reason="无法解析 head_ref",
                suggested_tool="git_diff",
            )
        ],
    )

    assert report.status == ReviewStatus.INSUFFICIENT_EVIDENCE
    assert report.missing_evidence[0].suggested_tool == "git_diff"


def test_code_review_report_rejects_dangling_evidence_id() -> None:
    with pytest.raises(ValidationError, match="不存在的 evidence_id"):
        make_report(findings=[make_finding(evidence_ids=["E2"])])


def test_code_review_report_rejects_duplicate_finding_id() -> None:
    with pytest.raises(ValidationError, match="finding_id 必须唯一"):
        make_report(findings=[make_finding(), make_finding()])


def test_code_review_report_rejects_duplicate_evidence_id() -> None:
    with pytest.raises(ValidationError, match="evidence_id 必须唯一"):
        make_report(evidence=[make_evidence(), make_evidence()])


def test_code_review_input_rejects_duplicate_evidence_id() -> None:
    with pytest.raises(ValidationError, match="evidence_id 必须唯一"):
        CodeReviewInput(
            review_id="review-1",
            base_ref="main",
            head_ref="feature-branch",
            evidence=[make_evidence(), make_evidence()],
        )


def test_code_review_input_accepts_missing_evidence() -> None:
    review_input = CodeReviewInput(
        review_id="review-1",
        base_ref="main",
        head_ref="feature-branch",
        missing_evidence=[
            MissingEvidence(
                needed="目标分支 Git diff",
                reason="本地不存在 head_ref",
                suggested_tool="git_diff",
            )
        ],
    )

    assert review_input.missing_evidence[0].needed == "目标分支 Git diff"


def test_code_review_input_rejects_empty_workspace() -> None:
    with pytest.raises(ValidationError, match="workspace"):
        CodeReviewInput(
            review_id="review-1",
            base_ref="main",
            head_ref="feature-branch",
            workspace="",
        )


def test_insufficient_report_requires_missing_evidence() -> None:
    with pytest.raises(ValidationError, match="必须说明 missing_evidence"):
        make_report(
            status=ReviewStatus.INSUFFICIENT_EVIDENCE,
            findings=[],
            evidence=[],
            missing_evidence=[],
        )


@pytest.mark.parametrize(
    "file_path",
    [
        "/absolute/file.py",
        "../outside.py",
        "src/../../outside.py",
        r"src\sample_app\uploader.py",
        ".",
        " src/sample_app/uploader.py",
    ],
)
def test_review_finding_requires_repository_relative_posix_path(
    file_path: str,
) -> None:
    with pytest.raises(ValidationError, match="file_path"):
        make_finding(file_path=file_path)


def test_review_finding_rejects_reversed_line_range() -> None:
    with pytest.raises(ValidationError, match="line_end 不能小于 line_start"):
        make_finding(line_start=20, line_end=10)


@pytest.mark.parametrize("finding_id", ["R0", "1", "r1", "R01"])
def test_review_finding_rejects_invalid_finding_id(finding_id: str) -> None:
    with pytest.raises(ValidationError, match="finding_id"):
        make_finding(finding_id=finding_id)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("evidence_ids", []),
        ("suggestion", ""),
        ("verification_steps", []),
    ],
)
def test_review_finding_requires_actionable_fields(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match=field_name):
        make_finding(**{field_name: value})


@pytest.mark.parametrize("model_name", ["input", "report"])
@pytest.mark.parametrize(
    ("base_ref", "head_ref", "message"),
    [
        ("main", "main", "不能相同"),
        (" main", "feature", "不能包含首尾空白"),
        ("main", "feature ", "不能包含首尾空白"),
    ],
)
def test_review_models_require_distinct_clean_refs(
    model_name: str,
    base_ref: str,
    head_ref: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        if model_name == "input":
            CodeReviewInput(
                review_id="review-1",
                base_ref=base_ref,
                head_ref=head_ref,
            )
        else:
            make_report(base_ref=base_ref, head_ref=head_ref)


def test_review_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CodeReviewInput(
            review_id="review-1",
            base_ref="main",
            head_ref="feature-branch",
            unexpected=True,
        )
