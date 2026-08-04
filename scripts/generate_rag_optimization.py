import json
import subprocess
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path

from devagent.eval import (
    BusinessRAGAcceptance,
    HybridBaselineSummary,
    LiveRAGEvalRun,
    RAGBaselineSummary,
    RAGOptimizationError,
    RerankBaselineSummary,
    VectorBaselineSummary,
    build_rag_optimization_summary,
    render_rag_optimization_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "eval" / "reports"
DEFAULT_OUTPUT = REPORT_DIR / "rag_optimization.md"


def main() -> None:
    parser = ArgumentParser(description="汇总 RAG 策略指标并生成第 9 周决策报告")
    parser.add_argument(
        "--bm25", type=Path, default=REPORT_DIR / "rag_bm25_baseline.json"
    )
    parser.add_argument(
        "--vector", type=Path, default=REPORT_DIR / "rag_vector_baseline.json"
    )
    parser.add_argument(
        "--hybrid", type=Path, default=REPORT_DIR / "rag_hybrid_baseline.json"
    )
    parser.add_argument(
        "--rerank", type=Path, default=REPORT_DIR / "rag_rerank_live.json"
    )
    parser.add_argument(
        "--business", type=Path, default=REPORT_DIR / "rag_business_live.json"
    )
    parser.add_argument("--live-run", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    live_paths = args.live_run or sorted(REPORT_DIR.glob("rag_live_provider*.json"))
    try:
        summary = build_rag_optimization_summary(
            bm25=_load_model(args.bm25, RAGBaselineSummary),
            vector=_load_model(args.vector, VectorBaselineSummary),
            hybrid=_load_model(args.hybrid, HybridBaselineSummary),
            rerank=_load_model(args.rerank, RerankBaselineSummary),
            business_acceptance=_load_business_acceptance(args.business),
            live_runs=[_load_model(path, LiveRAGEvalRun) for path in live_paths],
            generated_at=datetime.now(UTC).isoformat(),
            revision=_current_revision(),
        )
    except (OSError, ValueError, RAGOptimizationError) as exc:
        raise SystemExit(f"RAG optimization 生成失败: {exc}") from None

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_rag_optimization_report(summary), encoding="utf-8")
    json_output = output.with_suffix(".json")
    json_output.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    print(f"RAG optimization report 已生成: {output}")
    print(f"RAG optimization summary 已生成: {json_output}")


def _load_model(path: Path, model_type):
    resolved = path.expanduser().resolve()
    return model_type.model_validate_json(resolved.read_text(encoding="utf-8"))


def _load_business_acceptance(path: Path) -> BusinessRAGAcceptance:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    workflows = payload["workflows"]
    context = payload["context"]
    return BusinessRAGAcceptance(
        passed=payload["passed"],
        case_count=len(workflows),
        knowledge_reference_case_count=payload["knowledge_reference_case_count"],
        average_context_reduction_rate=context["average_reduction_rate"],
        locator_completeness_rate=context["locator_completeness_rate"],
        domain_flow_availability_rate=context["domain_flow_availability_rate"],
    )


def _current_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    revision = result.stdout.strip()
    if not revision:
        raise RuntimeError("无法读取 Git revision")
    return f"{revision} + working tree"


if __name__ == "__main__":
    main()
