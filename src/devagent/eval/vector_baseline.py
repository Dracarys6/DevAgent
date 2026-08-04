from pathlib import Path
from time import perf_counter
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.memory import (
    EmbeddingProvider,
    VectorRetrievalError,
    VectorRetriever,
    VectorRetrieverConfig,
    chunk_document,
)
from devagent.tools.knowledge_tools import load_workspace_documents

from .rag_report import RAGContextMetrics, evaluate_rag_context
from .runner import (
    RAGEvalCase,
    RAGEvalMetrics,
    RAGEvalPrediction,
    RAGEvalRun,
    evaluate_rag_predictions,
    run_rag_eval,
)


class MeasuredEmbeddingProvider(EmbeddingProvider, Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def observed_dimensions(self) -> int | None: ...

    @property
    def document_request_count(self) -> int: ...

    @property
    def query_request_count(self) -> int: ...

    @property
    def input_tokens(self) -> int: ...


class VectorBaselineError(RuntimeError):
    """向量 baseline 无法生成可信结果。"""


class VectorBaselineRun(BaseModel):
    """可序列化、可重新评分的向量检索 baseline。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    provider_name: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=200)
    vector_dimensions: int = Field(ge=1)
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    query_count: int = Field(ge=1)
    document_embedding_call_count: int = Field(ge=1)
    query_embedding_call_count: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    index_build_ms: float = Field(ge=0)
    vector_run: RAGEvalRun
    vector_context: RAGContextMetrics
    bm25_run: RAGEvalRun
    bm25_context: RAGContextMetrics

    @model_validator(mode="after")
    def validate_cross_metrics(self) -> "VectorBaselineRun":
        vector_quality = self.vector_run.metrics
        bm25_quality = self.bm25_run.metrics
        if vector_quality.case_count != self.query_count:
            raise ValueError("vector case 数量必须等于 query_count")
        if bm25_quality.case_count != self.query_count:
            raise ValueError("BM25 case 数量必须等于 query_count")
        if self.vector_context.corpus_document_count != self.document_count:
            raise ValueError("vector context 文档数量不一致")
        if self.bm25_context.corpus_document_count != self.document_count:
            raise ValueError("BM25 context 文档数量不一致")
        return self


class VectorBaselineSummary(BaseModel):
    """适合长期落盘且不包含检索正文的向量 baseline 摘要。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    provider_name: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=200)
    case_ids: list[str] = Field(min_length=1)
    vector_dimensions: int = Field(ge=1)
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    document_embedding_call_count: int = Field(ge=1)
    query_embedding_call_count: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    index_build_ms: float = Field(ge=0)
    vector_metrics: RAGEvalMetrics
    vector_context: RAGContextMetrics
    bm25_metrics: RAGEvalMetrics
    bm25_context: RAGContextMetrics

    @model_validator(mode="after")
    def validate_summary_counts(self) -> "VectorBaselineSummary":
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case_ids 不能重复")
        if self.vector_metrics.case_count != len(self.case_ids):
            raise ValueError("vector case 数量必须等于 case_ids 数量")
        if self.bm25_metrics.case_count != len(self.case_ids):
            raise ValueError("BM25 case 数量必须等于 case_ids 数量")
        if self.vector_context.corpus_document_count != self.document_count:
            raise ValueError("vector context 文档数量不一致")
        if self.bm25_context.corpus_document_count != self.document_count:
            raise ValueError("BM25 context 文档数量不一致")
        return self


def run_vector_baseline(
    cases: list[RAGEvalCase],
    *,
    workspace: str | Path,
    embedding_provider: MeasuredEmbeddingProvider,
    retriever_config: VectorRetrieverConfig | None = None,
) -> VectorBaselineRun:
    """构建一次真实向量索引，并以同一批 case 对比 BM25。"""
    documents = load_workspace_documents(workspace)
    chunks = [chunk for document in documents for chunk in chunk_document(document)]
    if not documents or not chunks:
        raise VectorBaselineError("RAG workspace 没有可索引内容")

    index_started = perf_counter()
    try:
        retriever = VectorRetriever(
            chunks,
            embedding_provider=embedding_provider,
            config=retriever_config,
        )
    except VectorRetrievalError as exc:
        raise VectorBaselineError("向量索引构建失败") from exc
    index_build_ms = (perf_counter() - index_started) * 1000

    predictions = [_run_vector_case(case, retriever=retriever) for case in cases]
    vector_run = RAGEvalRun(
        metrics=evaluate_rag_predictions(cases, predictions),
        predictions=predictions,
    )
    vector_context = evaluate_rag_context(
        cases,
        predictions,
        workspace=workspace,
    )
    bm25_run = run_rag_eval(cases, workspace=workspace)
    bm25_context = evaluate_rag_context(
        cases,
        bm25_run.predictions,
        workspace=workspace,
    )

    dimensions = embedding_provider.observed_dimensions
    if dimensions is None:
        raise VectorBaselineError("provider 未记录向量维度")
    return VectorBaselineRun(
        provider_name=embedding_provider.provider_name,
        model=embedding_provider.model_name,
        vector_dimensions=dimensions,
        document_count=len(documents),
        chunk_count=len(chunks),
        query_count=len(cases),
        document_embedding_call_count=embedding_provider.document_request_count,
        query_embedding_call_count=embedding_provider.query_request_count,
        input_tokens=embedding_provider.input_tokens,
        index_build_ms=index_build_ms,
        vector_run=vector_run,
        vector_context=vector_context,
        bm25_run=bm25_run,
        bm25_context=bm25_context,
    )


