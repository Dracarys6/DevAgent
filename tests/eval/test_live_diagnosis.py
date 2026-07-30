from collections.abc import Iterator

from devagent.diagnosis import (
    Confidence,
    DiagnosisInput,
    DiagnosisReport,
    DiagnosisScenario,
    DiagnosisStatus,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    Recommendation,
)
from devagent.eval import (
    evaluate_live_ci_diagnosis,
    render_live_ci_diagnosis_report,
    run_live_ci_diagnosis,
)
from devagent.llm import LLMResponse, MockLLMClient


class FixedCollector:
    def __init__(self, diagnosis_input: DiagnosisInput) -> None:
        self.diagnosis_input = diagnosis_input

    def collect(
        self,
        *,
        report_id: str,
        commit_id: str,
        workspace: str,
    ) -> DiagnosisInput:
        return self.diagnosis_input.model_copy(
            update={
                "commit_id": commit_id,
                "workspace": workspace,
            }
        )


def make_evidence() -> list[Evidence]:
    return [
        Evidence(
            evidence_id="E1",
            kind=EvidenceKind.CI_RESULT,
            tool_name="get_ci_result",
            source="pipeline-live",
            locator="commit_id=abc123",
            excerpt="assert 3 >= 12",
        ),
        Evidence(
            evidence_id="E2",
            kind=EvidenceKind.GIT_DIFF,
            tool_name="git_diff",
            source="abc123",
            locator="commit patch",
            excerpt="return self.config.min_timeout_seconds",
        ),
    ]


def make_input() -> DiagnosisInput:
    return DiagnosisInput(
        report_id="live-report",
        commit_id="abc123",
        workspace="examples/sample_repo",
        evidence=make_evidence(),
    )


def make_report(*, report_id: str = "live-report") -> DiagnosisReport:
    evidence = make_evidence()
    return DiagnosisReport(
        report_id=report_id,
        scenario=DiagnosisScenario.CI_FAILURE,
        target="abc123",
        status=DiagnosisStatus.DIAGNOSED,
        summary="build_upload_timeout 固定返回 min_timeout_seconds。",
        findings=[
            Finding(
                kind=FindingKind.ROOT_CAUSE,
                statement="动态超时计算未被使用。",
                confidence=Confidence.CONFIRMED,
                evidence_ids=["E1", "E2"],
            )
        ],
        evidence=evidence,
        recommendations=[
            Recommendation(
                action="修复 build_upload_timeout。",
                rationale="不能固定返回 min_timeout_seconds。",
                evidence_ids=["E1", "E2"],
                verification_steps=["重新运行失败测试"],
            )
        ],
    )


def make_factory(
    clients: list[MockLLMClient],
) -> tuple[Iterator[MockLLMClient], object]:
    iterator = iter(clients)

    def factory():
        return next(iterator)

    return iterator, factory


def test_live_ci_diagnosis_scores_real_service_contract() -> None:
    report = make_report()
    _, factory = make_factory(
        [MockLLMClient(responses=[LLMResponse.final_answer(report.model_dump_json())])]
    )

    run = run_live_ci_diagnosis(
        llm_client_factory=factory,
        commit_id="abc123",
        workspace="examples/sample_repo",
        workspace_label="examples/sample_repo",
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
        expected_keywords=["build_upload_timeout", "min_timeout_seconds"],
        ci_evidence_collector=FixedCollector(make_input()),
    )

    assert run.report is not None
    assert run.metrics.diagnosed is True
    assert run.metrics.required_evidence_covered is True
    assert run.metrics.evidence_references_grounded is True
    assert run.metrics.root_cause_finding_count == 1
    assert run.metrics.recommendation_count == 1
    assert run.metrics.expected_keyword_hit_rate == 1
    assert run.metrics.passed is True


def test_live_ci_diagnosis_retries_invalid_model_output() -> None:
    report = make_report()
    _, factory = make_factory(
        [
            MockLLMClient(responses=[LLMResponse.final_answer("not-json")]),
            MockLLMClient(
                responses=[LLMResponse.final_answer(report.model_dump_json())]
            ),
        ]
    )

    run = run_live_ci_diagnosis(
        llm_client_factory=factory,
        commit_id="abc123",
        workspace="examples/sample_repo",
        workspace_label="examples/sample_repo",
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
        expected_keywords=["build_upload_timeout", "min_timeout_seconds"],
        ci_evidence_collector=FixedCollector(make_input()),
        max_attempts=2,
    )

    assert run.attempt_count == 2
    assert run.attempt_errors == ["invalid_report"]
    assert run.metrics.passed is True


def test_live_ci_diagnosis_metrics_fail_missing_root_cause_keyword() -> None:
    report = make_report().model_copy(
        update={
            "summary": "上传测试失败。",
            "findings": [
                Finding(
                    kind=FindingKind.SYMPTOM,
                    statement="timeout 是 3。",
                    confidence=Confidence.CONFIRMED,
                    evidence_ids=["E1"],
                )
            ],
            "recommendations": [],
        }
    )

    metrics = evaluate_live_ci_diagnosis(
        report,
        ["build_upload_timeout", "min_timeout_seconds"],
    )

    assert metrics.root_cause_finding_count == 0
    assert metrics.recommendation_count == 0
    assert metrics.expected_keyword_hit_rate == 0
    assert metrics.passed is False


def test_live_ci_diagnosis_report_is_traceable_and_has_boundary() -> None:
    report = make_report()
    _, factory = make_factory(
        [MockLLMClient(responses=[LLMResponse.final_answer(report.model_dump_json())])]
    )
    run = run_live_ci_diagnosis(
        llm_client_factory=factory,
        commit_id="abc123",
        workspace="/private/machine/path/sample_repo",
        workspace_label="examples/sample_repo",
        provider="openai-compatible-live",
        model="real-model",
        api_mode="responses",
        expected_keywords=["build_upload_timeout", "min_timeout_seconds"],
        ci_evidence_collector=FixedCollector(make_input()),
    )

    rendered = render_live_ci_diagnosis_report(
        run,
        generated_at="2026-07-30T00:00:00Z",
        commit_id="revision",
    )

    assert "openai-compatible-live" in rendered
    assert "real-model" in rendered
    assert "End-to-End Passed | True" in rendered
    assert "Root Cause Findings | 1" in rendered
    assert "examples/sample_repo" in rendered
    assert "/private/machine/path" not in rendered
    assert "does not claim universal diagnosis accuracy" in rendered
