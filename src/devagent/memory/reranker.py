from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import Protocol

from .hybrid_retriever import HybridRetrievalError, Retriever
from .models import EvidenceSnippet, RetrievalResult
from .retriever import RetrievalError
from .vector_retriever import VectorRetrievalError


class RerankerError(RuntimeError):
    """Reranker provider 无法返回可信评分。"""

    def __init__(self, message: str, *, code: str = "reranker_error") -> None:
        super().__init__(message)
        self.code = code


class RerankingError(ValueError):
    """RerankingRetriever 请求或严格重排失败。"""


@dataclass(frozen=True)
class RerankScore:
    chunk_id: str
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.chunk_id, str) or not self.chunk_id.strip():
            raise RerankerError("rerank chunk_id 不能为空", code="invalid_score")
        if self.chunk_id != self.chunk_id.strip() or len(self.chunk_id) > 128:
            raise RerankerError("rerank chunk_id 格式无效", code="invalid_score")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise RerankerError("rerank score 必须是数值", code="invalid_score")
        if not isfinite(self.score) or not 0 <= self.score <= 1:
            raise RerankerError("rerank score 必须位于 0 到 1", code="invalid_score")


class Reranker(Protocol):
    @property
    def reranker_name(self) -> str: ...

    def score(
        self,
        query: str,
        candidates: Sequence[EvidenceSnippet],
    ) -> list[RerankScore]: ...


@dataclass(frozen=True)
class RerankingRetrieverConfig:
    candidate_k: int = 10
    fallback_on_error: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.candidate_k, bool) or not isinstance(self.candidate_k, int):
            raise TypeError("candidate_k 必须是整数")
        if not 1 <= self.candidate_k <= 50:
            raise ValueError("candidate_k 必须位于 1 到 50")
        if not isinstance(self.fallback_on_error, bool):
            raise TypeError("fallback_on_error 必须是布尔值")


class RerankingRetriever:
    """用可替换 Reranker 重排基础检索器的 Top-N 候选。"""

    def __init__(
        self,
        *,
        base_retriever: Retriever,
        reranker: Reranker,
        config: RerankingRetrieverConfig | None = None,
    ) -> None:
        self._base_retriever = base_retriever
        self._reranker = reranker
        self.config = config or RerankingRetrieverConfig()
        _validate_reranker_name(reranker.reranker_name)

    def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalResult:
        normalized = _validate_query(query)
        _validate_top_k(top_k)
        started = perf_counter()
        try:
            base_result = self._base_retriever.retrieve(
                normalized,
                top_k=max(top_k, self.config.candidate_k),
            )
        except (RetrievalError, VectorRetrievalError, HybridRetrievalError) as exc:
            raise RerankingError("基础检索失败") from exc

        result = rerank_retrieval_result(
            base_result,
            reranker=self._reranker,
            top_k=top_k,
            fallback_on_error=self.config.fallback_on_error,
        )
        return result.model_copy(
            update={"retrieval_ms": (perf_counter() - started) * 1000}
        )


def rerank_retrieval_result(
    result: RetrievalResult,
    *,
    reranker: Reranker,
    top_k: int = 5,
    fallback_on_error: bool = True,
) -> RetrievalResult:
    """重排已有候选；受控失败时可保留召回顺序。"""
    _validate_top_k(top_k)
    if not isinstance(fallback_on_error, bool):
        raise TypeError("fallback_on_error 必须是布尔值")
    reranker_name = _validate_reranker_name(reranker.reranker_name)
    if not result.items:
        return result.model_copy(update={"top_k": top_k, "items": []})

    started = perf_counter()
    try:
        scores = reranker.score(result.query, result.items)
        score_by_id = _validate_scores(scores, candidates=result.items)
    except RerankerError as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        if not fallback_on_error:
            raise RerankingError("reranker 评分失败") from exc
        return _build_fallback_result(
            result,
            top_k=top_k,
            reranker_name=reranker_name,
            error_code=exc.code,
            rerank_ms=elapsed_ms,
        )

    elapsed_ms = (perf_counter() - started) * 1000
    ranked = sorted(
        result.items,
        key=lambda item: (
            -score_by_id[item.chunk_id],
            item.rank,
            item.path,
            item.line_range.start,
            item.chunk_id,
        ),
    )
    selected = ranked[:top_k]
    items = [
        _build_success_evidence(
            item,
            rank=rank,
            rerank_score=score_by_id[item.chunk_id],
            reranker_name=reranker_name,
            rerank_ms=elapsed_ms,
        )
        for rank, item in enumerate(selected, start=1)
    ]
    return RetrievalResult(
        query=result.query,
        top_k=top_k,
        total_candidates=result.total_candidates,
        items=items,
        retrieval_ms=result.retrieval_ms + elapsed_ms,
        truncated=result.truncated or result.total_candidates > len(items),
    )


