from pathlib import Path

from devagent.eval import (
    HybridBaselineSummary,
    LiveRAGEvalRun,
    RAGBaselineSummary,
    RerankBaselineSummary,
    RetrievalStrategy,
    VectorBaselineSummary,
    build_rag_optimization_summary,
)
from scripts.generate_rag_optimization import (
    DEFAULT_OUTPUT,
    PROJECT_ROOT,
    _load_business_acceptance,
    _load_model,
)

REPORT_DIR = PROJECT_ROOT / "eval" / "reports"


def test_persisted_summaries_rebuild_week_9_strategy_decision() -> None:
    summary = build_rag_optimization_summary(
        bm25=_load_model(REPORT_DIR / "rag_bm25_baseline.json", RAGBaselineSummary),
        vector=_load_model(
            REPORT_DIR / "rag_vector_baseline.json", VectorBaselineSummary
        ),
        hybrid=_load_model(
            REPORT_DIR / "rag_hybrid_baseline.json", HybridBaselineSummary
        ),
        rerank=_load_model(REPORT_DIR / "rag_rerank_live.json", RerankBaselineSummary),
        business_acceptance=_load_business_acceptance(
            REPORT_DIR / "rag_business_live.json"
        ),
        live_runs=[
            _load_model(REPORT_DIR / "rag_live_provider.json", LiveRAGEvalRun),
            _load_model(REPORT_DIR / "rag_live_provider_run2.json", LiveRAGEvalRun),
        ],
        generated_at="2026-08-04T00:00:00Z",
        revision="test-revision",
    )

    assert len(summary.fixed_dataset_evaluations[0].case_ids) == 36
    assert summary.decision.global_agent_default == RetrievalStrategy.BM25
    assert summary.decision.domain_anchored_default == RetrievalStrategy.HYBRID
    assert summary.decision.high_value_rerank == RetrievalStrategy.HYBRID_RERANK
    assert summary.live_stability.run_count == 2


def test_default_output_is_inside_project_reports() -> None:
    assert DEFAULT_OUTPUT == PROJECT_ROOT / "eval" / "reports" / "rag_optimization.md"
    assert isinstance(DEFAULT_OUTPUT, Path)
