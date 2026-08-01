from collections.abc import Sequence
from dataclasses import dataclass
from math import fsum, isfinite
from time import perf_counter

from .embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingVector,
    normalize_embedding_vector,
)
from .models import Chunk, EvidenceSnippet, RetrievalResult


class VectorRetrievalError(ValueError):
    """向量索引或查询不满足检索契约。"""


@dataclass(frozen=True)
class VectorRetrieverConfig:
    max_excerpt_chars: int = 2000
    min_similarity: float = -1.0

    def __post_init__(self) -> None:
        if isinstance(self.max_excerpt_chars, bool) or not isinstance(
            self.max_excerpt_chars, int
        ):
            raise TypeError("max_excerpt_chars 必须是整数")
        if not 1 <= self.max_excerpt_chars <= 2000:
            raise ValueError("max_excerpt_chars 必须位于 1 到 2000")
        if isinstance(self.min_similarity, bool) or not isinstance(
            self.min_similarity, (int, float)
        ):
            raise TypeError("min_similarity 必须是数值")
        if not isfinite(self.min_similarity) or not -1 <= self.min_similarity <= 1:
            raise ValueError("min_similarity 必须是 -1 到 1 之间的有限数值")


@dataclass(frozen=True)
class _VectorIndexEntry:
    chunk: Chunk
    vector: EmbeddingVector


@dataclass(frozen=True)
class _ScoredVector:
    chunk: Chunk
    similarity: float


class VectorRetriever:
    """使用注入的 EmbeddingProvider 构建内存向量索引并返回统一证据。"""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        *,
        embedding_provider: EmbeddingProvider,
        config: VectorRetrieverConfig | None = None,
    ) -> None:
        self.config = config or VectorRetrieverConfig()
        self._embedding_provider = embedding_provider
        self._provider_name = _validate_provider_name(embedding_provider.provider_name)
        chunk_snapshot = tuple(chunks)
        chunk_ids = [chunk.chunk_id for chunk in chunk_snapshot]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise VectorRetrievalError("chunk_id 必须唯一")

        self._dimensions: int | None = None
        self._index: tuple[_VectorIndexEntry, ...] = ()
        if not chunk_snapshot:
            return

        try:
            raw_vectors = embedding_provider.embed_documents(
                [chunk.content for chunk in chunk_snapshot]
            )
        except EmbeddingProviderError as exc:
            raise VectorRetrievalError("文档 embedding 生成失败") from exc
        if len(raw_vectors) != len(chunk_snapshot):
            raise VectorRetrievalError("文档 embedding 数量与 chunk 数量不一致")

        normalized_vectors: list[EmbeddingVector] = []
        for raw_vector in raw_vectors:
            try:
                vector = normalize_embedding_vector(
                    raw_vector,
                    expected_dimensions=self._dimensions,
                )
            except EmbeddingProviderError as exc:
                raise VectorRetrievalError("文档 embedding 格式无效") from exc
            if self._dimensions is None:
                self._dimensions = len(vector)
            normalized_vectors.append(vector)

        self._index = tuple(
            _VectorIndexEntry(chunk=chunk, vector=vector)
            for chunk, vector in zip(
                chunk_snapshot,
                normalized_vectors,
                strict=True,
            )
        )

    def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalResult:
        """按 cosine similarity 返回带原始定位信息的 Top-K evidence。"""
        started_at = perf_counter()
        normalized_query = _validate_query(query)
        _validate_top_k(top_k)
        if not self._index:
            return RetrievalResult(
                query=normalized_query,
                top_k=top_k,
                total_candidates=0,
                items=[],
                retrieval_ms=(perf_counter() - started_at) * 1000,
            )

        try:
            query_vector = normalize_embedding_vector(
                self._embedding_provider.embed_query(normalized_query),
                expected_dimensions=self._dimensions,
            )
        except EmbeddingProviderError as exc:
            raise VectorRetrievalError("查询 embedding 生成失败") from exc

        candidates = self._rank_candidates(query_vector)
        selected = candidates[:top_k]
        excerpt_was_truncated = False
        items: list[EvidenceSnippet] = []

        for rank, candidate in enumerate(selected, start=1):
            chunk = candidate.chunk
            excerpt = chunk.content[: self.config.max_excerpt_chars]
            excerpt_was_truncated |= len(excerpt) < len(chunk.content)
            normalized_score = (candidate.similarity + 1) / 2
            items.append(
                EvidenceSnippet(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    source=chunk.source,
                    path=chunk.path,
                    line_range=chunk.line_range,
                    excerpt=excerpt,
                    score=normalized_score,
                    rank=rank,
                    metadata={
                        **chunk.metadata,
                        "retrieval_method": "vector",
                        "embedding_provider": self._provider_name,
                        "cosine_similarity": repr(candidate.similarity),
                        "excerpt_start_char": "0",
                        "excerpt_end_char": str(len(excerpt)),
                    },
                )
            )

        return RetrievalResult(
            query=normalized_query,
            top_k=top_k,
            total_candidates=len(candidates),
            items=items,
            retrieval_ms=(perf_counter() - started_at) * 1000,
            truncated=len(candidates) > len(selected) or excerpt_was_truncated,
        )

    def _rank_candidates(
        self,
        query_vector: EmbeddingVector,
    ) -> list[_ScoredVector]:
        candidates: list[_ScoredVector] = []
        for entry in self._index:
            similarity = _cosine_similarity(query_vector, entry.vector)
            if similarity >= self.config.min_similarity:
                candidates.append(
                    _ScoredVector(chunk=entry.chunk, similarity=similarity)
                )
        return sorted(
            candidates,
            key=lambda item: (
                -item.similarity,
                item.chunk.path,
                item.chunk.line_range.start,
                item.chunk.chunk_id,
            ),
        )


def _cosine_similarity(
    left: EmbeddingVector,
    right: EmbeddingVector,
) -> float:
    similarity = fsum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )
    return max(-1.0, min(1.0, similarity))


def _validate_provider_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorRetrievalError("embedding provider_name 不能为空")
    if value != value.strip() or len(value) > 100:
        raise VectorRetrievalError("embedding provider_name 格式无效")
    return value


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise VectorRetrievalError("query 必须是字符串")
    normalized_query = query.strip()
    if not normalized_query:
        raise VectorRetrievalError("query 不能为空")
    if len(normalized_query) > 2000:
        raise VectorRetrievalError("query 长度不能超过 2000 字符")
    return normalized_query


def _validate_top_k(top_k: int) -> None:
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise VectorRetrievalError("top_k 必须是整数")
    if not 1 <= top_k <= 50:
        raise VectorRetrievalError("top_k 必须位于 1 到 50")
