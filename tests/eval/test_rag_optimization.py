import pytest
from pydantic import ValidationError

from devagent.agent import AgentRunStatus
from devagent.eval import (
    BusinessRAGAcceptance,
    LiveRAGEvalRun,
    LiveRAGMetrics,
    LiveRAGPrediction,
    RAGOptimizationError,
    RAGOptimizationSummary,
    RetrievalStrategy,
    StrategyDecision,
    StrategyEvaluation,
    aggregate_live_rag_stability,
    decide_retrieval_strategies,
    render_rag_optimization_report,
)


def make_strategy(
    strategy: RetrievalStrategy,
    *,
    scope: str = "fixed:2",
    empty_accuracy: float = 1,
    p95_latency_ms: float = 10,
    ndcg: float = 1,
    mrr: float = 1,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy=strategy,
        case_ids=["positive", "negative"],
        dataset_scope=scope,
        evidence_hit_rate=1,
        precision_at_5=0.2,
        recall_at_5=1,
        ndcg_at_5=ndcg,
        mrr_at_5=mrr,
        empty_result_accuracy=empty_accuracy,
        context_reduction_rate=0.75,
        p95_latency_ms=p95_latency_ms,
        evidence_location_completeness=1,
    )


def make_business(*, passed: bool = True) -> BusinessRAGAcceptance:
    return BusinessRAGAcceptance(
        passed=passed,
        case_count=3,
        knowledge_reference_case_count=3,
        average_context_reduction_rate=0.45,
        locator_completeness_rate=1,
        domain_flow_availability_rate=1,
    )


def make_live_run(
    *,
    success_rate: float,
    failed_case_ids: list[str],
    latencies: tuple[float, float],
    attempts: tuple[int, int] = (1, 1),
    model: str = "model-a",
) -> LiveRAGEvalRun:
    predictions = [
        LiveRAGPrediction(
            case_id=case_id,
            run_success=True,
            run_status=AgentRunStatus.SUCCESS,
            tool_called=True,
            tool_success=False,
            latency_ms=latency,
            steps=1,
            tool_call_count=1,
            attempt_count=attempt,
        )
        for case_id, latency, attempt in zip(
            ("positive", "negative"), latencies, attempts, strict=True
        )
    ]
    metrics = LiveRAGMetrics(
        case_count=2,
        positive_case_count=1,
        negative_case_count=1,
        valid_answer_count=2,
        tool_hit_count=2,
        tool_success_count=2,
        evidence_hit_count=1,
        matched_answer_keyword_count=1,
        expected_answer_keyword_count=1,
        expected_path_citation_count=1,
        grounded_citation_count=1,
        returned_citation_count=1,
        correct_abstention_count=1,
        end_to_end_success_count=round(success_rate * 2),
        valid_answer_rate=1,
        tool_hit_rate=1,
        tool_success_rate=1,
        evidence_hit_rate=1,
        answer_keyword_hit_rate=1,
        expected_path_citation_rate=1,
        grounded_citation_rate=1,
        abstention_accuracy=1,
        end_to_end_success_rate=success_rate,
        average_latency_ms=sum(latencies) / 2,
        p95_latency_ms=max(latencies),
        failed_case_ids=failed_case_ids,
        failure_reasons={case_id: ["test_failure"] for case_id in failed_case_ids},
    )
    return LiveRAGEvalRun(
        provider="provider-a",
        model=model,
        api_mode="responses",
        metrics=metrics,
        predictions=predictions,
    )


def test_decision_applies_hard_gates_before_soft_ranking() -> None:
    fixed = [
        make_strategy(RetrievalStrategy.BM25),
        make_strategy(RetrievalStrategy.VECTOR, empty_accuracy=0),
        make_strategy(RetrievalStrategy.HYBRID, empty_accuracy=0),
    ]
    rerank = [
        make_strategy(
            RetrievalStrategy.HYBRID,
            scope="rerank:2",
            empty_accuracy=0,
            ndcg=0.8,
            mrr=0.8,
        ),
        make_strategy(
            RetrievalStrategy.HYBRID_RERANK,
            scope="rerank:2",
            empty_accuracy=0,
            p95_latency_ms=17_000,
        ),
    ]

    decision = decide_retrieval_strategies(
        fixed_evaluations=fixed,
        rerank_evaluations=rerank,
        business_acceptance=make_business(),
    )

    assert decision.global_agent_default == RetrievalStrategy.BM25
    assert decision.domain_anchored_default == RetrievalStrategy.HYBRID
    assert decision.high_value_rerank == RetrievalStrategy.HYBRID_RERANK
    assert "Empty Result Accuracy" in " ".join(
        decision.rejected_global_defaults[RetrievalStrategy.HYBRID]
    )
    assert "800 ms" in " ".join(
        decision.rejected_global_defaults[RetrievalStrategy.HYBRID_RERANK]
    )


