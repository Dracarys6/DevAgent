from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import Protocol

from .models import EvidenceSnippet, RetrievalResult
from .retriever import RetrievalError
from .vector_retriever import VectorRetrievalError


class Retriever(Protocol):
    """返回统一 RetrievalResult 的最小检索协议。"""

    def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalResult: ...


class HybridRetrievalError(ValueError):
    """混合召回输入、候选身份或底层检索不满足契约。"""


@dataclass(frozen=True)
class HybridRetrieverConfig:
    candidate_k: int = 20
    rrf_k: int = 60
    keyword_weight: float = 1.0
    vector_weight: float = 1.0

    def __post_init__(self) -> None:
        _validate_integer(self.candidate_k, name="candidate_k", minimum=1, maximum=50)
        _validate_integer(self.rrf_k, name="rrf_k", minimum=1)
        _validate_weight(self.keyword_weight, name="keyword_weight")
        _validate_weight(self.vector_weight, name="vector_weight")


@dataclass
class _FusedCandidate:
    keyword_item: EvidenceSnippet | None = None
    vector_item: EvidenceSnippet | None = None

    @property
    def evidence(self) -> EvidenceSnippet:
        # * BM25 excerpt 通常围绕命中词截取，比向量结果的固定前缀更适合作为上下文。
        item = self.keyword_item or self.vector_item
        if item is None:  # pragma: no cover - 仅防御内部编程错误。
            raise HybridRetrievalError("融合候选缺少 evidence")
        return item


class HybridRetriever:
    """使用 Reciprocal Rank Fusion 合并关键词和向量候选。"""

    def __init__(
        self,
        *,
        keyword_retriever: Retriever,
        vector_retriever: Retriever,
        config: HybridRetrieverConfig | None = None,
    ) -> None:
        self._keyword_retriever = keyword_retriever
        self._vector_retriever = vector_retriever
        self.config = config or HybridRetrieverConfig()

    def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalResult:
        normalized_query = _validate_query(query)
        _validate_top_k(top_k)
        candidate_k = max(top_k, self.config.candidate_k)
        started = perf_counter()
        try:
            keyword_result = self._keyword_retriever.retrieve(
                normalized_query,
                top_k=candidate_k,
            )
            vector_result = self._vector_retriever.retrieve(
                normalized_query,
                top_k=candidate_k,
            )
        except (RetrievalError, VectorRetrievalError) as exc:
            # ! 不把 query 或 provider 异常正文复制到混合检索错误中。
            raise HybridRetrievalError("底层检索失败") from exc

        result = fuse_retrieval_results(
            keyword_result=keyword_result,
            vector_result=vector_result,
            top_k=top_k,
            config=self.config,
        )
        return result.model_copy(
            update={"retrieval_ms": (perf_counter() - started) * 1000}
        )


def fuse_retrieval_results(
    *,
    keyword_result: RetrievalResult,
    vector_result: RetrievalResult,
    top_k: int = 5,
    config: HybridRetrieverConfig | None = None,
) -> RetrievalResult:
    """融合已生成的两路候选，便于评测复用昂贵的 query embedding。"""
    started = perf_counter()
    resolved_config = config or HybridRetrieverConfig()
    _validate_top_k(top_k)
    query = _validate_source_results(keyword_result, vector_result)
    candidates: dict[str, _FusedCandidate] = {}

    for item in keyword_result.items:
        candidate = candidates.setdefault(item.chunk_id, _FusedCandidate())
        if candidate.keyword_item is not None:
            raise HybridRetrievalError("BM25 结果包含重复 chunk_id")
        candidate.keyword_item = item

    for item in vector_result.items:
        candidate = candidates.setdefault(item.chunk_id, _FusedCandidate())
        if candidate.vector_item is not None:
            raise HybridRetrievalError("Vector 结果包含重复 chunk_id")
        if candidate.keyword_item is not None:
            _validate_evidence_identity(candidate.keyword_item, item)
        candidate.vector_item = item

    scored: list[tuple[float, _FusedCandidate]] = []
    for candidate in candidates.values():
        score = _rrf_score(candidate, resolved_config)
        if not isfinite(score) or score <= 0:
            raise HybridRetrievalError("融合分数无效")
        scored.append((score, candidate))

    ranked = sorted(
        scored,
        key=lambda pair: (
            -pair[0],
            pair[1].evidence.path,
            pair[1].evidence.line_range.start,
            pair[1].evidence.chunk_id,
        ),
    )
    selected = ranked[:top_k]
    items = [
        _build_fused_evidence(candidate, score=score, rank=rank)
        for rank, (score, candidate) in enumerate(selected, start=1)
    ]
    return RetrievalResult(
        query=query,
        top_k=top_k,
        total_candidates=len(ranked),
        items=items,
        retrieval_ms=(
            keyword_result.retrieval_ms
            + vector_result.retrieval_ms
            + (perf_counter() - started) * 1000
        ),
        truncated=(
            len(ranked) > len(selected)
            or keyword_result.truncated
            or vector_result.truncated
        ),
    )


