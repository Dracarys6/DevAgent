from pathlib import Path
from time import perf_counter
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.memory import (
    HybridRetrievalError,
    HybridRetriever,
    HybridRetrieverConfig,
    KeywordRetriever,
    Reranker,
    RetrievalResult,
    VectorRetrievalError,
    VectorRetriever,
    VectorRetrieverConfig,
    chunk_document,
    rerank_retrieval_result,
)
from devagent.tools.knowledge_tools import load_workspace_documents

from .rag_report import RAGContextMetrics, evaluate_rag_context
from .runner import (
    RAGEvalCase,
    RAGEvalMetrics,
    RAGEvalPrediction,
    RAGEvalRun,
    evaluate_rag_predictions,
)
from .vector_baseline import MeasuredEmbeddingProvider


class MeasuredReranker(Reranker, Protocol):
    @property
    def request_count(self) -> int: ...

    @property
    def repair_count(self) -> int: ...

    @property
    def scored_candidate_count(self) -> int: ...

    @property
    def input_char_count(self) -> int: ...

    @property
    def output_char_count(self) -> int: ...

    @property
    def timeout_seconds(self) -> float | None: ...

    @property
    def transport_max_retries(self) -> int | None: ...


class RerankBaselineError(RuntimeError):
    """Rerank baseline 无法形成可信的前后对照。"""


class RerankCaseObservation(BaseModel):
    """单个 case 的脱敏排名与运行状态。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    case_id: str = Field(min_length=1, max_length=100)
    before_relevant_rank: int | None = Field(default=None, ge=1)
    after_relevant_rank: int | None = Field(default=None, ge=1)
    rerank_status: Literal["success", "fallback", "skipped", "retrieval_failed"]
    rerank_error_code: str | None = Field(default=None, min_length=1, max_length=100)
    model_attempt_count: int = Field(ge=0)
    rerank_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_error_code(self) -> "RerankCaseObservation":
        if self.rerank_status == "fallback" and self.rerank_error_code is None:
            raise ValueError("fallback observation 必须包含 rerank_error_code")
        if self.rerank_status != "fallback" and self.rerank_error_code is not None:
            raise ValueError("非 fallback observation 不能包含 rerank_error_code")
        return self


class RerankBaselineRun(BaseModel):
    """含检索正文的进程内重排评测结果。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    embedding_provider_name: str = Field(min_length=1, max_length=300)
    embedding_model: str = Field(min_length=1, max_length=200)
    reranker_name: str = Field(min_length=1, max_length=300)
    vector_dimensions: int = Field(ge=1)
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    query_count: int = Field(ge=1)
    candidate_k: int = Field(ge=1, le=50)
    document_embedding_call_count: int = Field(ge=1)
    query_embedding_call_count: int = Field(ge=1)
    embedding_input_tokens: int = Field(ge=0)
    reranker_request_count: int = Field(ge=0)
    reranker_repair_count: int = Field(ge=0)
    reranker_scored_candidate_count: int = Field(ge=0)
    reranker_input_char_count: int = Field(ge=0)
    reranker_output_char_count: int = Field(ge=0)
    reranker_timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    reranker_transport_max_retries: int | None = Field(default=None, ge=0, le=10)
    fallback_count: int = Field(ge=0)
    metadata_completeness: float = Field(ge=0, le=1)
    index_build_ms: float = Field(ge=0)
    observations: list[RerankCaseObservation] = Field(min_length=1)
    before_run: RAGEvalRun
    before_context: RAGContextMetrics
    after_run: RAGEvalRun
    after_context: RAGContextMetrics

    @model_validator(mode="after")
    def validate_counts(self) -> "RerankBaselineRun":
        if len(self.observations) != self.query_count:
            raise ValueError("observations 数量必须等于 query_count")
        if self.before_run.metrics.case_count != self.query_count:
            raise ValueError("before case 数量必须等于 query_count")
        if self.after_run.metrics.case_count != self.query_count:
            raise ValueError("after case 数量必须等于 query_count")
        if self.fallback_count != sum(
            item.rerank_status == "fallback" for item in self.observations
        ):
            raise ValueError("fallback_count 与 observations 不一致")
        return self


