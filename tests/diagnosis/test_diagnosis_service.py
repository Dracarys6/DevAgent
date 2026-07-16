import json
from typing import Any

import pytest

from devagent.diagnosis import (
    Confidence,
    DiagnosisInput,
    DiagnosisReport,
    DiagnosisScenario,
    DiagnosisService,
    DiagnosisServiceError,
    DiagnosisServiceErrorCode,
    DiagnosisStatus,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    LocalCIEvidenceCollector,
)
from devagent.llm import LLMResponse, ToolCall
from devagent.tools.git_tools import GitDiffError


def make_evidence() -> Evidence:
    return Evidence(
        evidence_id="E1",
        kind=EvidenceKind.CI_RESULT,
        tool_name="get_ci_result",
        source="pipeline-1001",
        locator="commit_id=abc123",
        excerpt='{"status":"failed"}',
    )


def make_diagnosis_input() -> DiagnosisInput:
    return DiagnosisInput(
        report_id="report-ci-001",
        commit_id="abc123",
        workspace="examples/sample_repo",
        evidence=[make_evidence()],
    )


def make_report(
    *,
    report_id: str = "report-ci-001",
    target: str = "abc123",
) -> DiagnosisReport:
    evidence = make_evidence()
    return DiagnosisReport(
        report_id=report_id,
        scenario=DiagnosisScenario.CI_FAILURE,
        target=target,
        status=DiagnosisStatus.DIAGNOSED,
        summary="CI 测试确认 timeout 低于预期。",
        findings=[
            Finding(
                kind=FindingKind.SYMPTOM,
                statement="大文件上传测试失败。",
                confidence=Confidence.CONFIRMED,
                evidence_ids=["E1"],
            )
        ],
        evidence=[evidence],
    )


class FixedCollector:
    def __init__(self, diagnosis_input: DiagnosisInput) -> None:
        self.diagnosis_input = diagnosis_input
        self.calls: list[dict[str, str]] = []

    def collect(
        self,
        *,
        report_id: str,
        commit_id: str,
        workspace: str,
    ) -> DiagnosisInput:
        self.calls.append(
            {
                "report_id": report_id,
                "commit_id": commit_id,
                "workspace": workspace,
            }
        )
        return self.diagnosis_input


class FixedLLMClient:
    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.requests: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        self.requests.append(messages)
        return self.response


def make_service(response: LLMResponse) -> tuple[DiagnosisService, FixedLLMClient]:
    client = FixedLLMClient(response)
    service = DiagnosisService(
        llm_client=client,
        ci_evidence_collector=FixedCollector(make_diagnosis_input()),
        report_id_factory=lambda: "report-ci-001",
    )
    return service, client


def test_local_ci_evidence_collector_converts_ci_result_and_missing_diff():
    raw_ci_result = json.dumps(
        {
            "pipeline_id": "pipeline-1001",
            "status": "failed",
            "failed_jobs": [{"name": "unit-tests"}],
            "core_log": "AssertionError: assert 3 >= 12",
        }
    )

    def failing_git_diff(commit_id: str, workspace: str) -> str:
        raise GitDiffError(f"无法读取 {commit_id} at {workspace}")

    collector = LocalCIEvidenceCollector(
        ci_result_reader=lambda commit_id: raw_ci_result,
        git_diff_reader=failing_git_diff,
    )

    result = collector.collect(
        report_id="report-ci-001",
        commit_id="abc123",
        workspace="examples/sample_repo",
    )

    assert [item.evidence_id for item in result.evidence] == ["E1"]
    assert result.evidence[0].kind == EvidenceKind.CI_RESULT
    assert result.missing_evidence[0].suggested_tool == "git_diff"


def test_local_ci_evidence_collector_rejects_malformed_tool_json():
    collector = LocalCIEvidenceCollector(
        ci_result_reader=lambda commit_id: "not-json",
        git_diff_reader=lambda commit_id, workspace: "",
    )

    with pytest.raises(DiagnosisServiceError) as exc_info:
        collector.collect(
            report_id="report-ci-001",
            commit_id="abc123",
            workspace="examples/sample_repo",
        )

    assert (
        exc_info.value.code
        == DiagnosisServiceErrorCode.EVIDENCE_COLLECTION_FAILED
    )


def test_diagnosis_service_returns_validated_report_and_builds_messages():
    report = make_report()
    service, client = make_service(
        LLMResponse.final_answer(report.model_dump_json())
    )

    result = service.diagnose_ci(
        commit_id="abc123",
        workspace="examples/sample_repo",
    )

    assert result == report
    assert [message["role"] for message in client.requests[0]] == [
        "system",
        "user",
    ]
    assert '"commit_id":"abc123"' in client.requests[0][1]["content"]


def test_diagnosis_service_rejects_tool_call_response():
    service, _ = make_service(
        LLMResponse.tool_calls_response(
            [ToolCall(id="call-1", name="read_file", arguments={})]
        )
    )

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_ci(commit_id="abc123")

    assert (
        exc_info.value.code
        == DiagnosisServiceErrorCode.UNEXPECTED_LLM_RESPONSE
    )


def test_diagnosis_service_rejects_invalid_report_json():
    service, _ = make_service(LLMResponse.final_answer("not-json"))

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_ci(commit_id="abc123")

    assert exc_info.value.code == DiagnosisServiceErrorCode.INVALID_REPORT


def test_diagnosis_service_rejects_empty_report_content():
    service, _ = make_service(LLMResponse.final_answer("   "))

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_ci(commit_id="abc123")

    assert exc_info.value.code == DiagnosisServiceErrorCode.EMPTY_LLM_RESPONSE


def test_diagnosis_service_rejects_report_for_another_target():
    service, _ = make_service(
        LLMResponse.final_answer(
            make_report(target="deadbeef").model_dump_json()
        )
    )

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_ci(commit_id="abc123")

    assert exc_info.value.code == DiagnosisServiceErrorCode.REPORT_MISMATCH


def test_diagnosis_service_rejects_rewritten_evidence():
    report_data = make_report().model_dump()
    report_data["evidence"][0]["excerpt"] = "模型改写后的证据"
    report = DiagnosisReport.model_validate(report_data)
    service, _ = make_service(
        LLMResponse.final_answer(report.model_dump_json())
    )

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_ci(commit_id="abc123")

    assert exc_info.value.code == DiagnosisServiceErrorCode.REPORT_MISMATCH


def test_diagnosis_service_wraps_llm_exception_without_leaking_message():
    class FailingLLMClient:
        def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
            raise RuntimeError("secret provider detail")

    service = DiagnosisService(
        llm_client=FailingLLMClient(),
        ci_evidence_collector=FixedCollector(make_diagnosis_input()),
        report_id_factory=lambda: "report-ci-001",
    )

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_ci(commit_id="abc123")

    assert exc_info.value.code == DiagnosisServiceErrorCode.LLM_CALL_FAILED
    assert "secret provider detail" not in exc_info.value.message