def render_vector_baseline_report(
    run: VectorBaselineRun,
    *,
    generated_at: str,
    commit_id: str,
) -> str:
    """渲染不包含凭据或原始 provider response 的对比报告。"""
    vector = run.vector_run.metrics
    bm25 = run.bm25_run.metrics

    def percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    return "\n".join(
        [
            "# RAG Vector Baseline",
            "",
            f"- Generated at: `{generated_at}`",
            f"- Commit: `{commit_id}`",
            f"- Provider: `{run.provider_name}`",
            f"- Model: `{run.model}`",
            f"- Cases: {run.query_count}",
            f"- Positive / negative: {vector.positive_case_count} / {vector.negative_case_count}",
            "",
            "## Index And Cost",
            "",
            f"- Documents / chunks: {run.document_count} / {run.chunk_count}",
            f"- Vector dimensions: {run.vector_dimensions}",
            f"- Document embedding API calls: {run.document_embedding_call_count}",
            f"- Query embedding API calls: {run.query_embedding_call_count}",
            f"- Provider-reported input tokens: {run.input_tokens}",
            f"- Index build latency: {run.index_build_ms:.2f} ms",
            "",
            "## Retrieval Comparison",
            "",
            "| Metric | Vector | BM25 | Target |",
            "| --- | ---: | ---: | ---: |",
            f"| Top-5 Evidence Hit Rate | {percent(vector.evidence_hit_rate)} | {percent(bm25.evidence_hit_rate)} | >= 80% |",
            f"| Precision@5 | {percent(vector.precision_at_5)} | {percent(bm25.precision_at_5)} | compare |",
            f"| Recall@5 | {percent(vector.recall_at_5)} | {percent(bm25.recall_at_5)} | >= 80% |",
            f"| NDCG@5 | {percent(vector.ndcg_at_5)} | {percent(bm25.ndcg_at_5)} | compare |",
            f"| MRR@5 | {percent(vector.mrr_at_5)} | {percent(bm25.mrr_at_5)} | observe |",
            f"| Empty Result Accuracy | {percent(vector.empty_result_accuracy)} | {percent(bm25.empty_result_accuracy)} | observe |",
            f"| Evidence Location Completeness | {percent(vector.evidence_location_completeness)} | {percent(bm25.evidence_location_completeness)} | 100% |",
            f"| Context Reduction Rate | {percent(run.vector_context.context_reduction_rate)} | {percent(run.bm25_context.context_reduction_rate)} | >= 40% |",
            f"| Query p50 | {vector.p50_latency_ms:.2f} ms | {bm25.p50_latency_ms:.2f} ms | observe |",
            f"| Query p95 | {vector.p95_latency_ms:.2f} ms | {bm25.p95_latency_ms:.2f} ms | observe |",
            "",
            "## Failure Analysis",
            "",
            f"- Vector tool failures: {_render_values(vector.failed_tool_case_ids)}",
            f"- Vector miss@5: {_render_values(vector.missed_evidence_case_ids)}",
            f"- Vector false-positive non-empty: {_render_values(vector.incorrect_non_empty_case_ids)}",
            f"- BM25 miss@5: {_render_values(bm25.missed_evidence_case_ids)}",
            "",
            "## Interpretation",
            "",
            "Vector query latency includes the online embedding request and exact cosine scan.",
            "The in-memory exact index isolates embedding quality from ANN approximation and vector database operations.",
            "Nearest-neighbor search always has a closest result, so negative-case failures are expected before threshold calibration.",
            "Provider credentials, base URL, headers, and raw responses are intentionally excluded.",
            "",
        ]
    )


def summarize_vector_baseline_run(run: VectorBaselineRun) -> VectorBaselineSummary:
    """保留可审查指标和 case 身份，不持久化 query 或 evidence 正文。"""
    return VectorBaselineSummary(
        provider_name=run.provider_name,
        model=run.model,
        case_ids=[prediction.case_id for prediction in run.vector_run.predictions],
        vector_dimensions=run.vector_dimensions,
        document_count=run.document_count,
        chunk_count=run.chunk_count,
        document_embedding_call_count=run.document_embedding_call_count,
        query_embedding_call_count=run.query_embedding_call_count,
        input_tokens=run.input_tokens,
        index_build_ms=run.index_build_ms,
        vector_metrics=run.vector_run.metrics,
        vector_context=run.vector_context,
        bm25_metrics=run.bm25_run.metrics,
        bm25_context=run.bm25_context,
    )


def _run_vector_case(
    case: RAGEvalCase,
    *,
    retriever: VectorRetriever,
) -> RAGEvalPrediction:
    started = perf_counter()
    try:
        result = retriever.retrieve(case.query, top_k=case.top_k)
    except VectorRetrievalError:
        return RAGEvalPrediction(
            case_id=case.case_id,
            predicted_tool_name=case.expected_tool_name,
            tool_success=False,
            latency_ms=(perf_counter() - started) * 1000,
            error_code="VECTOR_RETRIEVAL_ERROR",
        )
    return RAGEvalPrediction(
        case_id=case.case_id,
        predicted_tool_name=case.expected_tool_name,
        tool_success=True,
        retrieval_result=result,
        answer_text="\n\n".join(item.excerpt for item in result.items),
        latency_ms=(perf_counter() - started) * 1000,
    )


def _render_values(values: list[str]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{value}`" for value in values)
