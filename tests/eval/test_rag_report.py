from pathlib import Path

import pytest
from pydantic import ValidationError

from devagent.eval import (
    RAGContextCategoryMetrics,
    RAGContextMetrics,
    RAGEvalCase,
    RAGEvalPrediction,
    RAGEvalRun,
    evaluate_rag_context,
    evaluate_rag_predictions,
    load_rag_eval_cases,
    render_rag_baseline_report,
    run_rag_eval,
)
from devagent.memory import EvidenceSnippet, LineRange, RetrievalResult

PROJECT_ROOT = Path(__file__).parents[2]
RAG_CASE_DIR = PROJECT_ROOT / "eval" / "cases" / "rag"
RAG_WORKSPACE = RAG_CASE_DIR / "workspace"


def make_case(
    *,
    case_id: str,
    category: str,
    expect_empty: bool = False,
) -> RAGEvalCase:
    return RAGEvalCase(
        case_id=case_id,
        description="RAG report test case",
        category=category,
        query="alpha" if not expect_empty else "unknown",
        expect_empty=expect_empty,
        expected_paths=[] if expect_empty else ["src/app.py"],
        expected_keywords=[] if expect_empty else ["alpha"],
    )


def make_result(
    *,
    query: str,
    empty: bool = False,
    path: str = "src/app.py",
    excerpt: str = "alpha",
) -> RetrievalResult:
    items = (
        []
        if empty
        else [
            EvidenceSnippet(
                chunk_id="chunk-1",
                document_id="document-1",
                source="workspace",
                path=path,
                line_range=LineRange(start=1, end=1),
                excerpt=excerpt,
                score=1,
                rank=1,
            )
        ]
    )
    return RetrievalResult(
        query=query,
        top_k=5,
        total_candidates=len(items),
        items=items,
        retrieval_ms=1,
    )


def make_predictions() -> list[RAGEvalPrediction]:
    return [
        RAGEvalPrediction(
            case_id="positive",
            predicted_tool_name="knowledge_retrieve",
            tool_success=True,
            retrieval_result=make_result(query="alpha"),
            answer_text="alpha",
            latency_ms=2,
        ),
        RAGEvalPrediction(
            case_id="negative",
            predicted_tool_name="knowledge_retrieve",
            tool_success=True,
            retrieval_result=make_result(query="unknown", empty=True),
            answer_text="",
            latency_ms=3,
        ),
    ]


def make_cases() -> list[RAGEvalCase]:
    return [
        make_case(case_id="positive", category="ci"),
        make_case(case_id="negative", category="negative", expect_empty=True),
    ]


def write_workspace(root: Path) -> int:
    files = {
        "src/app.py": "alpha beta\n",
        "docs/other.md": "unrelated context\n",
    }
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return sum(len(content) for content in files.values())


def test_evaluate_rag_context_excludes_negative_cases(
    tmp_path: Path,
) -> None:
    corpus_chars = write_workspace(tmp_path)

    metrics = evaluate_rag_context(
        make_cases(),
        make_predictions(),
        workspace=tmp_path,
    )

    assert metrics.corpus_document_count == 2
    assert metrics.corpus_chars_per_case == corpus_chars
    assert metrics.positive_case_count == 1
    assert metrics.full_context_chars_total == corpus_chars
    assert metrics.retrieved_context_chars_total == len("alpha")
    assert metrics.average_retrieved_context_chars == len("alpha")
    assert metrics.context_reduction_rate == pytest.approx(
        1 - len("alpha") / corpus_chars
    )
    assert metrics.categories[0].category == "ci"
    assert metrics.categories[0].evidence_hit_rate == 1


