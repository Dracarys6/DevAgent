from collections import defaultdict
from math import isclose
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.tools.knowledge_tools import load_workspace_documents

from .runner import (
    RAGEvalCase,
    RAGEvalMetrics,
    RAGEvalPrediction,
    RAGEvalRun,
    evaluate_rag_predictions,
)

_BUSINESS_CATEGORIES = ("ci", "log", "diagnosis", "review")


class RAGReportModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )


class RAGContextCategoryMetrics(RAGReportModel):
    category: str = Field(min_length=1, max_length=100)
    case_count: int = Field(ge=1)
    evidence_hit_count: int = Field(ge=0)
    evidence_hit_rate: float = Field(ge=0, le=1)
    average_retrieved_context_chars: float = Field(ge=0)
    context_reduction_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_category_counts(self) -> "RAGContextCategoryMetrics":
        if self.evidence_hit_count > self.case_count:
            raise ValueError("evidence_hit_count 不能大于 case_count")
        expected_rate = self.evidence_hit_count / self.case_count
        if not isclose(self.evidence_hit_rate, expected_rate, abs_tol=1e-12):
            raise ValueError("evidence_hit_rate 与命中数量不一致")
        return self


class RAGContextMetrics(RAGReportModel):
    corpus_document_count: int = Field(ge=1)
    corpus_chars_per_case: int = Field(ge=1)
    positive_case_count: int = Field(ge=1)
    full_context_chars_total: int = Field(ge=1)
    retrieved_context_chars_total: int = Field(ge=0)
    average_full_context_chars: float = Field(ge=1)
    average_retrieved_context_chars: float = Field(ge=0)
    max_retrieved_context_chars: int = Field(ge=0)
    context_reduction_rate: float = Field(ge=0, le=1)
    categories: list[RAGContextCategoryMetrics] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_context_totals(self) -> "RAGContextMetrics":
        expected_full = self.corpus_chars_per_case * self.positive_case_count
        if self.full_context_chars_total != expected_full:
            raise ValueError("full_context_chars_total 与 corpus 和 case 数量不一致")
        if self.retrieved_context_chars_total > self.full_context_chars_total:
            raise ValueError("retrieved context 不能大于 full context")
        expected_reduction = (
            1 - self.retrieved_context_chars_total / self.full_context_chars_total
        )
        if not isclose(
            self.context_reduction_rate,
            expected_reduction,
            abs_tol=1e-12,
        ):
            raise ValueError("context_reduction_rate 与字符总量不一致")
        category_names = [item.category for item in self.categories]
        if category_names != sorted(category_names):
            raise ValueError("categories 必须按名称排序")
        if len(category_names) != len(set(category_names)):
            raise ValueError("categories 不能重复")
        if sum(item.case_count for item in self.categories) != self.positive_case_count:
            raise ValueError("category case 总数与 positive_case_count 不一致")
        return self


class RAGBaselineSummary(RAGReportModel):
    """不包含 query、excerpt 或答案正文的 BM25 基线摘要。"""

    case_ids: list[str] = Field(min_length=1)
    metrics: RAGEvalMetrics
    context: RAGContextMetrics

    @model_validator(mode="after")
    def validate_counts(self) -> "RAGBaselineSummary":
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case_ids 不能重复")
        if self.metrics.case_count != len(self.case_ids):
            raise ValueError("metrics case 数量必须等于 case_ids 数量")
        if self.context.positive_case_count != self.metrics.positive_case_count:
            raise ValueError("context 与 metrics 正样本数量不一致")
        return self


def evaluate_rag_context(
    cases: list[RAGEvalCase],
    predictions: list[RAGEvalPrediction],
    *,
    workspace: str | Path,
) -> RAGContextMetrics:
    """比较 full-corpus oracle 与 Top-K evidence 的上下文字符量。"""
    evaluate_rag_predictions(cases, predictions)
    documents = load_workspace_documents(workspace)
    if not documents:
        raise ValueError("RAG Evaluation workspace 没有可用文档")

    corpus_chars = sum(len(document.content) for document in documents)
    prediction_by_id = {item.case_id: item for item in predictions}
    positive_cases = [case for case in cases if not case.expect_empty]
    if not positive_cases:
        raise ValueError("RAG Context Evaluation 至少需要一个正样本")
    retrieved_chars_total = 0
    max_retrieved_chars = 0
    category_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])

    for case in positive_cases:
        prediction = prediction_by_id[case.case_id]
        items = (
            prediction.retrieval_result.items
            if prediction.retrieval_result is not None
            else []
        )
        retrieved_chars = sum(len(item.excerpt) for item in items)
        actual_paths = {item.path for item in items}
        evidence_hit = bool(actual_paths & set(case.expected_paths))

        retrieved_chars_total += retrieved_chars
        max_retrieved_chars = max(max_retrieved_chars, retrieved_chars)
        stats = category_stats[case.category]
        stats[0] += 1
        stats[1] += int(evidence_hit)
        stats[2] += retrieved_chars

    full_context_chars_total = corpus_chars * len(positive_cases)
    categories = [
        RAGContextCategoryMetrics(
            category=category,
            case_count=values[0],
            evidence_hit_count=values[1],
            evidence_hit_rate=values[1] / values[0],
            average_retrieved_context_chars=values[2] / values[0],
            context_reduction_rate=1 - values[2] / (corpus_chars * values[0]),
        )
        for category, values in sorted(category_stats.items())
    ]
    return RAGContextMetrics(
        corpus_document_count=len(documents),
        corpus_chars_per_case=corpus_chars,
        positive_case_count=len(positive_cases),
        full_context_chars_total=full_context_chars_total,
        retrieved_context_chars_total=retrieved_chars_total,
        average_full_context_chars=corpus_chars,
        average_retrieved_context_chars=retrieved_chars_total / len(positive_cases),
        max_retrieved_context_chars=max_retrieved_chars,
        context_reduction_rate=1 - retrieved_chars_total / full_context_chars_total,
        categories=categories,
    )


