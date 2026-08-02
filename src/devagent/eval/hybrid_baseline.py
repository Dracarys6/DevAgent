from math import isclose
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.memory import (
    HybridRetrievalError,
    HybridRetrieverConfig,
    KeywordRetriever,
    RetrievalResult,
    VectorRetrievalError,
    VectorRetriever,
    VectorRetrieverConfig,
    chunk_document,
    fuse_retrieval_results,
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


class HybridBaselineError(RuntimeError):
    """Hybrid baseline 无法形成可信、同口径的三策略结果。"""


class HybridBaselineRun(BaseModel):
    """包含逐 case 结果的内存评测对象。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    provider_name: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=200)
    vector_dimensions: int = Field(ge=1)
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    query_count: int = Field(ge=1)
    candidate_k: int = Field(ge=1, le=50)
    rrf_k: int = Field(ge=1)
    keyword_weight: float = Field(gt=0)
    vector_weight: float = Field(gt=0)
    document_embedding_call_count: int = Field(ge=1)
    query_embedding_call_count: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    index_build_ms: float = Field(ge=0)
    traced_hybrid_evidence_count: int = Field(ge=0)
    returned_hybrid_evidence_count: int = Field(ge=0)
    candidate_source_traceability: float = Field(ge=0, le=1)
    hybrid_run: RAGEvalRun
    hybrid_context: RAGContextMetrics
    vector_run: RAGEvalRun
    vector_context: RAGContextMetrics
    bm25_run: RAGEvalRun
    bm25_context: RAGContextMetrics

    @model_validator(mode="after")
    def validate_cross_metrics(self) -> "HybridBaselineRun":
        runs = (self.hybrid_run, self.vector_run, self.bm25_run)
        if any(run.metrics.case_count != self.query_count for run in runs):
            raise ValueError("策略 case 数量必须等于 query_count")
        contexts = (self.hybrid_context, self.vector_context, self.bm25_context)
        if any(
            context.corpus_document_count != self.document_count for context in contexts
        ):
            raise ValueError("context 文档数量不一致")
        if self.traced_hybrid_evidence_count > self.returned_hybrid_evidence_count:
            raise ValueError("traced evidence 不能大于 returned evidence")
        expected_traceability = (
            self.traced_hybrid_evidence_count / self.returned_hybrid_evidence_count
            if self.returned_hybrid_evidence_count
            else 1.0
        )
        if not isclose(
            self.candidate_source_traceability,
            expected_traceability,
            abs_tol=1e-12,
        ):
            raise ValueError("candidate_source_traceability 与证据数量不一致")
        return self


class HybridBaselineSummary(BaseModel):
    """不包含 query、excerpt 和 answer_text 的可持久化 Hybrid 报告。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    provider_name: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=200)
    case_ids: list[str] = Field(min_length=1)
    vector_dimensions: int = Field(ge=1)
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    candidate_k: int = Field(ge=1, le=50)
    rrf_k: int = Field(ge=1)
    keyword_weight: float = Field(gt=0)
    vector_weight: float = Field(gt=0)
    document_embedding_call_count: int = Field(ge=1)
    query_embedding_call_count: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    index_build_ms: float = Field(ge=0)
    candidate_source_traceability: float = Field(ge=0, le=1)
    hybrid_metrics: RAGEvalMetrics
    hybrid_context: RAGContextMetrics
    vector_metrics: RAGEvalMetrics
    vector_context: RAGContextMetrics
    bm25_metrics: RAGEvalMetrics
    bm25_context: RAGContextMetrics

    @model_validator(mode="after")
    def validate_summary_counts(self) -> "HybridBaselineSummary":
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case_ids 不能重复")
        metrics = (
            self.hybrid_metrics,
            self.vector_metrics,
            self.bm25_metrics,
        )
        if any(metric.case_count != len(self.case_ids) for metric in metrics):
            raise ValueError("策略 case 数量必须等于 case_ids 数量")
        return self


