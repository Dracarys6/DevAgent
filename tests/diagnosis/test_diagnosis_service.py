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
    LocalLogEvidenceCollector,
    LogDiagnosisInput,
    MissingEvidence,
)
from devagent.llm import LLMResponse, ToolCall
from devagent.memory import EvidenceSnippet, LineRange, RetrievalResult
from devagent.tools.git_tools import GitDiffError
from devagent.tools.knowledge_tools import KnowledgeRetrieveError
from devagent.tools.log_tools import SearchLogError


def make_evidence() -> Evidence:
    return Evidence(
        evidence_id="E1",
        kind=EvidenceKind.CI_RESULT,
        tool_name="get_ci_result",
        source="pipeline-1001",
        locator="commit_id=abc123",
        excerpt='{"status":"failed"}',
    )


def make_retrieval_result(query: str) -> RetrievalResult:
    return RetrievalResult(
        query=query,
        top_k=3,
        total_candidates=1,
        retrieval_ms=3.5,
        items=[
            EvidenceSnippet(
                chunk_id="chunk-uploader",
                document_id="doc-uploader",
                source="workspace",
                path="src/sample_app/uploader.py",
                line_range=LineRange(start=1, end=24),
                excerpt="def build_upload_timeout():\n    return 3",
                score=0.9,
                rank=1,
                metadata={"retrieval_method": "hybrid_rrf"},
            )
        ],
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


class FixedLogCollector:
    def __init__(self, diagnosis_input: LogDiagnosisInput) -> None:
        self.diagnosis_input = diagnosis_input
        self.calls: list[dict[str, str]] = []

    def collect(
        self,
        *,
        report_id: str,
        task_id: str,
        data_dir: str,
        workspace: str | None = None,
    ) -> LogDiagnosisInput:
        self.calls.append(
            {
                "report_id": report_id,
                "task_id": task_id,
                "data_dir": data_dir,
                "workspace": workspace or ".",
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


def make_log_input() -> LogDiagnosisInput:
    return LogDiagnosisInput(
        report_id="report-log-001",
        task_id="task_001",
        workspace="examples/sample_logs",
        evidence=[
            Evidence(
                evidence_id="E1",
                kind=EvidenceKind.LOG,
                tool_name="search_log",
                source="task_001",
                locator="task_id=task_001;first_anomaly_sequence_id=3;entries=6",
                excerpt='{"first_anomaly":{"message":"UploadTimeoutError"}}',
            )
        ],
        missing_evidence=[
            MissingEvidence(
                needed="首个异常对应的代码证据",
                reason="日志不能单独证明代码根因",
                suggested_tool="read_file",
            )
        ],
    )


def make_log_report(*, target: str = "task_001") -> DiagnosisReport:
    diagnosis_input = make_log_input()
    return DiagnosisReport(
        report_id="model-report-id",
        scenario=DiagnosisScenario.LOG_FAILURE,
        target=target,
        status=DiagnosisStatus.DIAGNOSED,
        summary="首个异常是 UploadTimeoutError，后续重试失败。",
        findings=[
            Finding(
                kind=FindingKind.SYMPTOM,
                statement="sequence_id=3 首先出现 UploadTimeoutError。",
                confidence=Confidence.CONFIRMED,
                evidence_ids=["E1"],
            )
        ],
        evidence=diagnosis_input.evidence,
        missing_evidence=diagnosis_input.missing_evidence,
    )


def make_log_service(
    response: LLMResponse,
) -> tuple[DiagnosisService, FixedLLMClient, FixedLogCollector]:
    client = FixedLLMClient(response)
    collector = FixedLogCollector(make_log_input())
    service = DiagnosisService(
        llm_client=client,
        ci_evidence_collector=FixedCollector(make_diagnosis_input()),
        log_evidence_collector=collector,
        report_id_factory=lambda: "report-log-001",
    )
    return service, client, collector


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


def test_local_ci_evidence_collector_reads_complete_real_sample_evidence():
    collector = LocalCIEvidenceCollector()

    result = collector.collect(
        report_id="report-live-sample",
        commit_id="7229c86",
        workspace="examples/sample_repo",
    )

    assert [item.kind for item in result.evidence] == [
        EvidenceKind.CI_RESULT,
        EvidenceKind.GIT_DIFF,
    ]
    assert "test_large_upload_uses_dynamic_timeout" in result.evidence[0].excerpt
    assert "build_upload_timeout" in result.evidence[1].excerpt
    assert "README.md" not in result.evidence[1].excerpt
    assert "ci_failure_notes.md" not in result.evidence[1].excerpt
    assert "故意保留一个回归" not in result.evidence[1].excerpt
    assert "根因" not in result.evidence[1].excerpt
    assert result.missing_evidence == []


def test_local_ci_evidence_collector_appends_retrieved_workspace_evidence():
    raw_ci_result = json.dumps(
        {
            "pipeline_id": "pipeline-1001",
            "status": "failed",
            "failed_jobs": [{"name": "unit-tests"}],
            "core_log": "AssertionError: assert 3 >= 12",
        }
    )
    calls: list[tuple[str, str, int]] = []

    def retrieve(query: str, workspace: str, top_k: int) -> RetrievalResult:
        calls.append((query, workspace, top_k))
        return make_retrieval_result(query)

    collector = LocalCIEvidenceCollector(
        ci_result_reader=lambda commit_id: raw_ci_result,
        git_diff_reader=lambda commit_id, workspace: "-return timeout\n+return 3",
        knowledge_retriever=retrieve,
    )

    result = collector.collect(
        report_id="report-ci-001",
        commit_id="abc123",
        workspace="examples/sample_repo",
    )

    assert [item.kind for item in result.evidence] == [
        EvidenceKind.CI_RESULT,
        EvidenceKind.GIT_DIFF,
        EvidenceKind.KNOWLEDGE,
    ]
    assert result.evidence[2].evidence_id == "E3"
    assert "path=src/sample_app/uploader.py" in result.evidence[2].locator
    assert "AssertionError" in calls[0][0]
    assert calls[0][1:] == ("examples/sample_repo", 3)
    assert result.missing_evidence == []


def test_local_ci_evidence_collector_keeps_domain_evidence_on_retrieval_failure():
    raw_ci_result = json.dumps(
        {
            "pipeline_id": "pipeline-1001",
            "status": "failed",
            "failed_jobs": [{"name": "unit-tests"}],
            "core_log": "AssertionError",
        }
    )

    def fail_retrieval(query: str, workspace: str, top_k: int) -> RetrievalResult:
        raise KnowledgeRetrieveError("embedding unavailable")

    collector = LocalCIEvidenceCollector(
        ci_result_reader=lambda commit_id: raw_ci_result,
        git_diff_reader=lambda commit_id, workspace: "+return 3",
        knowledge_retriever=fail_retrieval,
    )

    result = collector.collect(
        report_id="report-ci-001",
        commit_id="abc123",
        workspace="examples/sample_repo",
    )

    assert [item.kind for item in result.evidence] == [
        EvidenceKind.CI_RESULT,
        EvidenceKind.GIT_DIFF,
    ]
    assert result.missing_evidence[-1].suggested_tool == "knowledge_retrieve"
    assert "embedding unavailable" not in result.missing_evidence[-1].reason


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

    assert exc_info.value.code == DiagnosisServiceErrorCode.EVIDENCE_COLLECTION_FAILED


def test_local_log_evidence_collector_reads_timeline_and_marks_root_cause_gap():
    collector = LocalLogEvidenceCollector()

    result = collector.collect(
        report_id="report-log-001",
        task_id="task_001",
        data_dir="examples/sample_logs",
    )

    assert [item.evidence_id for item in result.evidence] == ["E1"]
    assert result.evidence[0].kind == EvidenceKind.LOG
    assert "first_anomaly_sequence_id=3" in result.evidence[0].locator
    assert "UploadTimeoutError" in result.evidence[0].excerpt
    assert "RetryExhaustedError" in result.evidence[0].excerpt
    assert result.missing_evidence[0].suggested_tool == "read_file"


def test_local_log_evidence_collector_separates_log_and_knowledge_workspaces():
    calls: list[tuple[str, str, int]] = []

    def retrieve(query: str, workspace: str, top_k: int) -> RetrievalResult:
        calls.append((query, workspace, top_k))
        return make_retrieval_result(query)

    collector = LocalLogEvidenceCollector(knowledge_retriever=retrieve)

    result = collector.collect(
        report_id="report-log-001",
        task_id="task_001",
        data_dir="examples/sample_logs",
        workspace="examples/sample_repo",
    )

    assert result.workspace == "examples/sample_repo"
    assert [item.kind for item in result.evidence] == [
        EvidenceKind.LOG,
        EvidenceKind.KNOWLEDGE,
    ]
    assert "UploadTimeoutError" in calls[0][0]
    assert calls[0][1:] == ("examples/sample_repo", 3)
    assert result.missing_evidence == []


def test_local_log_evidence_collector_keeps_timeline_on_retrieval_failure():
    def fail_retrieval(query: str, workspace: str, top_k: int) -> RetrievalResult:
        raise KnowledgeRetrieveError("secret provider response")

    collector = LocalLogEvidenceCollector(knowledge_retriever=fail_retrieval)

    result = collector.collect(
        report_id="report-log-001",
        task_id="task_001",
        data_dir="examples/sample_logs",
        workspace="examples/sample_repo",
    )

    assert [item.kind for item in result.evidence] == [EvidenceKind.LOG]
    assert result.missing_evidence[-1].suggested_tool == "knowledge_retrieve"
    assert "secret provider response" not in result.missing_evidence[-1].reason


def test_local_log_evidence_collector_converts_missing_log_to_missing_evidence():
    def missing_log(task_id: str, data_dir: str) -> str:
        raise SearchLogError(f"missing {task_id} in {data_dir}")

    collector = LocalLogEvidenceCollector(log_result_reader=missing_log)

    result = collector.collect(
        report_id="report-log-001",
        task_id="task_missing",
        data_dir="examples/sample_logs",
    )

    assert result.evidence == []
    assert result.missing_evidence[0].suggested_tool == "search_log"


def test_local_log_evidence_collector_rejects_malformed_tool_json():
    collector = LocalLogEvidenceCollector(
        log_result_reader=lambda task_id, data_dir: "not-json"
    )

    with pytest.raises(DiagnosisServiceError) as exc_info:
        collector.collect(
            report_id="report-log-001",
            task_id="task_001",
            data_dir="examples/sample_logs",
        )

    assert exc_info.value.code == DiagnosisServiceErrorCode.EVIDENCE_COLLECTION_FAILED


def test_diagnosis_service_returns_validated_report_and_builds_messages():
    report = make_report()
    service, client = make_service(LLMResponse.final_answer(report.model_dump_json()))

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

    assert exc_info.value.code == DiagnosisServiceErrorCode.UNEXPECTED_LLM_RESPONSE


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


def test_diagnosis_service_binds_authoritative_target():
    service, _ = make_service(
        LLMResponse.final_answer(make_report(target="deadbeef").model_dump_json())
    )

    report = service.diagnose_ci(commit_id="abc123")

    assert report.target == "abc123"


def test_diagnosis_service_binds_authoritative_evidence():
    report_data = make_report().model_dump()
    report_data["evidence"][0]["excerpt"] = "模型改写后的证据"
    report = DiagnosisReport.model_validate(report_data)
    service, _ = make_service(LLMResponse.final_answer(report.model_dump_json()))

    result = service.diagnose_ci(commit_id="abc123")

    assert result.evidence == [make_evidence()]


def test_diagnosis_service_diagnoses_log_and_binds_authoritative_fields():
    response = LLMResponse.final_answer(
        make_log_report(target="model-target").model_dump_json()
    )
    service, client, collector = make_log_service(response)

    result = service.diagnose_log(
        task_id="task_001",
        data_dir="examples/sample_logs",
    )

    assert result.report_id == "report-log-001"
    assert result.scenario == DiagnosisScenario.LOG_FAILURE
    assert result.target == "task_001"
    assert result.evidence == make_log_input().evidence
    assert collector.calls[0]["task_id"] == "task_001"
    assert client.requests[0][0]["content"].startswith("你是一个日志根因分析 Agent")
    assert '"task_id":"task_001"' in client.requests[0][1]["content"]


def test_diagnosis_service_rejects_dangling_log_evidence_reference():
    report_data = make_log_report().model_dump()
    report_data["findings"][0]["evidence_ids"] = ["E9"]
    service, _, _ = make_log_service(
        LLMResponse.final_answer(json.dumps(report_data, ensure_ascii=False))
    )

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_log(task_id="task_001")

    assert exc_info.value.code == DiagnosisServiceErrorCode.INVALID_REPORT


def test_diagnosis_service_requires_log_collector_configuration():
    service, _ = make_service(LLMResponse.final_answer(make_report().model_dump_json()))

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_log(task_id="task_001")

    assert exc_info.value.code == DiagnosisServiceErrorCode.CONFIGURATION_ERROR


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