def _validate_scores(
    scores: object,
    *,
    candidates: Sequence[EvidenceSnippet],
) -> dict[str, float]:
    if isinstance(scores, (str, bytes)) or not isinstance(scores, Sequence):
        raise RerankerError("reranker scores 格式无效", code="invalid_scores")
    if len(scores) != len(candidates):
        raise RerankerError("reranker score 数量不匹配", code="invalid_scores")
    score_by_id: dict[str, float] = {}
    for score in scores:
        if not isinstance(score, RerankScore):
            raise RerankerError("reranker score 类型无效", code="invalid_scores")
        if score.chunk_id in score_by_id:
            raise RerankerError("reranker chunk_id 重复", code="invalid_scores")
        score_by_id[score.chunk_id] = float(score.score)
    expected_ids = {item.chunk_id for item in candidates}
    if set(score_by_id) != expected_ids:
        raise RerankerError("reranker chunk_id 集合不匹配", code="invalid_scores")
    return score_by_id


def _build_success_evidence(
    item: EvidenceSnippet,
    *,
    rank: int,
    rerank_score: float,
    reranker_name: str,
    rerank_ms: float,
) -> EvidenceSnippet:
    metadata = {
        **item.metadata,
        "retrieval_method": f"{item.metadata.get('retrieval_method', 'retrieval')}_rerank",
        "reranker": reranker_name,
        "recall_rank": str(item.rank),
        "recall_score": repr(item.score),
        "rerank_score": repr(rerank_score),
        "rerank_status": "success",
        "rerank_ms": repr(rerank_ms),
    }
    return item.model_copy(
        update={"score": rerank_score, "rank": rank, "metadata": metadata}
    )


def _build_fallback_result(
    result: RetrievalResult,
    *,
    top_k: int,
    reranker_name: str,
    error_code: str,
    rerank_ms: float,
) -> RetrievalResult:
    selected = result.items[:top_k]
    items = []
    for rank, item in enumerate(selected, start=1):
        metadata = {
            **item.metadata,
            "reranker": reranker_name,
            "rerank_status": "fallback",
            "rerank_error_code": error_code,
            "rerank_ms": repr(rerank_ms),
        }
        items.append(item.model_copy(update={"rank": rank, "metadata": metadata}))
    return RetrievalResult(
        query=result.query,
        top_k=top_k,
        total_candidates=result.total_candidates,
        items=items,
        retrieval_ms=result.retrieval_ms + rerank_ms,
        truncated=result.truncated or result.total_candidates > len(items),
    )


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise RerankingError("query 必须是字符串")
    normalized = query.strip()
    if not normalized:
        raise RerankingError("query 不能为空")
    if len(normalized) > 2_000:
        raise RerankingError("query 长度不能超过 2000 字符")
    return normalized


def _validate_top_k(top_k: int) -> None:
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise RerankingError("top_k 必须是整数")
    if not 1 <= top_k <= 50:
        raise RerankingError("top_k 必须位于 1 到 50")


def _validate_reranker_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RerankingError("reranker_name 不能为空")
    if value != value.strip() or len(value) > 200:
        raise RerankingError("reranker_name 格式无效")
    return value