def _rrf_score(
    candidate: _FusedCandidate,
    config: HybridRetrieverConfig,
) -> float:
    score = 0.0
    if candidate.keyword_item is not None:
        score += config.keyword_weight / (config.rrf_k + candidate.keyword_item.rank)
    if candidate.vector_item is not None:
        score += config.vector_weight / (config.rrf_k + candidate.vector_item.rank)
    return score


def _build_fused_evidence(
    candidate: _FusedCandidate,
    *,
    score: float,
    rank: int,
) -> EvidenceSnippet:
    base = candidate.evidence
    sources: list[str] = []
    metadata = dict(base.metadata)
    metadata["retrieval_method"] = "hybrid_rrf"
    metadata["rrf_score"] = repr(score)

    if candidate.keyword_item is not None:
        sources.append("bm25")
        metadata["bm25_rank"] = str(candidate.keyword_item.rank)
        metadata["bm25_score"] = repr(candidate.keyword_item.score)
    if candidate.vector_item is not None:
        sources.append("vector")
        metadata["vector_rank"] = str(candidate.vector_item.rank)
        metadata["vector_score"] = repr(candidate.vector_item.score)
        provider = candidate.vector_item.metadata.get("embedding_provider")
        if provider:
            metadata["embedding_provider"] = provider
        cosine = candidate.vector_item.metadata.get("cosine_similarity")
        if cosine:
            metadata["cosine_similarity"] = cosine
    metadata["candidate_sources"] = ",".join(sources)

    return base.model_copy(
        update={
            "score": score,
            "rank": rank,
            "metadata": metadata,
        }
    )


def _validate_source_results(
    keyword_result: RetrievalResult,
    vector_result: RetrievalResult,
) -> str:
    keyword_query = _validate_query(keyword_result.query)
    vector_query = _validate_query(vector_result.query)
    if keyword_query != vector_query:
        raise HybridRetrievalError("底层检索 query 不一致")
    return keyword_query


def _validate_evidence_identity(
    keyword_item: EvidenceSnippet,
    vector_item: EvidenceSnippet,
) -> None:
    identity = (
        "document_id",
        "source",
        "path",
        "line_range",
    )
    if any(
        getattr(keyword_item, field) != getattr(vector_item, field)
        for field in identity
    ):
        raise HybridRetrievalError("相同 chunk_id 的 evidence 身份冲突")


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise HybridRetrievalError("query 必须是字符串")
    normalized = query.strip()
    if not normalized:
        raise HybridRetrievalError("query 不能为空")
    if len(normalized) > 2_000:
        raise HybridRetrievalError("query 长度不能超过 2000 字符")
    return normalized


def _validate_top_k(top_k: int) -> None:
    try:
        _validate_integer(top_k, name="top_k", minimum=1, maximum=50)
    except (TypeError, ValueError) as exc:
        raise HybridRetrievalError(str(exc)) from exc


def _validate_integer(
    value: int,
    *,
    name: str,
    minimum: int,
    maximum: int | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须是整数")
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise ValueError(f"{name} 必须大于或等于 {minimum}")
        raise ValueError(f"{name} 必须位于 {minimum} 到 {maximum}")


def _validate_weight(value: float, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} 必须是数值")
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} 必须是有限正数")