def test_live_stability_aggregates_worst_values_latency_and_failures() -> None:
    runs = [
        make_live_run(
            success_rate=0.5,
            failed_case_ids=["positive"],
            latencies=(10, 20),
        ),
        make_live_run(
            success_rate=0,
            failed_case_ids=["positive", "negative"],
            latencies=(30, 40),
            attempts=(1, 2),
        ),
    ]

    stability = aggregate_live_rag_stability(runs)

    assert stability.run_count == 2
    assert stability.mean_end_to_end_success_rate == 0.25
    assert stability.minimum_end_to_end_success_rate == 0
    assert stability.aggregate_p95_latency_ms == 40
    assert stability.total_attempt_count == 5
    assert stability.failed_case_frequency == {"negative": 1, "positive": 2}


def test_live_stability_rejects_one_run_or_mixed_configuration() -> None:
    run = make_live_run(
        success_rate=1,
        failed_case_ids=[],
        latencies=(10, 20),
    )
    with pytest.raises(RAGOptimizationError, match="至少需要两次"):
        aggregate_live_rag_stability([run])
    with pytest.raises(RAGOptimizationError, match="同一 provider"):
        aggregate_live_rag_stability(
            [
                run,
                make_live_run(
                    success_rate=1,
                    failed_case_ids=[],
                    latencies=(10, 20),
                    model="model-b",
                ),
            ]
        )


def test_models_reject_duplicate_ids_and_empty_decision_reasons() -> None:
    payload = make_strategy(RetrievalStrategy.BM25).model_dump()
    payload["case_ids"] = ["same", "same"]
    with pytest.raises(ValidationError, match="不能重复"):
        StrategyEvaluation.model_validate(payload)

    with pytest.raises(ValidationError, match="理由不能为空"):
        StrategyDecision(
            global_agent_default=RetrievalStrategy.BM25,
            domain_anchored_default=RetrievalStrategy.BM25,
            high_value_rerank=RetrievalStrategy.BM25,
            reasons=[""],
            rejected_global_defaults={},
        )


def test_summary_rejects_mixed_fixed_dataset_scope() -> None:
    fixed = [
        make_strategy(RetrievalStrategy.BM25),
        make_strategy(RetrievalStrategy.VECTOR),
        make_strategy(RetrievalStrategy.HYBRID, scope="different:2"),
    ]
    rerank = [
        make_strategy(RetrievalStrategy.HYBRID, scope="rerank:2"),
        make_strategy(RetrievalStrategy.HYBRID_RERANK, scope="rerank:2"),
    ]
    decision = decide_retrieval_strategies(
        fixed_evaluations=fixed,
        rerank_evaluations=rerank,
        business_acceptance=make_business(),
    )
    stability = aggregate_live_rag_stability(
        [
            make_live_run(success_rate=1, failed_case_ids=[], latencies=(10, 20)),
            make_live_run(success_rate=1, failed_case_ids=[], latencies=(15, 25)),
        ]
    )

    with pytest.raises(ValidationError, match="相同 case IDs 和 dataset_scope"):
        RAGOptimizationSummary(
            generated_at="2026-08-04T00:00:00Z",
            revision="abc123",
            fixed_dataset_evaluations=fixed,
            rerank_subset_evaluations=rerank,
            business_acceptance=make_business(),
            live_stability=stability,
            decision=decision,
            evaluation_boundaries=["boundary"],
        )


def test_report_renders_metrics_decision_and_boundaries() -> None:
    fixed = [
        make_strategy(RetrievalStrategy.BM25),
        make_strategy(RetrievalStrategy.VECTOR, empty_accuracy=0),
        make_strategy(RetrievalStrategy.HYBRID, empty_accuracy=0),
    ]
    rerank = [
        make_strategy(RetrievalStrategy.HYBRID, scope="rerank:2"),
        make_strategy(
            RetrievalStrategy.HYBRID_RERANK,
            scope="rerank:2",
            p95_latency_ms=17_000,
        ),
    ]
    decision = decide_retrieval_strategies(
        fixed_evaluations=fixed,
        rerank_evaluations=rerank,
        business_acceptance=make_business(),
    )
    stability = aggregate_live_rag_stability(
        [
            make_live_run(success_rate=1, failed_case_ids=[], latencies=(10, 20)),
            make_live_run(success_rate=1, failed_case_ids=[], latencies=(15, 25)),
        ]
    )
    summary = RAGOptimizationSummary(
        generated_at="2026-08-04T00:00:00Z",
        revision="abc123",
        fixed_dataset_evaluations=fixed,
        rerank_subset_evaluations=rerank,
        business_acceptance=make_business(),
        live_stability=stability,
        decision=decision,
        evaluation_boundaries=["路径级判断不是 chunk 级完整标注"],
    )

    report = render_rag_optimization_report(summary)

    assert "Precision@5" in report
    assert "NDCG@5" in report
    assert "Open Agent default: `bm25`" in report
    assert "Domain-anchored default: `hybrid_rrf`" in report
    assert "路径级判断不是 chunk 级完整标注" in report
