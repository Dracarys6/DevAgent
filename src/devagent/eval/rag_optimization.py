from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from enum import Enum
from math import ceil

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .hybrid_baseline import HybridBaselineSummary
from .live_rag import LiveRAGEvalRun
from .rag_report import RAGBaselineSummary, RAGContextMetrics
from .rerank_baseline import RerankBaselineSummary
from .runner import RAGEvalMetrics
from .vector_baseline import VectorBaselineSummary

MIN_HIT_RATE = 0.80
MIN_RECALL_AT_5 = 0.80
MIN_EMPTY_RESULT_ACCURACY = 1.0
MIN_LOCATION_COMPLETENESS = 0.95
MIN_CONTEXT_REDUCTION_RATE = 0.40
MAX_GLOBAL_RETRIEVAL_P95_MS = 800.0


class RAGOptimizationError(ValueError):
    """优化输入无法形成同口径、可解释的策略决策。"""


class RetrievalStrategy(str, Enum):
    BM25 = "bm25"
    VECTOR = "vector"
    HYBRID = "hybrid_rrf"
    HYBRID_RERANK = "hybrid_rerank"


class RAGOptimizationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class StrategyEvaluation(RAGOptimizationModel):
    strategy: RetrievalStrategy
    case_ids: list[str] = Field(min_length=1)
    dataset_scope: str = Field(min_length=1, max_length=200)
    evidence_hit_rate: float = Field(ge=0, le=1)
    precision_at_5: float = Field(ge=0, le=1)
    recall_at_5: float = Field(ge=0, le=1)
    ndcg_at_5: float = Field(ge=0, le=1)
    mrr_at_5: float = Field(ge=0, le=1)
    empty_result_accuracy: float = Field(ge=0, le=1)
    context_reduction_rate: float = Field(ge=0, le=1)
    p95_latency_ms: float = Field(ge=0)
    evidence_location_completeness: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_case_ids(self) -> StrategyEvaluation:
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case_ids 不能重复")
        return self


class BusinessRAGAcceptance(RAGOptimizationModel):
    passed: bool = Field(strict=True)
    case_count: int = Field(ge=1)
    knowledge_reference_case_count: int = Field(ge=0)
    average_context_reduction_rate: float = Field(ge=0, le=1)
    locator_completeness_rate: float = Field(ge=0, le=1)
    domain_flow_availability_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_reference_count(self) -> BusinessRAGAcceptance:
        if self.knowledge_reference_case_count > self.case_count:
            raise ValueError("knowledge_reference_case_count 不能大于 case_count")
        return self


