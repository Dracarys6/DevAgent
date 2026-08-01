from collections.abc import Sequence
from pathlib import Path

import pytest

from devagent.eval import (
    RAGEvalCase,
    VectorBaselineError,
    VectorBaselineRun,
    VectorBaselineSummary,
    render_vector_baseline_report,
    run_vector_baseline,
    summarize_vector_baseline_run,
)
from devagent.memory import EmbeddingProviderError, EmbeddingVector


class MeasuredFixedProvider:
    provider_name = "fixed-vector-eval"
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
        vectors = [self._vector(text) for text in texts]
        self.observed_dimensions = 2
        self.input_tokens += len(texts)
        return vectors

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


def test_vector_baseline_builds_one_index_and_reuses_it_for_queries(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    provider = MeasuredFixedProvider()

    run = run_vector_baseline(
        make_cases(),
        workspace=workspace,
        embedding_provider=provider,
    )

    assert run.document_count == 2
    assert run.chunk_count == 2
    assert run.vector_dimensions == 2
    assert run.document_embedding_call_count == 1
    assert run.query_embedding_call_count == 2
    assert provider.document_request_count == 1
    assert len(provider.document_batches) == 1
    assert run.vector_run.metrics.evidence_hit_rate == 1
    assert run.vector_run.metrics.mrr_at_5 == 1
    assert run.vector_run.metrics.empty_result_accuracy == 0
    assert run.bm25_run.metrics.evidence_hit_rate == 1
    assert run.bm25_run.metrics.empty_result_accuracy == 1
    assert run.vector_context.context_reduction_rate > 0


def test_vector_baseline_records_query_failure_without_aborting_other_cases(
    tmp_path: Path,
) -> None:
    provider = MeasuredFixedProvider(fail_query="alpha timeout")

    run = run_vector_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=provider,
    )

    prediction = run.vector_run.predictions[0]
    assert prediction.tool_success is False
    assert prediction.error_code == "VECTOR_RETRIEVAL_ERROR"
    assert run.vector_run.metrics.failed_tool_case_ids == ["alpha-case"]
    assert provider.query_request_count == 2


def test_vector_baseline_converts_index_failure(
    tmp_path: Path,
) -> None:
    provider = MeasuredFixedProvider(fail_documents=True)

    with pytest.raises(VectorBaselineError, match="索引构建失败"):
        run_vector_baseline(
            make_cases(),
            workspace=make_workspace(tmp_path),
            embedding_provider=provider,
        )


def test_vector_baseline_report_is_sanitized_and_json_round_trips(
    tmp_path: Path,
) -> None:
    run = run_vector_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=MeasuredFixedProvider(),
    )

    report = render_vector_baseline_report(
        run,
        generated_at="2026-08-01T00:00:00+00:00",
        commit_id="abc123 + working tree",
    )
    restored = VectorBaselineRun.model_validate_json(run.model_dump_json())

    assert restored == run
    assert "fixed-vector-eval" in report
    assert "Top-5 Evidence Hit Rate" in report
    assert "Document embedding API calls: 1" in report
    assert "private-key" not in report
    assert "base_url" not in report


def test_vector_baseline_summary_excludes_query_and_evidence_content(
    tmp_path: Path,
) -> None:
    run = run_vector_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=MeasuredFixedProvider(),
    )

    summary = summarize_vector_baseline_run(run)
    serialized = summary.model_dump_json()

    assert "alpha timeout configuration evidence" not in serialized
    assert "alpha timeout" not in serialized
    assert "payment billing" not in serialized
    assert summary.vector_metrics == run.vector_run.metrics
    assert summary.bm25_metrics == run.bm25_run.metrics
    assert summary.case_ids == ["alpha-case", "negative-case"]
    assert VectorBaselineSummary.model_validate_json(serialized) == summary