def test_tool_failure_reduces_quality_instead_of_becoming_successful_compression(
    tmp_path: Path,
) -> None:
    write_workspace(tmp_path)
    predictions = make_predictions()
    predictions[0] = RAGEvalPrediction(
        case_id="positive",
        predicted_tool_name="knowledge_retrieve",
        tool_success=False,
        latency_ms=1,
        error_code="TOOL_EXECUTION_ERROR",
    )

    quality = evaluate_rag_predictions(make_cases(), predictions)
    context = evaluate_rag_context(
        make_cases(),
        predictions,
        workspace=tmp_path,
    )

    assert quality.evidence_hit_rate == 0
    assert quality.failed_tool_case_ids == ["positive"]
    assert context.context_reduction_rate == 1
    assert context.categories[0].evidence_hit_rate == 0


def test_context_models_reject_inconsistent_counts_and_order() -> None:
    with pytest.raises(ValidationError, match="evidence_hit_count"):
        RAGContextCategoryMetrics(
            category="ci",
            case_count=1,
            evidence_hit_count=2,
            evidence_hit_rate=1,
            average_retrieved_context_chars=1,
            context_reduction_rate=0.5,
        )

    categories = [
        RAGContextCategoryMetrics(
            category=category,
            case_count=1,
            evidence_hit_count=1,
            evidence_hit_rate=1,
            average_retrieved_context_chars=1,
            context_reduction_rate=0.5,
        )
        for category in ("review", "ci")
    ]
    with pytest.raises(ValidationError, match="排序"):
        RAGContextMetrics(
            corpus_document_count=1,
            corpus_chars_per_case=2,
            positive_case_count=2,
            full_context_chars_total=4,
            retrieved_context_chars_total=2,
            average_full_context_chars=2,
            average_retrieved_context_chars=1,
            max_retrieved_context_chars=1,
            context_reduction_rate=0.5,
            categories=categories,
        )


def test_evaluate_rag_context_rejects_empty_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="没有可用文档"):
        evaluate_rag_context(
            make_cases(),
            make_predictions(),
            workspace=tmp_path,
        )


def test_evaluate_rag_context_rejects_all_negative_cases(tmp_path: Path) -> None:
    write_workspace(tmp_path)
    cases = [make_case(case_id="negative", category="negative", expect_empty=True)]
    predictions = [make_predictions()[1]]

    with pytest.raises(ValueError, match="至少需要一个正样本"):
        evaluate_rag_context(cases, predictions, workspace=tmp_path)


def test_render_report_contains_metrics_business_slices_and_boundaries(
    tmp_path: Path,
) -> None:
    write_workspace(tmp_path)
    cases = make_cases()
    predictions = make_predictions()
    run = RAGEvalRun(
        metrics=evaluate_rag_predictions(cases, predictions),
        predictions=predictions,
    )
    context = evaluate_rag_context(cases, predictions, workspace=tmp_path)

    report = render_rag_baseline_report(
        run=run,
        context_metrics=context,
        commit_id="abc123",
        generated_at="2026-07-30T00:00:00Z",
    )

    assert "Top-5 Evidence Hit Rate | 100.0%" in report
    assert "Context Reduction Rate" in report
    assert "| ci | 1 | 100.0%" in report
    assert "Full-corpus oracle injection" in report
    assert "Negative cases" in report
    assert "live-LLM answer accuracy" in report
    assert "abc123" in report


def test_fixed_rag_baseline_meets_week8_targets() -> None:
    cases = load_rag_eval_cases(RAG_CASE_DIR)
    run = run_rag_eval(cases, workspace=RAG_WORKSPACE)

    context = evaluate_rag_context(
        cases,
        run.predictions,
        workspace=RAG_WORKSPACE,
    )

    assert context.corpus_document_count == 17
    assert context.corpus_chars_per_case == 4_923
    assert context.positive_case_count == 18
    assert context.average_retrieved_context_chars == pytest.approx(1040.6666666666667)
    assert context.context_reduction_rate == pytest.approx(0.7886112803845893)
    assert run.metrics.evidence_hit_rate >= 0.8
    assert run.metrics.p95_latency_ms < 800
    assert run.metrics.evidence_location_completeness >= 0.9

    categories = {item.category: item for item in context.categories}
    for category in ("ci", "log", "diagnosis", "review"):
        assert categories[category].evidence_hit_rate == 1
