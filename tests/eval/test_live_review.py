from pathlib import Path

from devagent.diagnosis import Evidence, EvidenceKind
from devagent.eval import (
    LiveReviewExpectedFinding,
    create_live_review_collector,
    evaluate_live_code_review,
    render_live_code_review_report,
    run_live_code_review,
)
from devagent.llm import LLMResponse, MockLLMClient
from devagent.review import (
    CodeReviewInput,
    CodeReviewReport,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)


class FixedCollector:
    def __init__(self, review_input: CodeReviewInput) -> None:
        self.review_input = review_input

    def collect(
        self,
        *,
        review_id: str,
        base_ref: str,
        head_ref: str,
        workspace: Path,
    ) -> CodeReviewInput:
        return self.review_input.model_copy(
            update={
                "review_id": review_id,
                "base_ref": base_ref,
                "head_ref": head_ref,
                "workspace": str(workspace),
            }
        )


def make_expected() -> LiveReviewExpectedFinding:
    return LiveReviewExpectedFinding(
        category=ReviewCategory.CORRECTNESS,
        severities=[
            ReviewSeverity.MEDIUM,
            ReviewSeverity.HIGH,
            ReviewSeverity.CRITICAL,
        ],
        file_path="src/sample_app/uploader.py",
        line=24,
        side=ReviewLineSide.HEAD,
        keywords=["build_upload_timeout", "min_timeout_seconds"],
    )


def make_evidence() -> list[Evidence]:
    return [
        Evidence(
            evidence_id="E1",
            kind=EvidenceKind.GIT_DIFF,
            tool_name="git_compare",
            source="head-sha",
            locator="hunks=1",
            excerpt="+return self.config.min_timeout_seconds",
        ),
        Evidence(
            evidence_id="E2",
            kind=EvidenceKind.CODE,
            tool_name="read_file",
            source="workspace",
            locator="path=src/sample_app/uploader.py;lines=1-24",
            excerpt="24: return self.config.min_timeout_seconds",
        ),
    ]


def make_input(workspace: Path) -> CodeReviewInput:
    return CodeReviewInput(
        review_id="input-review",
        base_ref="base",
        head_ref="head",
        workspace=str(workspace),
        evidence=make_evidence(),
    )


def make_report(*, extra_finding: bool = False) -> CodeReviewReport:
    findings = [
        ReviewFinding(
            finding_id="R1",
            severity=ReviewSeverity.HIGH,
            category=ReviewCategory.CORRECTNESS,
            title="动态上传超时被固定最小值覆盖",
            description=(
                "build_upload_timeout 固定返回 min_timeout_seconds，"
                "大文件上传会过早超时。"
            ),
            file_path="src/sample_app/uploader.py",
            line_start=24,
            side=ReviewLineSide.HEAD,
            evidence_ids=["E1", "E2"],
            suggestion="计算动态超时并保留最小值下限。",
            verification_steps=["运行大文件上传测试"],
        )
    ]
    if extra_finding:
        findings.append(
            findings[0].model_copy(
                update={
                    "finding_id": "R2",
                    "category": ReviewCategory.MAINTAINABILITY,
                    "line_start": 10,
                    "title": "额外误报",
                }
            )
        )
    return CodeReviewReport(
        review_id="model-review",
        base_ref="wrong-base",
        head_ref="wrong-head",
        status=ReviewStatus.REVIEWED,
        summary="发现 build_upload_timeout 没有使用动态 timeout。",
        findings=findings,
        evidence=make_evidence(),
    )


def test_live_review_runner_scores_service_evidence_and_finding(tmp_path: Path) -> None:
    report = make_report()

    run = run_live_code_review(
        llm_client_factory=lambda: MockLLMClient(
            responses=[LLMResponse.final_answer(report.model_dump_json())]
        ),
        base_ref="base",
        head_ref="head",
        workspace=tmp_path,
        workspace_label="examples/sample_repo",
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
        expected_finding=make_expected(),
        evidence_collector=FixedCollector(make_input(tmp_path)),
    )

    assert run.report is not None
    assert run.report.review_id != "model-review"
    assert run.report.base_ref == "base"
    assert run.report.evidence == make_evidence()
    assert run.attempt_count == 1
    assert run.metrics.required_evidence_covered is True
    assert run.metrics.evidence_references_grounded is True
    assert run.metrics.expected_finding_matched is True
    assert run.metrics.expected_keyword_hit_rate == 1
    assert run.metrics.unexpected_finding_count == 0
    assert run.metrics.passed is True


def test_live_review_runner_records_service_repair_attempt(tmp_path: Path) -> None:
    report = make_report()
    client = MockLLMClient(
        responses=[
            LLMResponse.final_answer("not-json"),
            LLMResponse.final_answer(report.model_dump_json()),
        ]
    )

    run = run_live_code_review(
        llm_client_factory=lambda: client,
        base_ref="base",
        head_ref="head",
        workspace=tmp_path,
        workspace_label="examples/sample_repo",
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
        expected_finding=make_expected(),
        evidence_collector=FixedCollector(make_input(tmp_path)),
        max_attempts=2,
    )

    assert run.attempt_count == 2
    assert run.metrics.passed is True


def test_live_review_metrics_penalize_additional_unmatched_finding() -> None:
    metrics = evaluate_live_code_review(
        make_report(extra_finding=True), make_expected()
    )

    assert metrics.expected_finding_matched is True
    assert metrics.unexpected_finding_count == 1
    assert metrics.passed is False


def test_live_review_metrics_accept_bounded_medium_correctness_risk() -> None:
    report = make_report()
    report.findings[0].severity = ReviewSeverity.MEDIUM

    metrics = evaluate_live_code_review(report, make_expected())

    assert metrics.expected_finding_matched is True
    assert metrics.passed is True


def test_live_review_collector_excludes_narrative_answers_and_keeps_locations() -> None:
    collector = create_live_review_collector()

    review_input = collector.collect(
        review_id="live-probe",
        base_ref="7229c86^",
        head_ref="7229c86",
        workspace=Path("examples/sample_repo").resolve(),
    )

    combined = "\n".join(item.excerpt for item in review_input.evidence)
    assert {item.kind for item in review_input.evidence} == {
        EvidenceKind.GIT_DIFF,
        EvidenceKind.CODE,
    }
    assert "src/sample_app/uploader.py" in combined
    assert "tests/test_uploader.py" in combined
    assert "return self.config.min_timeout_seconds" in combined
    assert "README.md" not in combined
    assert "ci_failure_notes.md" not in combined
    assert "故意保留一个回归" not in combined
    assert review_input.missing_evidence == []


def test_live_review_report_is_traceable_and_hides_absolute_workspace(
    tmp_path: Path,
) -> None:
    report = make_report()
    run = run_live_code_review(
        llm_client_factory=lambda: MockLLMClient(
            responses=[LLMResponse.final_answer(report.model_dump_json())]
        ),
        base_ref="base",
        head_ref="head",
        workspace=tmp_path,
        workspace_label="examples/sample_repo",
        provider="openai-compatible-live",
        model="real-model",
        api_mode="responses",
        expected_finding=make_expected(),
        evidence_collector=FixedCollector(make_input(tmp_path)),
    )

    rendered = render_live_code_review_report(
        run,
        generated_at="2026-07-31T00:00:00Z",
        commit_id="revision",
    )

    assert "openai-compatible-live" in rendered
    assert "Expected Finding Matched | True" in rendered
    assert "src/sample_app/uploader.py:24" in rendered
    assert str(tmp_path) not in rendered
    assert str(tmp_path) not in run.model_dump_json()
    assert "real GitHub publication path" in rendered
