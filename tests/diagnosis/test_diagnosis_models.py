import pytest
from pydantic import ValidationError

from devagent.diagnosis import (
    Confidence,
    DiagnosisInput,
    DiagnosisReport,
    DiagnosisStatus,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    MissingEvidence,
    Recommendation,
)


def make_evidence(
    evidence_id: str = "E1",
    *,
    kind: EvidenceKind = EvidenceKind.CI_RESULT,
    tool_name: str = "get_ci_result",
    source: str = "pipeline-1001",
    locator: str = "tests/test_uploader.py::test_large_upload_uses_dynamic_timeout",
    excerpt: str = "AssertionError: assert 3 >= 12",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        tool_name=tool_name,
        source=source,
        locator=locator,
        excerpt=excerpt,
    )


def make_abc123_report() -> DiagnosisReport:
    evidence = [
        make_evidence(),
        make_evidence(
            "E2",
            kind=EvidenceKind.CODE,
            tool_name="read_file",
            source="examples/sample_repo/src/sample_app/uploader.py",
            locator="UploadManager.build_upload_timeout",
            excerpt="return self.config.min_timeout_seconds",
        ),
        make_evidence(
            "E3",
            kind=EvidenceKind.LOG,
            tool_name="search_log",
            source="task_001",
            locator="sequence_id=3",
            excerpt="UploadTimeoutError: 上传在 3 秒后超时",
        ),
    ]
    return DiagnosisReport(
        report_id="report_abc123",
        target="abc123",
        status=DiagnosisStatus.DIAGNOSED,
        summary="大文件上传仍使用 3 秒 timeout，动态 timeout 计算可能未生效。",
        findings=[
            Finding(
                kind=FindingKind.SYMPTOM,
                statement="大文件上传 timeout 低于测试期望。",
                confidence=Confidence.CONFIRMED,
                evidence_ids=["E1", "E3"],
            ),
            Finding(
                kind=FindingKind.ROOT_CAUSE,
                statement="构建 timeout 时可能固定返回了最小值。",
                confidence=Confidence.LIKELY,
                evidence_ids=["E2"],
            ),
        ],
        evidence=evidence,
        recommendations=[
            Recommendation(
                action="让 build_upload_timeout 使用动态估算结果。",
                rationale="CI、代码和运行日志共同指向 timeout 计算未生效。",
                evidence_ids=["E1", "E2", "E3"],
                verification_steps=[
                    "运行 sample_repo 上传测试",
                    "确认大文件 timeout 不低于预估耗时",
                ],
            )
        ],
        missing_evidence=[
            MissingEvidence(
                needed="commit abc123 的真实 Git diff",
                reason="需要确认该行为是否由本次提交引入。",
                suggested_tool="git_diff",
            )
        ],
    )


def test_diagnosis_report_accepts_fixed_cited_case():
    report = make_abc123_report()

    assert report.findings[0].evidence_ids == ["E1", "E3"]
    assert report.findings[1].confidence == Confidence.LIKELY
    assert report.recommendations[0].evidence_ids == ["E1", "E2", "E3"]
    assert report.missing_evidence[0].suggested_tool == "git_diff"


def test_diagnosis_report_round_trips_through_json():
    report = make_abc123_report()

    assert DiagnosisReport.model_validate_json(report.model_dump_json()) == report


def test_diagnosis_report_rejects_duplicate_evidence_id():
    report = make_abc123_report().model_dump()
    report["evidence"].append(report["evidence"][0])

    with pytest.raises(ValidationError, match="evidence_id 不能重复"):
        DiagnosisReport.model_validate(report)


def test_diagnosis_input_rejects_duplicate_evidence_id():
    evidence = make_evidence()

    with pytest.raises(ValidationError, match="evidence_id 不能重复"):
        DiagnosisInput(
            report_id="report_abc123",
            commit_id="abc123",
            evidence=[evidence, evidence],
        )


@pytest.mark.parametrize("reference_owner", ["finding", "recommendation"])
def test_diagnosis_report_rejects_unknown_evidence_id(reference_owner: str):
    report = make_abc123_report().model_dump()
    report["findings"][0]["evidence_ids"] = ["E9"]
    if reference_owner == "recommendation":
        report["findings"][0]["evidence_ids"] = ["E1"]
        report["recommendations"][0]["evidence_ids"] = ["E9"]

    with pytest.raises(ValidationError, match="不存在的 evidence_id"):
        DiagnosisReport.model_validate(report)


def test_diagnosis_report_requires_finding_when_diagnosed():
    with pytest.raises(ValidationError, match="已诊断报告至少需要一条 finding"):
        DiagnosisReport(
            report_id="report_empty",
            target="abc123",
            status=DiagnosisStatus.DIAGNOSED,
            summary="没有诊断结论。",
            evidence=[make_evidence()],
        )


def test_diagnosis_report_requires_missing_evidence_when_insufficient():
    with pytest.raises(ValidationError, match="证据不足报告必须说明 missing_evidence"):
        DiagnosisReport(
            report_id="report_insufficient",
            target="abc123",
            status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
            summary="当前证据不足。",
        )


def test_evidence_rejects_invalid_evidence_id():
    with pytest.raises(ValidationError, match="evidence_id"):
        make_evidence("invalid_id")


def test_finding_rejects_invalid_evidence_reference_format():
    with pytest.raises(ValidationError, match="evidence_ids"):
        Finding(
            kind=FindingKind.SYMPTOM,
            statement="CI 失败。",
            confidence=Confidence.CONFIRMED,
            evidence_ids=["invalid_id"],
        )


def test_recommendation_requires_verification_steps():
    with pytest.raises(ValidationError, match="verification_steps"):
        Recommendation(
            action="修复 timeout。",
            rationale="timeout 低于预期。",
            evidence_ids=["E1"],
            verification_steps=[],
        )


def test_diagnosis_models_reject_unknown_fields():
    data = make_evidence().model_dump()
    data["unexpected"] = "ignored contract drift"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        Evidence.model_validate(data)
