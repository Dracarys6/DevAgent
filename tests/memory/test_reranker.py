from collections.abc import Sequence

import pytest

from devagent.memory import (
    EvidenceSnippet,
    LineRange,
    RerankerError,
    RerankingError,
    RerankingRetriever,
    RerankingRetrieverConfig,
    RerankScore,
    RetrievalResult,
    rerank_retrieval_result,
)


class FixedReranker:
    reranker_name = "fixed-reranker"

    def __init__(
        self,
        scores: object,
        *,
        error: Exception | None = None,
    ) -> None:
        self.scores = scores
        self.error = error
        self.calls: list[tuple[str, list[str]]] = []

    def score(
        self,
        query: str,
        candidates: Sequence[EvidenceSnippet],
    ) -> list[RerankScore]:
        self.calls.append((query, [item.chunk_id for item in candidates]))
        if self.error is not None:
            raise self.error
        return self.scores  # type: ignore[return-value]


class FixedRetriever:
    def __init__(self, result: RetrievalResult) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalResult:
        self.calls.append((query, top_k))
        return self.result


def make_item(chunk_id: str, *, path: str, rank: int, score: float) -> EvidenceSnippet:
    return EvidenceSnippet(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source="workspace",
        path=path,
        line_range=LineRange(start=rank, end=rank),
        excerpt=f"evidence-{chunk_id}",
        score=score,
        rank=rank,
        metadata={"retrieval_method": "hybrid_rrf"},
    )


def make_result() -> RetrievalResult:
    return RetrievalResult(
        query="find evidence",
        top_k=3,
        total_candidates=3,
        items=[
            make_item("a", path="src/a.py", rank=1, score=0.3),
            make_item("b", path="src/b.py", rank=2, score=0.2),
            make_item("c", path="src/c.py", rank=3, score=0.1),
        ],
        retrieval_ms=2,
    )


def test_rerank_binds_scores_by_chunk_id_and_preserves_evidence() -> None:
    reranker = FixedReranker(
        [
            RerankScore(chunk_id="c", score=0.2),
            RerankScore(chunk_id="a", score=0.4),
            RerankScore(chunk_id="b", score=0.9),
        ]
    )

    result = rerank_retrieval_result(make_result(), reranker=reranker, top_k=2)

    assert [item.chunk_id for item in result.items] == ["b", "a"]
    assert [item.rank for item in result.items] == [1, 2]
    assert result.items[0].path == "src/b.py"
    assert result.items[0].excerpt == "evidence-b"
    assert result.items[0].score == 0.9
    assert result.items[0].metadata["recall_rank"] == "2"
    assert result.items[0].metadata["recall_score"] == repr(0.2)
    assert result.items[0].metadata["rerank_status"] == "success"
    assert result.items[0].metadata["reranker"] == "fixed-reranker"
    assert result.retrieval_ms >= 2
    assert result.truncated is True


def test_rerank_uses_recall_rank_as_score_tie_break() -> None:
    reranker = FixedReranker(
        [RerankScore(chunk_id=item, score=0.5) for item in ("a", "b", "c")]
    )

    result = rerank_retrieval_result(make_result(), reranker=reranker, top_k=3)

    assert [item.chunk_id for item in result.items] == ["a", "b", "c"]


def test_reranking_retriever_requests_candidate_k() -> None:
    base = FixedRetriever(make_result())
    reranker = FixedReranker(
        [RerankScore(chunk_id=item, score=0.5) for item in ("a", "b", "c")]
    )
    retriever = RerankingRetriever(
        base_retriever=base,
        reranker=reranker,
        config=RerankingRetrieverConfig(candidate_k=10),
    )

    result = retriever.retrieve("  find evidence  ", top_k=2)

    assert base.calls == [("find evidence", 10)]
    assert reranker.calls == [("find evidence", ["a", "b", "c"])]
    assert len(result.items) == 2


def test_empty_result_skips_reranker() -> None:
    empty = make_result().model_copy(update={"items": [], "total_candidates": 0})
    reranker = FixedReranker([])

    result = rerank_retrieval_result(empty, reranker=reranker, top_k=2)

    assert result.items == []
    assert result.top_k == 2
    assert reranker.calls == []


def test_controlled_failure_falls_back_with_observable_metadata() -> None:
    reranker = FixedReranker(
        [],
        error=RerankerError("private provider body", code="provider_timeout"),
    )

    result = rerank_retrieval_result(make_result(), reranker=reranker, top_k=2)

    assert [item.chunk_id for item in result.items] == ["a", "b"]
    assert result.items[0].metadata["rerank_status"] == "fallback"
    assert result.items[0].metadata["rerank_error_code"] == "provider_timeout"
    assert "private" not in str(result.model_dump())


def test_strict_mode_raises_sanitized_reranking_error() -> None:
    reranker = FixedReranker([], error=RerankerError("secret", code="timeout"))

    with pytest.raises(RerankingError) as captured:
        rerank_retrieval_result(
            make_result(),
            reranker=reranker,
            fallback_on_error=False,
        )

    assert str(captured.value) == "reranker 评分失败"
    assert "secret" not in str(captured.value)


@pytest.mark.parametrize(
    "scores",
    [
        [RerankScore(chunk_id="a", score=0.5)],
        [
            RerankScore(chunk_id="a", score=0.5),
            RerankScore(chunk_id="b", score=0.4),
            RerankScore(chunk_id="unknown", score=0.3),
        ],
        [
            RerankScore(chunk_id="a", score=0.5),
            RerankScore(chunk_id="a", score=0.4),
            RerankScore(chunk_id="c", score=0.3),
        ],
        [object(), object(), object()],
    ],
)
def test_invalid_scores_trigger_fallback(scores: object) -> None:
    result = rerank_retrieval_result(
        make_result(),
        reranker=FixedReranker(scores),
    )

    assert result.items[0].metadata["rerank_status"] == "fallback"
    assert result.items[0].metadata["rerank_error_code"] == "invalid_scores"


def test_unexpected_programming_error_is_not_silently_fallback() -> None:
    reranker = FixedReranker([], error=RuntimeError("programming bug"))

    with pytest.raises(RuntimeError, match="programming bug"):
        rerank_retrieval_result(make_result(), reranker=reranker)


@pytest.mark.parametrize(
    ("chunk_id", "score", "error"),
    [
        ("", 0.5, "chunk_id"),
        ("a", True, "数值"),
        ("a", float("nan"), "0 到 1"),
        ("a", 1.1, "0 到 1"),
    ],
)
def test_rerank_score_validates_provider_values(
    chunk_id: str,
    score: object,
    error: str,
) -> None:
    with pytest.raises(RerankerError, match=error):
        RerankScore(chunk_id=chunk_id, score=score)  # type: ignore[arg-type]
