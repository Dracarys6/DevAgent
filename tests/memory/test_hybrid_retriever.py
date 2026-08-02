from dataclasses import fields

import pytest

from devagent.memory import (
    EvidenceSnippet,
    HybridRetrievalError,
    HybridRetriever,
    HybridRetrieverConfig,
    LineRange,
    RetrievalError,
    RetrievalResult,
    fuse_retrieval_results,
)


class FixedRetriever:
    def __init__(
        self,
        result: RetrievalResult | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalResult:
        self.calls.append((query, top_k))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def make_item(
    chunk_id: str,
    *,
    path: str,
    rank: int,
    score: float,
    excerpt: str,
    method: str,
    document_id: str | None = None,
) -> EvidenceSnippet:
    metadata = {"retrieval_method": method}
    if method == "vector":
        metadata.update(
            {
                "embedding_provider": "fixed-embedding",
                "cosine_similarity": repr(score * 2 - 1),
            }
        )
    return EvidenceSnippet(
        chunk_id=chunk_id,
        document_id=document_id or f"doc-{chunk_id}",
        source="workspace",
        path=path,
        line_range=LineRange(start=1, end=1),
        excerpt=excerpt,
        score=score,
        rank=rank,
        metadata=metadata,
    )


def make_result(
    items: list[EvidenceSnippet],
    *,
    query: str = "find evidence",
    top_k: int = 20,
    total_candidates: int | None = None,
    truncated: bool = False,
) -> RetrievalResult:
    return RetrievalResult(
        query=query,
        top_k=top_k,
        total_candidates=(len(items) if total_candidates is None else total_candidates),
        items=items,
        retrieval_ms=2.5,
        truncated=truncated,
    )


def make_fusion_results() -> tuple[RetrievalResult, RetrievalResult]:
    keyword = make_result(
        [
            make_item(
                "a",
                path="src/a.py",
                rank=1,
                score=8.0,
                excerpt="bm25-a",
                method="bm25",
            ),
            make_item(
                "b",
                path="src/b.py",
                rank=2,
                score=7.0,
                excerpt="bm25-b",
                method="bm25",
            ),
        ]
    )
    vector = make_result(
        [
            make_item(
                "b",
                path="src/b.py",
                rank=1,
                score=0.95,
                excerpt="vector-b",
                method="vector",
            ),
            make_item(
                "c",
                path="src/c.py",
                rank=2,
                score=0.90,
                excerpt="vector-c",
                method="vector",
            ),
            make_item(
                "a",
                path="src/a.py",
                rank=3,
                score=0.85,
                excerpt="vector-a",
                method="vector",
            ),
        ]
    )
    return keyword, vector


def test_rrf_fuses_ranks_deduplicates_and_preserves_source_metadata() -> None:
    keyword, vector = make_fusion_results()

    result = fuse_retrieval_results(
        keyword_result=keyword,
        vector_result=vector,
        top_k=3,
    )

    assert [item.chunk_id for item in result.items] == ["b", "a", "c"]
    assert result.total_candidates == 3
    assert result.retrieval_ms >= 5.0
    assert result.truncated is False

    first = result.items[0]
    assert first.excerpt == "bm25-b"
    assert first.score == pytest.approx(1 / 62 + 1 / 61)
    assert first.metadata["retrieval_method"] == "hybrid_rrf"
    assert first.metadata["candidate_sources"] == "bm25,vector"
    assert first.metadata["bm25_rank"] == "2"
    assert first.metadata["vector_rank"] == "1"
    assert first.metadata["bm25_score"] == repr(7.0)
    assert first.metadata["vector_score"] == repr(0.95)
    assert first.metadata["embedding_provider"] == "fixed-embedding"

    vector_only = result.items[2]
    assert vector_only.metadata["candidate_sources"] == "vector"
    assert "bm25_rank" not in vector_only.metadata


def test_rrf_applies_weights() -> None:
    keyword, vector = make_fusion_results()
    config = HybridRetrieverConfig(keyword_weight=2, vector_weight=0.5)

    result = fuse_retrieval_results(
        keyword_result=keyword,
        vector_result=vector,
        top_k=3,
        config=config,
    )

    assert [item.chunk_id for item in result.items] == ["a", "b", "c"]
    assert result.items[0].score == pytest.approx(2 / 61 + 0.5 / 63)


def test_hybrid_retriever_requests_candidate_pool_once_per_source() -> None:
    keyword_result, vector_result = make_fusion_results()
    keyword = FixedRetriever(keyword_result)
    vector = FixedRetriever(vector_result)
    retriever = HybridRetriever(
        keyword_retriever=keyword,
        vector_retriever=vector,
        config=HybridRetrieverConfig(candidate_k=20),
    )

    result = retriever.retrieve("  find evidence  ", top_k=2)

    assert keyword.calls == [("find evidence", 20)]
    assert vector.calls == [("find evidence", 20)]
    assert len(result.items) == 2
    assert result.query == "find evidence"
    assert result.retrieval_ms >= 0


def test_hybrid_retriever_expands_candidate_k_for_larger_top_k() -> None:
    empty = make_result([], top_k=20)
    keyword = FixedRetriever(empty)
    vector = FixedRetriever(empty)
    retriever = HybridRetriever(
        keyword_retriever=keyword,
        vector_retriever=vector,
        config=HybridRetrieverConfig(candidate_k=2),
    )

    result = retriever.retrieve("query", top_k=5)

    assert keyword.calls == [("query", 5)]
    assert vector.calls == [("query", 5)]
    assert result.items == []


def test_rrf_uses_stable_tie_break_for_single_source_candidates() -> None:
    keyword = make_result(
        [
            make_item(
                "b",
                path="src/b.py",
                rank=1,
                score=2,
                excerpt="b",
                method="bm25",
            )
        ]
    )
    vector = make_result(
        [
            make_item(
                "a",
                path="src/a.py",
                rank=1,
                score=0.9,
                excerpt="a",
                method="vector",
            )
        ]
    )

    first = fuse_retrieval_results(
        keyword_result=keyword,
        vector_result=vector,
        top_k=2,
    )
    second = fuse_retrieval_results(
        keyword_result=keyword,
        vector_result=vector,
        top_k=2,
    )

    assert [item.chunk_id for item in first.items] == ["a", "b"]
    assert [item.chunk_id for item in second.items] == ["a", "b"]


def test_rrf_propagates_source_truncation_and_final_limit() -> None:
    keyword, vector = make_fusion_results()
    keyword = keyword.model_copy(update={"truncated": True})

    result = fuse_retrieval_results(
        keyword_result=keyword,
        vector_result=vector,
        top_k=1,
    )

    assert len(result.items) == 1
    assert result.total_candidates == 3
    assert result.truncated is True


def test_rrf_rejects_source_query_mismatch() -> None:
    keyword, vector = make_fusion_results()
    vector = vector.model_copy(update={"query": "different query"})

    with pytest.raises(HybridRetrievalError, match="query 不一致"):
        fuse_retrieval_results(
            keyword_result=keyword,
            vector_result=vector,
        )


def test_rrf_rejects_conflicting_identity_for_same_chunk() -> None:
    keyword, vector = make_fusion_results()
    conflicting = vector.items[2].model_copy(update={"document_id": "other-doc"})
    vector = vector.model_copy(
        update={"items": [vector.items[0], vector.items[1], conflicting]}
    )

    with pytest.raises(HybridRetrievalError, match="身份冲突"):
        fuse_retrieval_results(
            keyword_result=keyword,
            vector_result=vector,
        )


def test_hybrid_retriever_sanitizes_controlled_source_failure() -> None:
    keyword = FixedRetriever(error=RetrievalError("private query and source"))
    vector = FixedRetriever(make_result([]))
    retriever = HybridRetriever(
        keyword_retriever=keyword,
        vector_retriever=vector,
    )

    with pytest.raises(HybridRetrievalError) as captured:
        retriever.retrieve("private query")

    assert str(captured.value) == "底层检索失败"
    assert "private" not in str(captured.value)
    assert vector.calls == []


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("candidate_k", True, "整数"),
        ("candidate_k", 0, "1 到 50"),
        ("candidate_k", 51, "1 到 50"),
        ("rrf_k", 0, "大于或等于 1"),
        ("keyword_weight", True, "数值"),
        ("keyword_weight", 0, "有限正数"),
        ("vector_weight", float("inf"), "有限正数"),
    ],
)
def test_hybrid_config_rejects_invalid_values(
    field: str,
    value: object,
    error: str,
) -> None:
    config = {item.name: item.default for item in fields(HybridRetrieverConfig)}
    config[field] = value

    with pytest.raises((TypeError, ValueError), match=error):
        HybridRetrieverConfig(**config)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("query", "top_k", "error"),
    [
        ("", 5, "不能为空"),
        (123, 5, "字符串"),
        ("query", True, "整数"),
        ("query", 0, "1 到 50"),
        ("query", 51, "1 到 50"),
    ],
)
def test_hybrid_retriever_validates_request_before_sources(
    query: object,
    top_k: object,
    error: str,
) -> None:
    empty = make_result([])
    keyword = FixedRetriever(empty)
    vector = FixedRetriever(empty)
    retriever = HybridRetriever(
        keyword_retriever=keyword,
        vector_retriever=vector,
    )

    with pytest.raises((TypeError, HybridRetrievalError), match=error):
        retriever.retrieve(query, top_k=top_k)  # type: ignore[arg-type]

    assert keyword.calls == []
    assert vector.calls == []
