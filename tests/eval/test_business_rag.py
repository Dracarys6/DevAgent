import pytest

from devagent.diagnosis import Evidence, EvidenceKind, MissingEvidence
from devagent.eval.business_rag import (
    BusinessRAGCase,
    evaluate_business_rag,
    render_business_rag_report,
)


def make_case(
    case_id: str,
    *,
    baseline_chars: int = 1_000,
    retrieval_locator: str = ("path=src/app.py;lines=1-4;chunk_id=chunk-app;rank=1"),
) -> BusinessRAGCase:
    return BusinessRAGCase(
        case_id=case_id,
        scenario="ci_failure",
        baseline_context_chars=baseline_chars,
        evidence=[
            Evidence(
                evidence_id="E1",
                kind=EvidenceKind.CI_RESULT,
                tool_name="get_ci_result",
                source="pipeline-1",
                locator="commit_id=abc123",
                excerpt="failure" * 10,
            ),
            Evidence(
                evidence_id="E2",
                kind=EvidenceKind.KNOWLEDGE,
                tool_name="knowledge_retrieve",
                source="workspace",
                locator=retrieval_locator,
                excerpt="related code" * 10,
            ),
        ],
    )


def test_evaluate_business_rag_scores_context_and_evidence_contract() -> None:
    run = evaluate_business_rag([make_case("ci-1"), make_case("ci-2")])

    assert run.metrics.passed is True
    assert run.metrics.average_context_reduction_rate == pytest.approx(0.81)
    assert run.metrics.retrieval_locator_completeness_rate == 1
    assert run.metrics.domain_flow_availability_rate == 1
    assert run.metrics.duplicate_location_count == 0
    assert run.cases[0].retrieval_evidence_chars == 120


def test_evaluate_business_rag_records_explicit_fallback() -> None:
    case = make_case("ci-fallback")
    case.missing_evidence = [
        MissingEvidence(
            needed="supplemental context",
            reason="retrieval unavailable",
            suggested_tool="knowledge_retrieve",
        )
    ]

    run = evaluate_business_rag([case])

    assert run.metrics.fallback_case_count == 1


def test_evaluate_business_rag_fails_incomplete_locator() -> None:
    run = evaluate_business_rag(
        [make_case("ci-invalid", retrieval_locator="path=src/app.py")]
    )

    assert run.metrics.retrieval_locator_completeness_rate == 0
    assert run.metrics.passed is False


def test_evaluate_business_rag_requires_retrieval_and_domain_evidence() -> None:
    case = make_case("ci-no-retrieval")
    case.evidence = [case.evidence[0]]

    with pytest.raises(ValueError, match="至少需要一条检索 evidence"):
        evaluate_business_rag([case])

    case = make_case("ci-no-domain")
    case.evidence = [case.evidence[1]]
    with pytest.raises(ValueError, match="缺少领域权威 evidence"):
        evaluate_business_rag([case])


def test_render_business_rag_report_excludes_evidence_body() -> None:
    run = evaluate_business_rag([make_case("ci-1")])

    report = render_business_rag_report(
        run,
        generated_at="2026-08-03T00:00:00Z",
        revision="abc123",
    )

    assert "Average Context Reduction" in report
    assert "ci-1" in report
    assert "related code" not in report