def render_rag_baseline_report(
    *,
    run: RAGEvalRun,
    context_metrics: RAGContextMetrics,
    commit_id: str,
    generated_at: str,
) -> str:
    """把 RAG 质量、上下文与延迟指标渲染为 Markdown baseline。"""
    quality = run.metrics
    if quality.positive_case_count != context_metrics.positive_case_count:
        raise ValueError("RAG quality 与 context metrics 的正样本数量不一致")

    def percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    business_by_name = {
        item.category: item
        for item in context_metrics.categories
        if item.category in _BUSINESS_CATEGORIES
    }
    business_rows = [
        (
            f"| {category} | {item.case_count} | "
            f"{percent(item.evidence_hit_rate)} | "
            f"{item.average_retrieved_context_chars:.1f} | "
            f"{percent(item.context_reduction_rate)} |"
        )
        for category in _BUSINESS_CATEGORIES
        if (item := business_by_name.get(category)) is not None
    ]

    return "\n".join(
        [
            "# RAG Evaluation Baseline",
            "",
            f"- Generated at: `{generated_at}`",
            f"- Commit: `{commit_id}`",
            f"- Cases: {quality.case_count}",
            f"- Positive / negative: {quality.positive_case_count} / {quality.negative_case_count}",
            f"- Corpus documents: {context_metrics.corpus_document_count}",
            "",
            "## Quality And Performance",
            "",
            "| Metric | Result | Target |",
            "| --- | ---: | ---: |",
            f"| Tool Hit Rate | {percent(quality.tool_hit_rate)} | 100% |",
            f"| Top-5 Evidence Hit Rate | {percent(quality.evidence_hit_rate)} | >= 80% |",
            f"| Precision@5 | {percent(quality.precision_at_5)} | compare |",
            f"| Recall@5 | {percent(quality.recall_at_5)} | >= 80% |",
            f"| NDCG@5 | {percent(quality.ndcg_at_5)} | compare |",
            f"| MRR@5 | {percent(quality.mrr_at_5)} | baseline |",
            f"| Answer Keyword Hit Rate | {percent(quality.answer_keyword_hit_rate)} | >= 80% |",
            f"| Empty Result Accuracy | {percent(quality.empty_result_accuracy)} | 100% |",
            f"| Evidence Location Completeness | {percent(quality.evidence_location_completeness)} | >= 90% |",
            f"| Context Reduction Rate | {percent(context_metrics.context_reduction_rate)} | >= 40% |",
            f"| Retrieval p95 | {quality.p95_latency_ms:.2f} ms | < 800 ms |",
            "",
            "## Context Efficiency",
            "",
            "| Strategy | Average chars / positive case | Evidence availability |",
            "| --- | ---: | ---: |",
            f"| Full-corpus oracle injection | {context_metrics.average_full_context_chars:.1f} | 100.0% oracle |",
            f"| BM25 Top-5 evidence injection | {context_metrics.average_retrieved_context_chars:.1f} | {percent(quality.evidence_hit_rate)} |",
            "",
            f"- Full context total: {context_metrics.full_context_chars_total}",
            f"- Retrieved context total: {context_metrics.retrieved_context_chars_total}",
            f"- Maximum retrieved context for one case: {context_metrics.max_retrieved_context_chars}",
            "",
            "## Business Slices",
            "",
            "| Category | Cases | Evidence Hit | Average retrieved chars | Context reduction |",
            "| --- | ---: | ---: | ---: | ---: |",
            *business_rows,
            "",
            "## Failure Analysis",
            "",
            f"- `tool_failure`: {_render_values(quality.failed_tool_case_ids)}",
            f"- `miss_at_5`: {_render_values(quality.missed_evidence_case_ids)}",
            f"- `false_positive_non_empty`: {_render_values(quality.incorrect_non_empty_case_ids)}",
            f"- `incomplete_location`: {_render_values(quality.incomplete_location_case_ids)}",
            f"- `answer_keyword_miss`: {_render_values(quality.missing_answer_keywords)}",
            "",
            "## Interpretation And Boundaries",
            "",
            "This deterministic local baseline compares full-corpus oracle availability with BM25 Top-5 evidence injection.",
            "Hit@5 measures whether any relevant path is retrieved; Precision@5 and Recall@5 measure evidence density and coverage; NDCG@5 uses graded relevance; MRR@5 measures how early the first relevant result appears.",
            "Current fixtures are path-level judgments. Unlisted paths are treated as irrelevant, and legacy expected_paths migrate to relevance grade 3; chunk-level relevance still requires finer annotations.",
            "The report measures retrieval evidence quality, context efficiency, and local tool latency; it does not measure live-LLM answer accuracy or provider network latency.",
            "Negative cases are scored with Empty Result Accuracy and are excluded from Context Reduction Rate.",
            "",
        ]
    )


def summarize_rag_baseline_run(
    *,
    run: RAGEvalRun,
    context_metrics: RAGContextMetrics,
    case_ids: list[str],
) -> RAGBaselineSummary:
    """生成统一优化报告可以安全消费的 BM25 结构化摘要。"""
    return RAGBaselineSummary(
        case_ids=case_ids,
        metrics=run.metrics,
        context=context_metrics,
    )


def _render_values(values: list[str]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{value}`" for value in values)