def run_hybrid_baseline(
    cases: list[RAGEvalCase],
    *,
    workspace: str | Path,
    embedding_provider: MeasuredEmbeddingProvider,
    hybrid_config: HybridRetrieverConfig | None = None,
    vector_config: VectorRetrieverConfig | None = None,
) -> HybridBaselineRun:
    """复用一次两路查询结果，比较 BM25、Vector 和 Hybrid。"""
    _validate_cases(cases)
    config = hybrid_config or HybridRetrieverConfig()
    documents = load_workspace_documents(workspace)
    chunks = [chunk for document in documents for chunk in chunk_document(document)]
    if not documents or not chunks:
        raise HybridBaselineError("RAG workspace 没有可索引内容")

    index_started = perf_counter()
    keyword_retriever = KeywordRetriever(chunks)
    try:
        vector_retriever = VectorRetriever(
            chunks,
            embedding_provider=embedding_provider,
            config=vector_config,
        )
    except VectorRetrievalError as exc:
        raise HybridBaselineError("向量索引构建失败") from exc
    index_build_ms = (perf_counter() - index_started) * 1000

    hybrid_predictions: list[RAGEvalPrediction] = []
    vector_predictions: list[RAGEvalPrediction] = []
    bm25_predictions: list[RAGEvalPrediction] = []
    candidate_k = max(config.candidate_k, max(case.top_k for case in cases))

    for case in cases:
        keyword_result = keyword_retriever.retrieve(case.query, top_k=candidate_k)
        bm25_predictions.append(_success_prediction(case, keyword_result))
        try:
            vector_result = vector_retriever.retrieve(case.query, top_k=candidate_k)
        except VectorRetrievalError:
            vector_predictions.append(
                _failure_prediction(case, "VECTOR_RETRIEVAL_ERROR")
            )
            hybrid_predictions.append(_failure_prediction(case, "HYBRID_SOURCE_ERROR"))
            continue

        vector_predictions.append(_success_prediction(case, vector_result))
        try:
            hybrid_result = fuse_retrieval_results(
                keyword_result=keyword_result,
                vector_result=vector_result,
                top_k=case.top_k,
                config=config,
            )
        except HybridRetrievalError:
            hybrid_predictions.append(_failure_prediction(case, "HYBRID_FUSION_ERROR"))
        else:
            hybrid_predictions.append(_success_prediction(case, hybrid_result))

    bm25_predictions = [
        _limit_prediction(prediction, top_k=case.top_k)
        for case, prediction in zip(cases, bm25_predictions, strict=True)
    ]
    vector_predictions = [
        _limit_prediction(prediction, top_k=case.top_k)
        for case, prediction in zip(cases, vector_predictions, strict=True)
    ]
    hybrid_run = _build_eval_run(cases, hybrid_predictions)
    vector_run = _build_eval_run(cases, vector_predictions)
    bm25_run = _build_eval_run(cases, bm25_predictions)

    dimensions = embedding_provider.observed_dimensions
    if dimensions is None:
        raise HybridBaselineError("provider 未记录向量维度")
    traced, returned = _count_traceable_hybrid_evidence(hybrid_predictions)
    return HybridBaselineRun(
        provider_name=embedding_provider.provider_name,
        model=embedding_provider.model_name,
        vector_dimensions=dimensions,
        document_count=len(documents),
        chunk_count=len(chunks),
        query_count=len(cases),
        candidate_k=config.candidate_k,
        rrf_k=config.rrf_k,
        keyword_weight=config.keyword_weight,
        vector_weight=config.vector_weight,
        document_embedding_call_count=embedding_provider.document_request_count,
        query_embedding_call_count=embedding_provider.query_request_count,
        input_tokens=embedding_provider.input_tokens,
        index_build_ms=index_build_ms,
        traced_hybrid_evidence_count=traced,
        returned_hybrid_evidence_count=returned,
        candidate_source_traceability=traced / returned if returned else 1.0,
        hybrid_run=hybrid_run,
        hybrid_context=evaluate_rag_context(
            cases,
            hybrid_predictions,
            workspace=workspace,
        ),
        vector_run=vector_run,
        vector_context=evaluate_rag_context(
            cases,
            vector_predictions,
            workspace=workspace,
        ),
        bm25_run=bm25_run,
        bm25_context=evaluate_rag_context(
            cases,
            bm25_predictions,
            workspace=workspace,
        ),
    )