class LiveRAGStabilityMetrics(RAGOptimizationModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    api_mode: str = Field(min_length=1, max_length=100)
    run_count: int = Field(ge=2)
    case_ids: list[str] = Field(min_length=1)
    minimum_tool_call_rate: float = Field(ge=0, le=1)
    minimum_grounded_citation_rate: float = Field(ge=0, le=1)
    minimum_abstention_accuracy: float = Field(ge=0, le=1)
    mean_end_to_end_success_rate: float = Field(ge=0, le=1)
    minimum_end_to_end_success_rate: float = Field(ge=0, le=1)
    aggregate_p95_latency_ms: float = Field(ge=0)
    total_attempt_count: int = Field(ge=1)
    failed_case_frequency: dict[str, int]

    @model_validator(mode="after")
    def validate_stability(self) -> LiveRAGStabilityMetrics:
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case_ids 不能重复")
        if self.minimum_end_to_end_success_rate > self.mean_end_to_end_success_rate:
            raise ValueError("最差成功率不能大于平均成功率")
        unknown = set(self.failed_case_frequency) - set(self.case_ids)
        if unknown:
            raise ValueError("failed_case_frequency 包含未知 case_id")
        if any(
            not 1 <= count <= self.run_count
            for count in self.failed_case_frequency.values()
        ):
            raise ValueError("失败频次必须位于 1 到 run_count")
        return self


class StrategyDecision(RAGOptimizationModel):
    global_agent_default: RetrievalStrategy
    domain_anchored_default: RetrievalStrategy
    high_value_rerank: RetrievalStrategy
    reasons: list[str] = Field(min_length=1)
    rejected_global_defaults: dict[RetrievalStrategy, list[str]]

    @model_validator(mode="after")
    def validate_reasons(self) -> StrategyDecision:
        if any(not reason for reason in self.reasons):
            raise ValueError("策略决策理由不能为空")
        if any(not reasons for reasons in self.rejected_global_defaults.values()):
            raise ValueError("被拒绝策略必须包含原因")
        return self


class RAGOptimizationSummary(RAGOptimizationModel):
    generated_at: str = Field(min_length=1, max_length=100)
    revision: str = Field(min_length=1, max_length=200)
    fixed_dataset_evaluations: list[StrategyEvaluation] = Field(min_length=3)
    rerank_subset_evaluations: list[StrategyEvaluation] = Field(min_length=2)
    business_acceptance: BusinessRAGAcceptance
    live_stability: LiveRAGStabilityMetrics
    decision: StrategyDecision
    evaluation_boundaries: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_strategy_sets(self) -> RAGOptimizationSummary:
        _validate_evaluation_group(
            self.fixed_dataset_evaluations,
            expected={
                RetrievalStrategy.BM25,
                RetrievalStrategy.VECTOR,
                RetrievalStrategy.HYBRID,
            },
            label="固定集",
        )
        _validate_evaluation_group(
            self.rerank_subset_evaluations,
            expected={
                RetrievalStrategy.HYBRID,
                RetrievalStrategy.HYBRID_RERANK,
            },
            label="Rerank 子集",
        )
        return self


def aggregate_live_rag_stability(
    runs: Sequence[LiveRAGEvalRun],
) -> LiveRAGStabilityMetrics:
    """聚合同配置真实运行，保留最差值与重复失败频次。"""
    if len(runs) < 2:
        raise RAGOptimizationError("Live RAG 稳定性至少需要两次运行")
    first = runs[0]
    case_ids = [item.case_id for item in first.predictions]
    expected_identity = (first.provider, first.model, first.api_mode)
    latencies: list[float] = []
    failed_case_frequency: Counter[str] = Counter()
    for run in runs:
        if (run.provider, run.model, run.api_mode) != expected_identity:
            raise RAGOptimizationError(
                "Live RAG runs 必须使用同一 provider/model/api_mode"
            )
        current_ids = [item.case_id for item in run.predictions]
        if current_ids != case_ids:
            raise RAGOptimizationError("Live RAG runs 必须使用相同且同序的 case IDs")
        latencies.extend(item.latency_ms for item in run.predictions)
        failed_case_frequency.update(run.metrics.failed_case_ids)

    metrics = [run.metrics for run in runs]
    return LiveRAGStabilityMetrics(
        provider=first.provider,
        model=first.model,
        api_mode=first.api_mode,
        run_count=len(runs),
        case_ids=case_ids,
        minimum_tool_call_rate=min(item.tool_hit_rate for item in metrics),
        minimum_grounded_citation_rate=min(
            item.grounded_citation_rate for item in metrics
        ),
        minimum_abstention_accuracy=min(item.abstention_accuracy for item in metrics),
        mean_end_to_end_success_rate=(
            sum(item.end_to_end_success_rate for item in metrics) / len(metrics)
        ),
        minimum_end_to_end_success_rate=min(
            item.end_to_end_success_rate for item in metrics
        ),
        aggregate_p95_latency_ms=_percentile(latencies, 0.95),
        total_attempt_count=sum(
            prediction.attempt_count for run in runs for prediction in run.predictions
        ),
        failed_case_frequency=dict(sorted(failed_case_frequency.items())),
    )


def build_rag_optimization_summary(
    *,
    bm25: RAGBaselineSummary,
    vector: VectorBaselineSummary,
    hybrid: HybridBaselineSummary,
    rerank: RerankBaselineSummary,
    business_acceptance: BusinessRAGAcceptance,
    live_runs: Sequence[LiveRAGEvalRun],
    generated_at: str,
    revision: str,
) -> RAGOptimizationSummary:
    """把脱敏 JSON 摘要转换为统一策略决策，不解析 Markdown 展示文本。"""
    _validate_fixed_dataset_case_ids(bm25, vector, hybrid)
    fixed_scope = f"fixed-path-judgments:{len(bm25.case_ids)}"
    rerank_scope = f"representative-rerank-subset:{len(rerank.case_ids)}"
    fixed_evaluations = [
        _strategy_evaluation(
            RetrievalStrategy.BM25,
            bm25.case_ids,
            fixed_scope,
            bm25.metrics,
            bm25.context,
        ),
        _strategy_evaluation(
            RetrievalStrategy.VECTOR,
            vector.case_ids,
            fixed_scope,
            vector.vector_metrics,
            vector.vector_context,
        ),
        _strategy_evaluation(
            RetrievalStrategy.HYBRID,
            hybrid.case_ids,
            fixed_scope,
            hybrid.hybrid_metrics,
            hybrid.hybrid_context,
        ),
    ]
    rerank_evaluations = [
        _strategy_evaluation(
            RetrievalStrategy.HYBRID,
            rerank.case_ids,
            rerank_scope,
            rerank.before_metrics,
            rerank.before_context,
        ),
        _strategy_evaluation(
            RetrievalStrategy.HYBRID_RERANK,
            rerank.case_ids,
            rerank_scope,
            rerank.after_metrics,
            rerank.after_context,
        ),
    ]
    stability = aggregate_live_rag_stability(live_runs)
    decision = decide_retrieval_strategies(
        fixed_evaluations=fixed_evaluations,
        rerank_evaluations=rerank_evaluations,
        business_acceptance=business_acceptance,
    )
    return RAGOptimizationSummary(
        generated_at=generated_at,
        revision=revision,
        fixed_dataset_evaluations=fixed_evaluations,
        rerank_subset_evaluations=rerank_evaluations,
        business_acceptance=business_acceptance,
        live_stability=stability,
        decision=decision,
        evaluation_boundaries=[
            "Precision@5、Recall@5 与 NDCG@5 使用路径级人工判断；未标注路径按不相关处理。",
            "legacy expected_paths 迁移为 grade 3，当前 NDCG 仍不是 chunk 级完整标注。",
            "Rerank 只在代表性子集评测，不能与 36 条完整集指标伪装成同口径实验。",
            "真实 Agent 稳定性是代表集证据，不等同生产 SLA。",
        ],
    )


def decide_retrieval_strategies(
    *,
    fixed_evaluations: Sequence[StrategyEvaluation],
    rerank_evaluations: Sequence[StrategyEvaluation],
    business_acceptance: BusinessRAGAcceptance,
) -> StrategyDecision:
    """先应用可靠性硬门槛，再用排序质量和成本选择全局默认。"""
    by_strategy = {item.strategy: item for item in fixed_evaluations}
    required = {
        RetrievalStrategy.BM25,
        RetrievalStrategy.VECTOR,
        RetrievalStrategy.HYBRID,
    }
    if set(by_strategy) != required:
        raise RAGOptimizationError("固定集必须包含 BM25、Vector 和 Hybrid")

    rejected: dict[RetrievalStrategy, list[str]] = {}
    eligible: list[StrategyEvaluation] = []
    for evaluation in fixed_evaluations:
        failures = _global_gate_failures(evaluation)
        if failures:
            rejected[evaluation.strategy] = failures
        else:
            eligible.append(evaluation)
    if not eligible:
        raise RAGOptimizationError("没有策略通过开放式 Agent 全局硬门槛")

    global_default = max(
        eligible,
        key=lambda item: (
            item.recall_at_5,
            item.evidence_hit_rate,
            item.ndcg_at_5,
            item.mrr_at_5,
            item.precision_at_5,
            item.context_reduction_rate,
            -item.p95_latency_ms,
        ),
    ).strategy
    domain_default = (
        RetrievalStrategy.HYBRID if business_acceptance.passed else global_default
    )

    rerank_by_strategy = {item.strategy: item for item in rerank_evaluations}
    if set(rerank_by_strategy) != {
        RetrievalStrategy.HYBRID,
        RetrievalStrategy.HYBRID_RERANK,
    }:
        raise RAGOptimizationError("Rerank 子集必须包含重排前后的 Hybrid")
    reranked = rerank_by_strategy[RetrievalStrategy.HYBRID_RERANK]
    before = rerank_by_strategy[RetrievalStrategy.HYBRID]
    rerank_reasons = ["只在代表性子集评测，不能作为全局默认"]
    rerank_reasons.extend(_global_gate_failures(reranked))
    if not rerank_reasons:
        rerank_reasons.append("增加额外 provider 调用和故障点")
    rejected[RetrievalStrategy.HYBRID_RERANK] = list(dict.fromkeys(rerank_reasons))

    quality_non_regression = all(
        (
            reranked.evidence_hit_rate >= before.evidence_hit_rate,
            reranked.ndcg_at_5 >= before.ndcg_at_5,
            reranked.mrr_at_5 >= before.mrr_at_5,
        )
    )
    high_value = (
        RetrievalStrategy.HYBRID_RERANK if quality_non_regression else domain_default
    )
    return StrategyDecision(
        global_agent_default=global_default,
        domain_anchored_default=domain_default,
        high_value_rerank=high_value,
        reasons=[
            "开放式 Agent 先要求负样本拒答、定位完整性、上下文压缩和延迟全部达标。",
            "通过硬门槛后再比较 Recall、Hit、NDCG、MRR、Precision 与成本。",
            "领域业务由 CI、日志或 Git 工具提供权威锚点，Hybrid 只补充代码上下文。",
            "Rerank 仅在质量不回退且调用方接受额外延迟时显式启用。",
        ],
        rejected_global_defaults=rejected,
    )


def render_rag_optimization_report(summary: RAGOptimizationSummary) -> str:
    """渲染统一质量、可靠性、成本和默认策略报告。"""
    lines = [
        "# RAG Optimization And Week 9 Acceptance",
        "",
        f"- Generated at: `{summary.generated_at}`",
        f"- Revision: `{summary.revision}`",
        "",
        "## Fixed Dataset Comparison",
        "",
        "| Strategy | Cases | Hit@5 | Precision@5 | Recall@5 | NDCG@5 | MRR@5 | Empty | Context reduction | p95 | Location |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(_strategy_row(item) for item in summary.fixed_dataset_evaluations)
    lines.extend(
        [
            "",
            "## Representative Rerank Subset",
            "",
            "| Strategy | Cases | Hit@5 | Precision@5 | Recall@5 | NDCG@5 | MRR@5 | Empty | Context reduction | p95 | Location |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_strategy_row(item) for item in summary.rerank_subset_evaluations)
    business = summary.business_acceptance
    stability = summary.live_stability
    decision = summary.decision
    lines.extend(
        [
            "",
            "## Business And Live Acceptance",
            "",
            f"- Domain Hybrid workflows passed: `{business.passed}` ({business.knowledge_reference_case_count}/{business.case_count} referenced knowledge evidence)",
            f"- Business context reduction: {_percent(business.average_context_reduction_rate)}",
            f"- Business locator completeness: {_percent(business.locator_completeness_rate)}",
            f"- Live runs / cases: {stability.run_count} / {len(stability.case_ids)}",
            f"- Minimum Tool Call / Grounded Citation / Abstention: {_percent(stability.minimum_tool_call_rate)} / {_percent(stability.minimum_grounded_citation_rate)} / {_percent(stability.minimum_abstention_accuracy)}",
            f"- Mean / minimum strict success: {_percent(stability.mean_end_to_end_success_rate)} / {_percent(stability.minimum_end_to_end_success_rate)}",
            f"- Aggregate end-to-end p95: {stability.aggregate_p95_latency_ms:.2f} ms",
            f"- Repeated failed cases: {_render_frequency(stability.failed_case_frequency)}",
            "",
            "## Default Strategy Decision",
            "",
            f"- Open Agent default: `{decision.global_agent_default.value}`",
            f"- Domain-anchored default: `{decision.domain_anchored_default.value}`",
            f"- High-value explicit rerank: `{decision.high_value_rerank.value}`",
            "",
            *[f"- {reason}" for reason in decision.reasons],
            "",
            "### Rejected As Global Defaults",
            "",
            *[
                f"- `{strategy.value}`: {'; '.join(reasons)}"
                for strategy, reasons in decision.rejected_global_defaults.items()
            ],
            "",
            "## Evaluation Boundaries",
            "",
            *[f"- {boundary}" for boundary in summary.evaluation_boundaries],
            "",
        ]
    )
    return "\n".join(lines)


def _strategy_evaluation(
    strategy: RetrievalStrategy,
    case_ids: list[str],
    dataset_scope: str,
    metrics: RAGEvalMetrics,
    context: RAGContextMetrics,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy=strategy,
        case_ids=case_ids,
        dataset_scope=dataset_scope,
        evidence_hit_rate=metrics.evidence_hit_rate,
        precision_at_5=metrics.precision_at_5,
        recall_at_5=metrics.recall_at_5,
        ndcg_at_5=metrics.ndcg_at_5,
        mrr_at_5=metrics.mrr_at_5,
        empty_result_accuracy=metrics.empty_result_accuracy,
        context_reduction_rate=context.context_reduction_rate,
        p95_latency_ms=metrics.p95_latency_ms,
        evidence_location_completeness=metrics.evidence_location_completeness,
    )


def _validate_fixed_dataset_case_ids(
    bm25: RAGBaselineSummary,
    vector: VectorBaselineSummary,
    hybrid: HybridBaselineSummary,
) -> None:
    if bm25.case_ids != vector.case_ids or bm25.case_ids != hybrid.case_ids:
        raise RAGOptimizationError(
            "BM25、Vector 和 Hybrid 必须使用相同且同序的 case IDs"
        )


def _validate_evaluation_group(
    evaluations: Sequence[StrategyEvaluation],
    *,
    expected: set[RetrievalStrategy],
    label: str,
) -> None:
    if {item.strategy for item in evaluations} != expected:
        raise ValueError(f"{label}策略集合不完整或存在重复")
    first = evaluations[0]
    if any(
        item.case_ids != first.case_ids or item.dataset_scope != first.dataset_scope
        for item in evaluations[1:]
    ):
        raise ValueError(f"{label}必须使用相同 case IDs 和 dataset_scope")


def _global_gate_failures(evaluation: StrategyEvaluation) -> list[str]:
    checks = (
        (evaluation.evidence_hit_rate < MIN_HIT_RATE, "Hit@5 未达到 80%"),
        (evaluation.recall_at_5 < MIN_RECALL_AT_5, "Recall@5 未达到 80%"),
        (
            evaluation.empty_result_accuracy < MIN_EMPTY_RESULT_ACCURACY,
            "Empty Result Accuracy 未达到 100%",
        ),
        (
            evaluation.evidence_location_completeness < MIN_LOCATION_COMPLETENESS,
            "Evidence Location Completeness 未达到 95%",
        ),
        (
            evaluation.context_reduction_rate < MIN_CONTEXT_REDUCTION_RATE,
            "Context Reduction 未达到 40%",
        ),
        (
            evaluation.p95_latency_ms >= MAX_GLOBAL_RETRIEVAL_P95_MS,
            "Retrieval p95 未低于 800 ms",
        ),
    )
    return [reason for failed, reason in checks if failed]


def _strategy_row(item: StrategyEvaluation) -> str:
    return (
        f"| {item.strategy.value} | {len(item.case_ids)} | "
        f"{_percent(item.evidence_hit_rate)} | {_percent(item.precision_at_5)} | "
        f"{_percent(item.recall_at_5)} | {_percent(item.ndcg_at_5)} | "
        f"{_percent(item.mrr_at_5)} | {_percent(item.empty_result_accuracy)} | "
        f"{_percent(item.context_reduction_rate)} | {item.p95_latency_ms:.2f} ms | "
        f"{_percent(item.evidence_location_completeness)} |"
    )


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _render_frequency(values: dict[str, int]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{case_id}`={count}" for case_id, count in values.items())


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise RAGOptimizationError("无法计算空延迟集合的百分位")
    ordered = sorted(values)
    rank = max(1, ceil(percentile * len(ordered)))
    return ordered[rank - 1]
