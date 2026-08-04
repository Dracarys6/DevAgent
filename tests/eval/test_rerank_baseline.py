from collections.abc import Sequence
from pathlib import Path

import pytest

from devagent.eval import (
    RAGEvalCase,
    RerankBaselineError,
    RerankBaselineSummary,
    render_rerank_baseline_report,
    run_rerank_baseline,
    summarize_rerank_baseline_run,
)
from devagent.memory import (
    EmbeddingVector,
    EvidenceSnippet,
    RerankerError,
    RerankScore,
)


class FixedEmbeddingProvider:
    provider_name = "fixed"
    model_name = "fixed-embedding"

    def __init__(self) -> None:
        self.observed_dimensions: int | None = None
        self.document_request_count = 0
        self.query_request_count = 0
        self.input_tokens = 0

    def embed_documents(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        self.document_request_count += 1
        self.input_tokens += len(texts)
        self.observed_dimensions = 2
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> EmbeddingVector:
        self.query_request_count += 1
        self.input_tokens += 1
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> EmbeddingVector:
        return (1.0, 0.0) if "alpha" in text.casefold() else (0.0, 1.0)


class FixedMeasuredReranker:
    reranker_name = "fixed-reranker"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.request_count = 0
        self.repair_count = 0
        self.scored_candidate_count = 0
        self.input_char_count = 0
        self.output_char_count = 0
        self.timeout_seconds = None
        self.transport_max_retries = None

    def score(
        self,
        query: str,
        candidates: Sequence[EvidenceSnippet],
    ) -> list[RerankScore]:
        self.request_count += 1
        self.scored_candidate_count += len(candidates)
        self.input_char_count += len(query) + sum(
            len(item.excerpt) for item in candidates
        )
        self.output_char_count += len(candidates) * 20
        if self.fail:
            raise RerankerError("private provider failure", code="provider_timeout")
        return [
            RerankScore(
                chunk_id=item.chunk_id,
                score=0.9 if item.path == "beta.txt" else 0.1,
            )
            for item in reversed(candidates)
        ]


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "alpha.txt").write_text("alpha signal", encoding="utf-8")
    (workspace / "beta.txt").write_text("beta target evidence", encoding="utf-8")
    return workspace


def make_cases() -> list[RAGEvalCase]:
    return [
        RAGEvalCase(
            case_id="promote-beta",
            description="rerank target",
            category="code",
            query="alpha signal",
            expected_paths=["beta.txt"],
            expected_keywords=["beta"],
            top_k=2,
        ),
        RAGEvalCase(
            case_id="negative",
            description="unrelated",
            category="negative",
            query="payment billing",
            expect_empty=True,
            top_k=2,
        ),
    ]


def test_rerank_baseline_compares_same_candidates_and_improves_rank(
    tmp_path: Path,
) -> None:
    provider = FixedEmbeddingProvider()
    reranker = FixedMeasuredReranker()

    run = run_rerank_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=provider,
        reranker=reranker,
        candidate_k=2,
    )

    observation = run.observations[0]
    assert observation.before_relevant_rank == 2
    assert observation.after_relevant_rank == 1
    assert observation.rerank_status == "success"
    assert run.before_run.metrics.mrr_at_5 == 0.5
    assert run.after_run.metrics.mrr_at_5 == 1
    assert run.query_embedding_call_count == 2
    assert run.reranker_request_count == 2
    assert run.reranker_scored_candidate_count == 4
    assert run.reranker_input_char_count > 0
    assert run.reranker_output_char_count == 80
    assert run.fallback_count == 0
    assert run.metadata_completeness == 1


def test_rerank_baseline_records_observable_fallback(tmp_path: Path) -> None:
    run = run_rerank_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=FixedEmbeddingProvider(),
        reranker=FixedMeasuredReranker(fail=True),
        candidate_k=2,
    )

    assert run.fallback_count == 2
    assert all(item.rerank_status == "fallback" for item in run.observations)
    assert all(
        item.rerank_error_code == "provider_timeout" for item in run.observations
    )
    assert run.before_run.metrics.mrr_at_5 == run.after_run.metrics.mrr_at_5
    first = run.after_run.predictions[0].retrieval_result
    assert first is not None
    assert first.items[0].metadata["rerank_error_code"] == "provider_timeout"
    assert "private provider failure" not in first.model_dump_json()


def test_rerank_summary_and_report_exclude_retrieval_content(tmp_path: Path) -> None:
    run = run_rerank_baseline(
        make_cases(),
        workspace=make_workspace(tmp_path),
        embedding_provider=FixedEmbeddingProvider(),
        reranker=FixedMeasuredReranker(),
        candidate_k=2,
    )

    summary = summarize_rerank_baseline_run(run)
    serialized = summary.model_dump_json()
    restored = RerankBaselineSummary.model_validate_json(serialized)
    report = render_rerank_baseline_report(
        run,
        generated_at="2026-08-02T00:00:00+00:00",
        commit_id="abc123 + working tree",
    )

    assert restored == summary
    assert summary.case_ids == ["promote-beta", "negative"]
    assert "alpha signal" not in serialized
    assert "beta target evidence" not in serialized
    assert "Quality Comparison" in report
    assert "Precision@5" in report
    assert "Recall@5" in report
    assert "NDCG@5" in report
    assert "Fallback cases: 0" in report
    assert "promote-beta" in report


def test_rerank_baseline_validates_cases_before_embedding(tmp_path: Path) -> None:
    provider = FixedEmbeddingProvider()

    with pytest.raises(RerankBaselineError, match="不能为空"):
        run_rerank_baseline(
            [],
            workspace=make_workspace(tmp_path),
            embedding_provider=provider,
            reranker=FixedMeasuredReranker(),
        )

    assert provider.document_request_count == 0


@pytest.mark.parametrize("candidate_k", [True, 1, 21])
def test_rerank_baseline_rejects_invalid_candidate_k(
    tmp_path: Path,
    candidate_k: object,
) -> None:
    with pytest.raises(RerankBaselineError, match="candidate_k"):
        run_rerank_baseline(
            make_cases(),
            workspace=make_workspace(tmp_path),
            embedding_provider=FixedEmbeddingProvider(),
            reranker=FixedMeasuredReranker(),
            candidate_k=candidate_k,  # type: ignore[arg-type]
        )