def summarize_hybrid_baseline_run(run: HybridBaselineRun) -> HybridBaselineSummary:
    """生成保留指标和 case 身份的脱敏摘要。"""
    return HybridBaselineSummary(
        provider_name=run.provider_name,
        model=run.model,
        case_ids=[prediction.case_id for prediction in run.hybrid_run.predictions],
        vector_dimensions=run.vector_dimensions,
        document_count=run.document_count,
        chunk_count=run.chunk_count,
        candidate_k=run.candidate_k,
        rrf_k=run.rrf_k,
        keyword_weight=run.keyword_weight,
        vector_weight=run.vector_weight,
        document_embedding_call_count=run.document_embedding_call_count,
        query_embedding_call_count=run.query_embedding_call_count,
        input_tokens=run.input_tokens,
        index_build_ms=run.index_build_ms,
        candidate_source_traceability=run.candidate_source_traceability,
        hybrid_metrics=run.hybrid_run.metrics,
        hybrid_context=run.hybrid_context,
        vector_metrics=run.vector_run.metrics,
        vector_context=run.vector_context,
        bm25_metrics=run.bm25_run.metrics,
        bm25_context=run.bm25_context,
    )


def render_hybrid_baseline_report(
    run: HybridBaselineRun,
    *,
    generated_at: str,
    commit_id: str,
) -> str:
    """渲染三策略质量、延迟和上下文成本对比。"""
    hybrid = run.hybrid_run.metrics
    vector = run.vector_run.metrics
    bm25 = run.bm25_run.metrics

    def percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    return "\n".join(
        [
            "# RAG Hybrid Baseline",
            "",
            f"- Generated at: `{generated_at}`",
            f"- Commit: `{commit_id}`",
            f"- Provider / model: `{run.provider_name}` / `{run.model}`",
            f"- Cases: {run.query_count}",
            f"- Documents / chunks: {run.document_count} / {run.chunk_count}",
            "",
            "## Fusion Configuration",
            "",
            "- Strategy: Reciprocal Rank Fusion",
            f"- Candidate K / RRF K: {run.candidate_k} / {run.rrf_k}",
            f"- BM25 / Vector weight: {run.keyword_weight:g} / {run.vector_weight:g}",
            f"- Candidate source traceability: {percent(run.candidate_source_traceability)}",
            "",
            "## Quality And Performance",
            "",
            "| Metric | Hybrid RRF | BM25 | Vector | Target |",
            "| --- | ---: | ---: | ---: | ---: |",
            _metric_row(
                "Top-5 Evidence Hit Rate",
                hybrid.evidence_hit_rate,
                bm25.evidence_hit_rate,
                vector.evidence_hit_rate,
                ">= BM25",
            ),
            _metric_row(
                "MRR@5", hybrid.mrr_at_5, bm25.mrr_at_5, vector.mrr_at_5, "observe"
            ),
            _metric_row(
                "Empty Result Accuracy",
                hybrid.empty_result_accuracy,
                bm25.empty_result_accuracy,
                vector.empty_result_accuracy,
                "observe",
            ),
            _metric_row(
                "Evidence Location Completeness",
                hybrid.evidence_location_completeness,
                bm25.evidence_location_completeness,
                vector.evidence_location_completeness,
                "100%",
            ),
            _metric_row(
                "Context Reduction",
                run.hybrid_context.context_reduction_rate,
                run.bm25_context.context_reduction_rate,
                run.vector_context.context_reduction_rate,
                ">= 40%",
            ),
            f"| Query p50 | {hybrid.p50_latency_ms:.2f} ms | {bm25.p50_latency_ms:.2f} ms | {vector.p50_latency_ms:.2f} ms | observe |",
            f"| Query p95 | {hybrid.p95_latency_ms:.2f} ms | {bm25.p95_latency_ms:.2f} ms | {vector.p95_latency_ms:.2f} ms | < 800 ms |",
            "",
            "## Provider And Index Cost",
            "",
            f"- Vector dimensions: {run.vector_dimensions}",
            f"- Document embedding calls: {run.document_embedding_call_count}",
            f"- Query embedding calls: {run.query_embedding_call_count}",
            f"- Provider-reported input tokens: {run.input_tokens}",
            f"- Index build latency: {run.index_build_ms:.2f} ms",
            "",
            "## Failure Analysis",
            "",
            f"- Hybrid tool failures: {_render_values(hybrid.failed_tool_case_ids)}",
            f"- Hybrid miss@5: {_render_values(hybrid.missed_evidence_case_ids)}",
            f"- Hybrid false-positive non-empty: {_render_values(hybrid.incorrect_non_empty_case_ids)}",
            "",
            "## Interpretation",
            "",
            "Hybrid RRF is an uncalibrated candidate union baseline; it does not prove absolute relevance.",
            "Each query performs one BM25 lookup and one online query embedding, then reuses both results for all three strategy metrics.",
            "Raw queries, excerpts, answers, credentials, base URLs, headers, and provider responses are excluded from the persisted summary.",
            "",
        ]
    )


