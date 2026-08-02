from collections.abc import Sequence
from pathlib import Path

import pytest

from devagent.eval import (
    HybridBaselineError,
    HybridBaselineSummary,
    RAGEvalCase,
    render_hybrid_baseline_report,
    run_hybrid_baseline,
    summarize_hybrid_baseline_run,
)
from devagent.memory import EmbeddingProviderError, EmbeddingVector


class MeasuredFixedProvider:
    provider_name = "fixed-hybrid-eval"
    model_name = "fixed-model"

    def __init__(
        self,
        *,
        fail_documents: bool = False,
        fail_query: str | None = None,
    ) -> None:
        self.fail_documents = fail_documents
        self.fail_query = fail_query
        self.document_request_count = 0
        self.query_request_count = 0
        self.input_tokens = 0
        self.observed_dimensions: int | None = None
        self.document_batches: list[list[str]] = []

    def embed_documents(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        self.document_request_count += 1
        self.document_batches.append(list(texts))
        if self.fail_documents:
            raise EmbeddingProviderError("document failure")
        self.observed_dimensions = 2
        self.input_tokens += len(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> EmbeddingVector:
        self.query_request_count += 1
        if text == self.fail_query:
            raise EmbeddingProviderError("query failure")
        self.input_tokens += 1
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> EmbeddingVector:
        folded = text.casefold()
        if "alpha" in folded:
            return (1.0, 0.0)
        if "beta" in folded:
            return (0.0, 1.0)
        return (-1.0, 0.0)


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "alpha.txt").write_text(
        "alpha timeout configuration evidence",
        encoding="utf-8",
    )
    (workspace / "beta.txt").write_text(
        "beta permission policy evidence",
        encoding="utf-8",
    )
    return workspace


def make_cases() -> list[RAGEvalCase]:
    return [
        RAGEvalCase(
            case_id="alpha-case",
            description="find alpha",
            category="code",
            query="alpha timeout",
            expected_paths=["alpha.txt"],
            expected_keywords=["alpha"],
            top_k=1,
        ),
        RAGEvalCase(
            case_id="negative-case",
            description="unrelated domain",
            category="negative",
            query="payment billing",
            expect_empty=True,
            top_k=1,
        ),
    ]


def test_hybrid_baseline_reuses_one_document_index_and_query_embedding(
    tmp_path: Path,
) -> None:
    provider = MeasuredFixedProvider()

    run = run_hybrid_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=provider,
    )

    assert run.document_count == 2
    assert run.chunk_count == 2
    assert run.document_embedding_call_count == 1
    assert run.query_embedding_call_count == 2
    assert provider.document_request_count == 1
    assert provider.query_request_count == 2
    assert len(provider.document_batches) == 1
    assert run.hybrid_run.metrics.evidence_hit_rate == 1
    assert run.hybrid_run.metrics.mrr_at_5 == 1
    assert run.hybrid_run.metrics.empty_result_accuracy == 0
    assert run.vector_run.metrics.evidence_hit_rate == 1
    assert run.bm25_run.metrics.empty_result_accuracy == 1
    assert run.candidate_source_traceability == 1
    assert run.traced_hybrid_evidence_count == run.returned_hybrid_evidence_count
    assert run.hybrid_context.context_reduction_rate > 0


def test_hybrid_baseline_records_vector_failure_without_losing_bm25(
    tmp_path: Path,
) -> None:
    provider = MeasuredFixedProvider(fail_query="alpha timeout")

    run = run_hybrid_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=provider,
    )

    vector_prediction = run.vector_run.predictions[0]
    hybrid_prediction = run.hybrid_run.predictions[0]
    bm25_prediction = run.bm25_run.predictions[0]
    assert vector_prediction.error_code == "VECTOR_RETRIEVAL_ERROR"
    assert hybrid_prediction.error_code == "HYBRID_SOURCE_ERROR"
    assert bm25_prediction.tool_success is True
    assert provider.query_request_count == 2


def test_hybrid_baseline_rejects_index_failure(
    tmp_path: Path,
) -> None:
    provider = MeasuredFixedProvider(fail_documents=True)

    with pytest.raises(HybridBaselineError, match="索引构建失败"):
        run_hybrid_baseline(
            make_cases(),
            workspace=make_workspace(tmp_path),
            embedding_provider=provider,
        )


def test_hybrid_baseline_validates_cases_before_embedding(
    tmp_path: Path,
) -> None:
    provider = MeasuredFixedProvider()

    with pytest.raises(HybridBaselineError, match="不能为空"):
        run_hybrid_baseline(
            [],
            workspace=make_workspace(tmp_path),
            embedding_provider=provider,
        )

    assert provider.document_request_count == 0
    assert provider.query_request_count == 0


def test_hybrid_summary_excludes_query_and_evidence_content(
    tmp_path: Path,
) -> None:
    run = run_hybrid_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=MeasuredFixedProvider(),
    )

    summary = summarize_hybrid_baseline_run(run)
    serialized = summary.model_dump_json()
    restored = HybridBaselineSummary.model_validate_json(serialized)

    assert restored == summary
    assert summary.case_ids == ["alpha-case", "negative-case"]
    assert "alpha timeout configuration evidence" not in serialized
    assert "alpha timeout" not in serialized
    assert "payment billing" not in serialized
    assert "api_key" not in serialized


def test_hybrid_report_compares_all_strategies_and_costs(tmp_path: Path) -> None:
    run = run_hybrid_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=MeasuredFixedProvider(),
    )

    report = render_hybrid_baseline_report(
        run,
        generated_at="2026-08-02T00:00:00+00:00",
        commit_id="abc123 + working tree",
    )

    assert "Hybrid RRF" in report
    assert "BM25" in report
    assert "Vector" in report
    assert "Candidate source traceability: 100.0%" in report
    assert "Document embedding calls: 1" in report
    assert "Query embedding calls: 2" in report
    assert "private-key" not in report
    assert "base_url" not in report
