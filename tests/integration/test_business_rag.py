from pathlib import Path

from devagent.diagnosis import (
    EvidenceKind,
    LocalCIEvidenceCollector,
    LocalLogEvidenceCollector,
)
from devagent.eval import BusinessRAGCase, evaluate_business_rag
from devagent.review import LocalCodeReviewEvidenceCollector
from devagent.tools.knowledge_tools import (
    DEFAULT_KNOWLEDGE_SERVICE,
    load_workspace_documents,
)


def test_business_collectors_add_bounded_retrieval_to_authoritative_evidence() -> None:
    workspace = Path("examples/sample_repo").resolve()
    retrieve = DEFAULT_KNOWLEDGE_SERVICE.retrieve

    ci_input = LocalCIEvidenceCollector(knowledge_retriever=retrieve).collect(
        report_id="ci-business-rag",
        commit_id="7229c86",
        workspace=str(workspace),
    )
    log_input = LocalLogEvidenceCollector(knowledge_retriever=retrieve).collect(
        report_id="log-business-rag",
        task_id="task_001",
        data_dir="examples/sample_logs",
        workspace=str(workspace),
    )
    review_input = LocalCodeReviewEvidenceCollector(
        knowledge_retriever=retrieve
    ).collect(
        review_id="review-business-rag",
        base_ref="7229c86^",
        head_ref="7229c86",
        workspace=workspace,
    )
    legacy_review_input = LocalCodeReviewEvidenceCollector().collect(
        review_id="review-baseline",
        base_ref="7229c86^",
        head_ref="7229c86",
        workspace=workspace,
    )

    workspace_chars = sum(
        len(document.content) for document in load_workspace_documents(workspace)
    )
    run = evaluate_business_rag(
        [
            _make_case(
                "ci-upload-timeout",
                "ci_failure",
                ci_input.evidence,
                ci_input.missing_evidence,
                workspace_chars=workspace_chars,
            ),
            _make_case(
                "log-upload-timeout",
                "log_failure",
                log_input.evidence,
                log_input.missing_evidence,
                workspace_chars=workspace_chars,
            ),
            BusinessRAGCase(
                case_id="review-upload-timeout",
                scenario="code_review",
                baseline_context_chars=sum(
                    len(item.excerpt) for item in legacy_review_input.evidence
                ),
                evidence=review_input.evidence,
                missing_evidence=review_input.missing_evidence,
            ),
        ]
    )

    assert run.metrics.passed is True
    assert run.metrics.average_context_reduction_rate >= 0.40
    assert run.metrics.retrieval_locator_completeness_rate == 1
    assert run.metrics.domain_flow_availability_rate == 1
    assert run.metrics.duplicate_location_count == 0
    assert all(case.retrieval_evidence_count >= 1 for case in run.cases)
    assert EvidenceKind.CI_RESULT in {item.kind for item in ci_input.evidence}
    assert EvidenceKind.LOG in {item.kind for item in log_input.evidence}
    assert EvidenceKind.GIT_DIFF in {item.kind for item in review_input.evidence}


def _make_case(
    case_id: str,
    scenario: str,
    evidence: list,
    missing_evidence: list,
    *,
    workspace_chars: int,
) -> BusinessRAGCase:
    domain_chars = sum(
        len(item.excerpt) for item in evidence if item.kind != EvidenceKind.KNOWLEDGE
    )
    return BusinessRAGCase(
        case_id=case_id,
        scenario=scenario,
        baseline_context_chars=domain_chars + workspace_chars,
        evidence=evidence,
        missing_evidence=missing_evidence,
    )