def _build_eval_run(
    cases: list[RAGEvalCase],
    predictions: list[RAGEvalPrediction],
) -> RAGEvalRun:
    return RAGEvalRun(
        metrics=evaluate_rag_predictions(cases, predictions),
        predictions=predictions,
    )


def _success_prediction(
    case: RAGEvalCase,
    result: RetrievalResult,
) -> RAGEvalPrediction:
    return RAGEvalPrediction(
        case_id=case.case_id,
        predicted_tool_name=case.expected_tool_name,
        tool_success=True,
        retrieval_result=result,
        answer_text="\n\n".join(item.excerpt for item in result.items),
        latency_ms=result.retrieval_ms,
    )


def _failure_prediction(case: RAGEvalCase, error_code: str) -> RAGEvalPrediction:
    return RAGEvalPrediction(
        case_id=case.case_id,
        predicted_tool_name=case.expected_tool_name,
        tool_success=False,
        latency_ms=0,
        error_code=error_code,
    )


def _limit_prediction(
    prediction: RAGEvalPrediction,
    *,
    top_k: int,
) -> RAGEvalPrediction:
    result = prediction.retrieval_result
    if result is None:
        return prediction
    items = result.items[:top_k]
    limited = result.model_copy(
        update={
            "top_k": top_k,
            "items": items,
            "truncated": result.truncated or result.total_candidates > len(items),
        }
    )
    return prediction.model_copy(
        update={
            "retrieval_result": limited,
            "answer_text": "\n\n".join(item.excerpt for item in items),
        }
    )


def _count_traceable_hybrid_evidence(
    predictions: list[RAGEvalPrediction],
) -> tuple[int, int]:
    traced = 0
    returned = 0
    for prediction in predictions:
        result = prediction.retrieval_result
        if result is None:
            continue
        for item in result.items:
            returned += 1
            sources = item.metadata.get("candidate_sources", "").split(",")
            valid_sources = set(sources)
            if (
                valid_sources
                and valid_sources <= {"bm25", "vector"}
                and len(sources) == len(valid_sources)
                and all(
                    f"{source}_rank" in item.metadata
                    and f"{source}_score" in item.metadata
                    for source in valid_sources
                )
            ):
                traced += 1
    return traced, returned


def _validate_cases(cases: list[RAGEvalCase]) -> None:
    if not cases:
        raise HybridBaselineError("RAG eval cases 不能为空")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise HybridBaselineError("case_id 必须唯一")
    if not any(not case.expect_empty for case in cases):
        raise HybridBaselineError("RAG eval cases 必须包含正样本")
    if not any(case.expect_empty for case in cases):
        raise HybridBaselineError("RAG eval cases 必须包含负样本")


def _metric_row(
    name: str,
    hybrid: float,
    bm25: float,
    vector: float,
    target: str,
) -> str:
    return (
        f"| {name} | {hybrid * 100:.1f}% | {bm25 * 100:.1f}% | "
        f"{vector * 100:.1f}% | {target} |"
    )


def _render_values(values: list[str]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{value}`" for value in values)
