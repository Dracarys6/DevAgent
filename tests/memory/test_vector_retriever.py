from collections.abc import Sequence

import pytest

from devagent.memory import (
    Chunk,
    ChunkType,
    EmbeddingProviderError,
    EmbeddingVector,
    LineRange,
    VectorRetrievalError,
    VectorRetriever,
    VectorRetrieverConfig,
)


class FixedEmbeddingProvider:
    provider_name = "fixed-test"

    def __init__(
        self,
        *,
        document_vectors: dict[str, EmbeddingVector],
        query_vectors: dict[str, EmbeddingVector] | None = None,
        document_output: list[EmbeddingVector] | None = None,
        fail_documents: bool = False,
        fail_query: bool = False,
    ) -> None:
        self.document_vectors = document_vectors
        self.query_vectors = query_vectors or {}
        self.document_output = document_output
        self.fail_documents = fail_documents
        self.fail_query = fail_query
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        self.document_calls.append(list(texts))
        if self.fail_documents:
            raise EmbeddingProviderError("secret provider response")
        if self.document_output is not None:
            return self.document_output
        return [self.document_vectors[text] for text in texts]

    def embed_query(self, text: str) -> EmbeddingVector:
        self.query_calls.append(text)
        if self.fail_query:
            raise EmbeddingProviderError("secret provider response")
        return self.query_vectors[text]


def make_chunk(
    *,
    chunk_id: str,
    path: str,
    content: str,
    line: int = 1,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source="workspace",
        path=path,
        line_range=LineRange(start=line, end=line),
        chunk_type=ChunkType.CODE,
        content=content,
        metadata={"fixture": "vector"},
    )


def make_ranking_fixture() -> tuple[list[Chunk], FixedEmbeddingProvider]:
    chunks = [
        make_chunk(chunk_id="c", path="src/c.py", content="gamma"),
        make_chunk(chunk_id="a", path="src/a.py", content="alpha"),
        make_chunk(chunk_id="b", path="src/b.py", content="beta"),
    ]
    provider = FixedEmbeddingProvider(
        document_vectors={
            "alpha": (1.0, 0.0),
            "beta": (1.0, 1.0),
            "gamma": (0.0, 1.0),
        },
        query_vectors={"find alpha": (1.0, 0.0)},
    )
    return chunks, provider


def test_vector_retriever_ranks_cosine_and_preserves_evidence_metadata() -> None:
    chunks, provider = make_ranking_fixture()
    retriever = VectorRetriever(chunks, embedding_provider=provider)

    result = retriever.retrieve("find alpha", top_k=3)

    assert [item.path for item in result.items] == [
        "src/a.py",
        "src/b.py",
        "src/c.py",
    ]
    assert [item.rank for item in result.items] == [1, 2, 3]
    assert [item.score for item in result.items] == pytest.approx(
        [1, (2**-0.5 + 1) / 2, 0.5]
    )
    assert result.total_candidates == 3
    assert result.truncated is False
    assert provider.document_calls == [["gamma", "alpha", "beta"]]
    assert provider.query_calls == ["find alpha"]

    first = result.items[0]
    assert first.chunk_id == "a"
    assert first.document_id == "doc-a"
    assert first.source == "workspace"
    assert first.line_range == LineRange(start=1, end=1)
    assert first.excerpt == "alpha"
    assert first.metadata["fixture"] == "vector"
    assert first.metadata["retrieval_method"] == "vector"
    assert first.metadata["embedding_provider"] == "fixed-test"
    assert float(first.metadata["cosine_similarity"]) == pytest.approx(1)


def test_vector_retriever_uses_stable_tie_break_and_repeatable_results() -> None:
    chunks = [
        make_chunk(chunk_id="z", path="src/b.py", content="beta", line=2),
        make_chunk(chunk_id="a", path="src/a.py", content="alpha", line=3),
        make_chunk(chunk_id="b", path="src/a.py", content="alpha-2", line=2),
    ]
    provider = FixedEmbeddingProvider(
        document_vectors={
            "alpha": (0.0, 1.0),
            "alpha-2": (0.0, 1.0),
            "beta": (0.0, 1.0),
        },
        query_vectors={"query": (1.0, 0.0)},
    )
    retriever = VectorRetriever(chunks, embedding_provider=provider)

    first = retriever.retrieve("query", top_k=3)
    second = retriever.retrieve("query", top_k=3)

    expected = ["b", "a", "z"]
    assert [item.chunk_id for item in first.items] == expected
    assert [item.chunk_id for item in second.items] == expected


def test_vector_retriever_applies_top_k_threshold_and_excerpt_limit() -> None:
    chunks, provider = make_ranking_fixture()
    retriever = VectorRetriever(
        chunks,
        embedding_provider=provider,
        config=VectorRetrieverConfig(
            max_excerpt_chars=3,
            min_similarity=0.5,
        ),
    )

    result = retriever.retrieve("find alpha", top_k=1)

    assert result.total_candidates == 2
    assert len(result.items) == 1
    assert result.items[0].excerpt == "alp"
    assert result.truncated is True