class RerankBaselineSummary(BaseModel):
    """不包含 query、excerpt 或 provider response 的持久化摘要。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    embedding_provider_name: str = Field(min_length=1, max_length=300)
    embedding_model: str = Field(min_length=1, max_length=200)
    reranker_name: str = Field(min_length=1, max_length=300)
    case_ids: list[str] = Field(min_length=1)
    vector_dimensions: int = Field(ge=1)
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    candidate_k: int = Field(ge=1, le=50)
    document_embedding_call_count: int = Field(ge=1)
    query_embedding_call_count: int = Field(ge=1)
    embedding_input_tokens: int = Field(ge=0)
    reranker_request_count: int = Field(ge=0)
    reranker_repair_count: int = Field(ge=0)
    reranker_scored_candidate_count: int = Field(ge=0)
    reranker_input_char_count: int = Field(ge=0)
    reranker_output_char_count: int = Field(ge=0)
    reranker_timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    reranker_transport_max_retries: int | None = Field(default=None, ge=0, le=10)
    fallback_count: int = Field(ge=0)
    metadata_completeness: float = Field(ge=0, le=1)
    index_build_ms: float = Field(ge=0)
    observations: list[RerankCaseObservation] = Field(min_length=1)
    before_metrics: RAGEvalMetrics
    before_context: RAGContextMetrics
    after_metrics: RAGEvalMetrics
    after_context: RAGContextMetrics


def run_rerank_baseline(
    cases: list[RAGEvalCase],
    *,
    workspace: str | Path,
    embedding_provider: MeasuredEmbeddingProvider,
    reranker: MeasuredReranker,
    candidate_k: int = 10,
    hybrid_config: HybridRetrieverConfig | None = None,
    vector_config: VectorRetrieverConfig | None = None,
) -> RerankBaselineRun:
    """复用 Hybrid Top-N 候选，对照 LLM 重排前后的检索指标。"""
    _validate_inputs(cases, candidate_k=candidate_k)
    initial_request_count = reranker.request_count
    initial_repair_count = reranker.repair_count
    initial_candidate_count = reranker.scored_candidate_count
    initial_input_chars = reranker.input_char_count
    initial_output_chars = reranker.output_char_count
    documents = load_workspace_documents(workspace)
    chunks = [chunk for document in documents for chunk in chunk_document(document)]
    if not documents or not chunks:
        raise RerankBaselineError("RAG workspace 没有可索引内容")

    index_started = perf_counter()
    try:
        vector_retriever = VectorRetriever(
            chunks,
            embedding_provider=embedding_provider,
            config=vector_config,
        )
    except VectorRetrievalError as exc:
        raise RerankBaselineError("向量索引构建失败") from exc
    hybrid_retriever = HybridRetriever(
        keyword_retriever=KeywordRetriever(chunks),
        vector_retriever=vector_retriever,
        config=hybrid_config,
    )
    index_build_ms = (perf_counter() - index_started) * 1000

    before_predictions: list[RAGEvalPrediction] = []
    after_predictions: list[RAGEvalPrediction] = []
    observations: list[RerankCaseObservation] = []

    for case in cases:
        requests_before = reranker.request_count
        try:
            candidates = hybrid_retriever.retrieve(case.query, top_k=candidate_k)
        except HybridRetrievalError:
            before_predictions.append(_failure_prediction(case))
            after_predictions.append(_failure_prediction(case))
            observations.append(
                RerankCaseObservation(
                    case_id=case.case_id,
                    rerank_status="retrieval_failed",
                    model_attempt_count=0,
                    rerank_ms=0,
                )
            )
            continue

        before_result = _limit_result(candidates, top_k=case.top_k)
        before_predictions.append(_success_prediction(case, before_result))
        rerank_started = perf_counter()
        after_result = rerank_retrieval_result(
            candidates,
            reranker=reranker,
            top_k=case.top_k,
            fallback_on_error=True,
        )
        rerank_ms = (perf_counter() - rerank_started) * 1000
        after_predictions.append(_success_prediction(case, after_result))
        observations.append(
            RerankCaseObservation(
                case_id=case.case_id,
                before_relevant_rank=_relevant_rank(case, before_result),
                after_relevant_rank=_relevant_rank(case, after_result),
                rerank_status=_rerank_status(after_result),
                rerank_error_code=_rerank_error_code(after_result),
                model_attempt_count=reranker.request_count - requests_before,
                rerank_ms=rerank_ms,
            )
        )

    before_run = _build_run(cases, before_predictions)
    after_run = _build_run(cases, after_predictions)
    dimensions = embedding_provider.observed_dimensions
    if dimensions is None:
        raise RerankBaselineError("provider 未记录向量维度")
    complete, returned = _count_complete_metadata(after_predictions)
    return RerankBaselineRun(
        embedding_provider_name=embedding_provider.provider_name,
        embedding_model=embedding_provider.model_name,
        reranker_name=reranker.reranker_name,
        vector_dimensions=dimensions,
        document_count=len(documents),
        chunk_count=len(chunks),
        query_count=len(cases),
        candidate_k=candidate_k,
        document_embedding_call_count=embedding_provider.document_request_count,
        query_embedding_call_count=embedding_provider.query_request_count,
        embedding_input_tokens=embedding_provider.input_tokens,
        reranker_request_count=reranker.request_count - initial_request_count,
        reranker_repair_count=reranker.repair_count - initial_repair_count,
        reranker_scored_candidate_count=(
            reranker.scored_candidate_count - initial_candidate_count
        ),
        reranker_input_char_count=reranker.input_char_count - initial_input_chars,
        reranker_output_char_count=reranker.output_char_count - initial_output_chars,
        reranker_timeout_seconds=reranker.timeout_seconds,
        reranker_transport_max_retries=reranker.transport_max_retries,
        fallback_count=sum(item.rerank_status == "fallback" for item in observations),
        metadata_completeness=complete / returned if returned else 1,
        index_build_ms=index_build_ms,
        observations=observations,
        before_run=before_run,
        before_context=evaluate_rag_context(
            cases, before_predictions, workspace=workspace
        ),
        after_run=after_run,
        after_context=evaluate_rag_context(
            cases, after_predictions, workspace=workspace
        ),
    )


def summarize_rerank_baseline_run(run: RerankBaselineRun) -> RerankBaselineSummary:
    return RerankBaselineSummary(
        embedding_provider_name=run.embedding_provider_name,
        embedding_model=run.embedding_model,
        reranker_name=run.reranker_name,
        case_ids=[item.case_id for item in run.observations],
        vector_dimensions=run.vector_dimensions,
        document_count=run.document_count,
        chunk_count=run.chunk_count,
        candidate_k=run.candidate_k,
        document_embedding_call_count=run.document_embedding_call_count,
        query_embedding_call_count=run.query_embedding_call_count,
        embedding_input_tokens=run.embedding_input_tokens,
        reranker_request_count=run.reranker_request_count,
        reranker_repair_count=run.reranker_repair_count,
        reranker_scored_candidate_count=run.reranker_scored_candidate_count,
        reranker_input_char_count=run.reranker_input_char_count,
        reranker_output_char_count=run.reranker_output_char_count,
        reranker_timeout_seconds=run.reranker_timeout_seconds,
        reranker_transport_max_retries=run.reranker_transport_max_retries,
        fallback_count=run.fallback_count,
        metadata_completeness=run.metadata_completeness,
        index_build_ms=run.index_build_ms,
        observations=run.observations,
        before_metrics=run.before_run.metrics,
        before_context=run.before_context,
        after_metrics=run.after_run.metrics,
        after_context=run.after_context,
    )


def render_rerank_baseline_report(
    run: RerankBaselineRun,
    *,
    generated_at: str,
    commit_id: str,
) -> str:
    before = run.before_run.metrics
    after = run.after_run.metrics
    rows = [
        "| Case | Before rank | After rank | Status | Error code | Attempts | Rerank latency |",
        "| --- | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    rows.extend(
        f"| `{item.case_id}` | {_rank(item.before_relevant_rank)} | "
        f"{_rank(item.after_relevant_rank)} | {item.rerank_status} | "
        f"{item.rerank_error_code or '-'} | "
        f"{item.model_attempt_count} | {item.rerank_ms:.2f} ms |"
        for item in run.observations
    )
    return "\n".join(
        [
            "# RAG Rerank Baseline",
            "",
            f"- Generated at: `{generated_at}`",
            f"- Commit: `{commit_id}`",
            f"- Embedding: `{run.embedding_provider_name}` / `{run.embedding_model}`",
            f"- Reranker: `{run.reranker_name}`",
            f"- Cases / candidates: {run.query_count} / Top-{run.candidate_k}",
            "",
            "## Quality Comparison",
            "",
            "| Metric | Hybrid before | Rerank after | Target |",
            "| --- | ---: | ---: | ---: |",
            _metric_row(
                "Hit@5", before.evidence_hit_rate, after.evidence_hit_rate, ">= before"
            ),
            _metric_row("MRR@5", before.mrr_at_5, after.mrr_at_5, ">= before"),
            _metric_row(
                "Empty accuracy",
                before.empty_result_accuracy,
                after.empty_result_accuracy,
                ">= before",
            ),
            _metric_row(
                "Location completeness",
                before.evidence_location_completeness,
                after.evidence_location_completeness,
                "100%",
            ),
            f"| Query p95 | {before.p95_latency_ms:.2f} ms | {after.p95_latency_ms:.2f} ms | observe |",
            "",
            "## Reliability And Cost",
            "",
            f"- Reranker requests / repair retries: {run.reranker_request_count} / {run.reranker_repair_count}",
            f"- Scored candidates: {run.reranker_scored_candidate_count}",
            f"- Reranker input / output characters: {run.reranker_input_char_count} / {run.reranker_output_char_count}",
            f"- Transport timeout / SDK retries: {_optional(run.reranker_timeout_seconds)} s / {_optional(run.reranker_transport_max_retries)}",
            f"- Fallback cases: {run.fallback_count}",
            f"- Rerank metadata completeness: {run.metadata_completeness * 100:.1f}%",
            f"- Embedding document / query calls: {run.document_embedding_call_count} / {run.query_embedding_call_count}",
            f"- Embedding input tokens: {run.embedding_input_tokens}",
            f"- Index build latency: {run.index_build_ms:.2f} ms",
            "",
            "## Case Observations",
            "",
            *rows,
            "",
            "## Interpretation",
            "",
            "The reranker scores only bounded Hybrid candidates and binds scores back by chunk_id.",
            "Controlled reranker failures preserve the Hybrid order and expose fallback status, error code, and latency in evidence metadata.",
            "The persisted summary excludes queries, excerpts, provider responses, credentials, and private endpoint details.",
            "",
        ]
    )


def _validate_inputs(cases: list[RAGEvalCase], *, candidate_k: int) -> None:
    if not cases:
        raise RerankBaselineError("RAG eval cases 不能为空")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise RerankBaselineError("case_id 必须唯一")
    if not any(not case.expect_empty for case in cases):
        raise RerankBaselineError("RAG eval cases 必须包含正样本")
    if not any(case.expect_empty for case in cases):
        raise RerankBaselineError("RAG eval cases 必须包含负样本")
    if isinstance(candidate_k, bool) or not isinstance(candidate_k, int):
        raise RerankBaselineError("candidate_k 必须是整数")
    if not max(case.top_k for case in cases) <= candidate_k <= 20:
        raise RerankBaselineError("candidate_k 必须覆盖 top_k 且不超过 20")


def _success_prediction(
    case: RAGEvalCase, result: RetrievalResult
) -> RAGEvalPrediction:
    return RAGEvalPrediction(
        case_id=case.case_id,
        predicted_tool_name=case.expected_tool_name,
        tool_success=True,
        retrieval_result=result,
        answer_text="\n\n".join(item.excerpt for item in result.items),
        latency_ms=result.retrieval_ms,
    )


def _failure_prediction(case: RAGEvalCase) -> RAGEvalPrediction:
    return RAGEvalPrediction(
        case_id=case.case_id,
        predicted_tool_name=case.expected_tool_name,
        tool_success=False,
        latency_ms=0,
        error_code="HYBRID_RETRIEVAL_ERROR",
    )


def _build_run(
    cases: list[RAGEvalCase], predictions: list[RAGEvalPrediction]
) -> RAGEvalRun:
    return RAGEvalRun(
        metrics=evaluate_rag_predictions(cases, predictions),
        predictions=predictions,
    )


def _limit_result(result: RetrievalResult, *, top_k: int) -> RetrievalResult:
    items = result.items[:top_k]
    return result.model_copy(
        update={
            "top_k": top_k,
            "items": items,
            "truncated": result.truncated or result.total_candidates > len(items),
        }
    )


def _relevant_rank(case: RAGEvalCase, result: RetrievalResult) -> int | None:
    expected_paths = set(case.expected_paths)
    return next(
        (item.rank for item in result.items if item.path in expected_paths),
        None,
    )


def _rerank_status(result: RetrievalResult) -> str:
    if not result.items:
        return "skipped"
    return result.items[0].metadata.get("rerank_status", "fallback")


def _rerank_error_code(result: RetrievalResult) -> str | None:
    if not result.items:
        return None
    return result.items[0].metadata.get("rerank_error_code")


def _count_complete_metadata(
    predictions: list[RAGEvalPrediction],
) -> tuple[int, int]:
    complete = 0
    returned = 0
    for prediction in predictions:
        result = prediction.retrieval_result
        if result is None:
            continue
        for item in result.items:
            returned += 1
            status = item.metadata.get("rerank_status")
            required = {"reranker", "rerank_status", "rerank_ms"}
            if status == "success":
                required |= {"recall_rank", "recall_score", "rerank_score"}
            elif status == "fallback":
                required.add("rerank_error_code")
            if status in {"success", "fallback"} and required <= item.metadata.keys():
                complete += 1
    return complete, returned


def _metric_row(name: str, before: float, after: float, target: str) -> str:
    return f"| {name} | {before * 100:.1f}% | {after * 100:.1f}% | {target} |"


def _rank(value: int | None) -> str:
    return str(value) if value is not None else "-"


def _optional(value: object | None) -> str:
    return str(value) if value is not None else "provider default"
