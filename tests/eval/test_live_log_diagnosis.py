from pathlib import Path

from devagent.diagnosis import (
    Confidence,
    DiagnosisReport,
    DiagnosisScenario,
    DiagnosisStatus,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    MissingEvidence,
    Recommendation,
)
from devagent.eval import (
    evaluate_live_log_diagnosis,
    render_live_log_diagnosis_report,
    run_live_log_diagnosis,
)
from devagent.llm import LLMResponse, MockLLMClient

EXPECTED_KEYWORDS = ["UploadTimeoutError", "RetryExhaustedError", "3 秒"]


def make_report(*, confirmed_root_cause: bool = False) -> DiagnosisReport:
    evidence = Evidence(
        evidence_id="E1",
        kind=EvidenceKind.LOG,
        tool_name="search_log",
        source="task_001",
        locator="task_id=task_001;first_anomaly_sequence_id=3;entries=6",
        excerpt='{"first_anomaly":{"message":"UploadTimeoutError: 3 秒后超时"}}',
    )
    findings = [
        Finding(
            kind=FindingKind.SYMPTOM,
            statement="sequence_id=3 首先出现 UploadTimeoutError，上传在 3 秒后超时。",
            confidence=Confidence.CONFIRMED,
            evidence_ids=["E1"],
        ),
        Finding(
            kind=FindingKind.SYMPTOM,
            statement="RetryExhaustedError 是超时后的连锁错误。",
            confidence=Confidence.CONFIRMED,
            evidence_ids=["E1"],
        ),
    ]
    if confirmed_root_cause:
        findings.append(
            Finding(
                kind=FindingKind.ROOT_CAUSE,
                statement="代码实现确定是根因。",
                confidence=Confidence.CONFIRMED,
                evidence_ids=["E1"],
            )
        )
    return DiagnosisReport(
        report_id="model-report",
        scenario=DiagnosisScenario.LOG_FAILURE,
        target="model-target",
        status=DiagnosisStatus.DIAGNOSED,
        summary="上传先超时，之后重试耗尽并导致任务失败。",
        findings=findings,
        evidence=[evidence],
        recommendations=[
            Recommendation(
                action="检查上传 timeout 的代码和配置。",
                rationale="日志显示 timeout_seconds 为 3。",
                evidence_ids=["E1"],
                verification_steps=["读取上传 timeout 实现", "重新运行上传任务"],
            )
        ],
        missing_evidence=[
            MissingEvidence(
                needed="上传 timeout 的代码或配置证据",
                reason="日志不能单独确认代码根因",
                suggested_tool="read_file",
            )
        ],
    )


def test_live_log_runner_uses_real_collector_and_binds_authority() -> None:
    report = make_report()

    run = run_live_log_diagnosis(
        llm_client_factory=lambda: MockLLMClient(
            responses=[LLMResponse.final_answer(report.model_dump_json())]
        ),
        task_id="task_001",
        data_dir=Path("examples/sample_logs"),
        data_dir_label="examples/sample_logs",
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
        expected_keywords=EXPECTED_KEYWORDS,
    )

    assert run.report is not None
    assert run.report.report_id != "model-report"
    assert run.report.scenario == DiagnosisScenario.LOG_FAILURE
    assert run.report.target == "task_001"
    assert "UploadTimeoutError" in run.report.evidence[0].excerpt
    assert run.metrics.first_anomaly_identified is True
    assert run.metrics.cascade_error_identified is True
    assert run.metrics.code_evidence_gap_recorded is True
    assert run.metrics.passed is True


def test_live_log_runner_records_retry_count() -> None:
    responses = [
        LLMResponse.final_answer("not-json"),
        LLMResponse.final_answer(make_report().model_dump_json()),
    ]

    run = run_live_log_diagnosis(
        llm_client_factory=lambda: MockLLMClient(responses=[responses.pop(0)]),
        task_id="task_001",
        data_dir=Path("examples/sample_logs"),
        data_dir_label="examples/sample_logs",
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
        expected_keywords=EXPECTED_KEYWORDS,
        max_attempts=2,
    )

    assert run.attempt_count == 2
    assert run.attempt_errors == ["invalid_report"]
    assert run.metrics.passed is True


def test_live_log_metrics_reject_confirmed_root_cause_from_logs_alone() -> None:
    metrics = evaluate_live_log_diagnosis(
        make_report(confirmed_root_cause=True),
        EXPECTED_KEYWORDS,
    )

    assert metrics.confirmed_root_cause_count == 1
    assert metrics.passed is False


def test_live_log_report_is_traceable_and_hides_absolute_data_dir(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "logs"
    data_dir.mkdir()
    source = Path("examples/sample_logs/task_001.jsonl")
    (data_dir / "task_001.jsonl").write_text(
        source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    run = run_live_log_diagnosis(
        llm_client_factory=lambda: MockLLMClient(
            responses=[LLMResponse.final_answer(make_report().model_dump_json())]
        ),
        task_id="task_001",
        data_dir=data_dir,
        data_dir_label="fixtures/logs",
        provider="openai-compatible-live",
        model="real-model",
        api_mode="responses",
        expected_keywords=EXPECTED_KEYWORDS,
    )

    rendered = render_live_log_diagnosis_report(
        run,
        generated_at="2026-08-01T00:00:00Z",
        commit_id="revision",
    )

    assert "First Anomaly Identified | True" in rendered
    assert "Confirmed Root Causes | 0" in rendered
    assert "task_001" in rendered
    assert str(data_dir.resolve()) not in rendered
    assert str(data_dir.resolve()) not in run.model_dump_json()