def test_empty_corpus_returns_empty_without_provider_calls() -> None:
    provider = FixedEmbeddingProvider(document_vectors={})
    retriever = VectorRetriever([], embedding_provider=provider)

    result = retriever.retrieve("unknown", top_k=5)

    assert result.items == []
    assert result.total_candidates == 0
    assert provider.document_calls == []
    assert provider.query_calls == []


def test_vector_retriever_rejects_duplicate_chunk_ids() -> None:
    chunks = [
        make_chunk(chunk_id="same", path="src/a.py", content="alpha"),
        make_chunk(chunk_id="same", path="src/b.py", content="beta"),
    ]
    provider = FixedEmbeddingProvider(document_vectors={})

    with pytest.raises(VectorRetrievalError, match="chunk_id"):
        VectorRetriever(chunks, embedding_provider=provider)

    assert provider.document_calls == []


@pytest.mark.parametrize("provider_name", ["", "  ", " padded ", "x" * 101])
def test_vector_retriever_rejects_invalid_provider_name(
    provider_name: str,
) -> None:
    provider = FixedEmbeddingProvider(document_vectors={})
    provider.provider_name = provider_name

    with pytest.raises(VectorRetrievalError, match="provider_name"):
        VectorRetriever([], embedding_provider=provider)


def test_vector_retriever_rejects_document_vector_count_mismatch() -> None:
    chunk = make_chunk(chunk_id="a", path="src/a.py", content="alpha")
    provider = FixedEmbeddingProvider(document_vectors={}, document_output=[])

    with pytest.raises(VectorRetrievalError, match="数量"):
        VectorRetriever([chunk], embedding_provider=provider)


def test_vector_retriever_rejects_document_dimension_mismatch() -> None:
    chunks = [
        make_chunk(chunk_id="a", path="src/a.py", content="alpha"),
        make_chunk(chunk_id="b", path="src/b.py", content="beta"),
    ]
    provider = FixedEmbeddingProvider(
        document_vectors={"alpha": (1.0, 0.0), "beta": (1.0, 0.0, 0.0)}
    )

    with pytest.raises(VectorRetrievalError, match="格式无效"):
        VectorRetriever(chunks, embedding_provider=provider)


def test_vector_retriever_rejects_query_dimension_mismatch() -> None:
    chunk = make_chunk(chunk_id="a", path="src/a.py", content="alpha")
    provider = FixedEmbeddingProvider(
        document_vectors={"alpha": (1.0, 0.0)},
        query_vectors={"query": (1.0, 0.0, 0.0)},
    )
    retriever = VectorRetriever([chunk], embedding_provider=provider)

    with pytest.raises(VectorRetrievalError, match="查询 embedding"):
        retriever.retrieve("query")


def test_vector_retriever_converts_controlled_provider_failures() -> None:
    chunk = make_chunk(chunk_id="a", path="src/a.py", content="alpha")
    document_failure = FixedEmbeddingProvider(
        document_vectors={},
        fail_documents=True,
    )

    with pytest.raises(VectorRetrievalError, match="文档 embedding") as exc_info:
        VectorRetriever([chunk], embedding_provider=document_failure)
    assert "secret provider response" not in str(exc_info.value)

    query_failure = FixedEmbeddingProvider(
        document_vectors={"alpha": (1.0, 0.0)},
        fail_query=True,
    )
    retriever = VectorRetriever([chunk], embedding_provider=query_failure)
    with pytest.raises(VectorRetrievalError, match="查询 embedding") as exc_info:
        retriever.retrieve("query")
    assert "secret provider response" not in str(exc_info.value)


@pytest.mark.parametrize("query", ["", "   ", "x" * 2001])
def test_vector_retriever_rejects_invalid_query(query: str) -> None:
    provider = FixedEmbeddingProvider(document_vectors={})
    retriever = VectorRetriever([], embedding_provider=provider)

    with pytest.raises(VectorRetrievalError, match="query"):
        retriever.retrieve(query)


@pytest.mark.parametrize("top_k", [0, 51, True, 1.5])
def test_vector_retriever_rejects_invalid_top_k(top_k: object) -> None:
    provider = FixedEmbeddingProvider(document_vectors={})
    retriever = VectorRetriever([], embedding_provider=provider)

    with pytest.raises(VectorRetrievalError, match="top_k"):
        retriever.retrieve("query", top_k=top_k)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "config",
    [
        {"max_excerpt_chars": 0},
        {"max_excerpt_chars": 2001},
        {"max_excerpt_chars": True},
        {"min_similarity": -1.1},
        {"min_similarity": 1.1},
        {"min_similarity": float("nan")},
        {"min_similarity": True},
    ],
)
def test_vector_retriever_config_rejects_invalid_values(
    config: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        VectorRetrieverConfig(**config)  # type: ignore[arg-type]
