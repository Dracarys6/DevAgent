import subprocess
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path

from openai import OpenAI

from devagent.eval import (
    HybridBaselineError,
    load_live_embedding_settings,
    load_rag_eval_cases,
    render_hybrid_baseline_report,
    run_hybrid_baseline,
    summarize_hybrid_baseline_run,
)
from devagent.memory import (
    HybridRetrieverConfig,
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = PROJECT_ROOT / "eval" / "cases" / "rag"
DEFAULT_WORKSPACE = DEFAULT_CASE_DIR / "workspace"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "rag_hybrid_baseline.md"


def main() -> None:
    parser = ArgumentParser(
        description="显式调用真实 embedding provider 生成 Hybrid RAG baseline"
    )
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--keyword-weight", type=float, default=1.0)
    parser.add_argument("--vector-weight", type=float, default=1.0)
    args = parser.parse_args()

    settings = load_live_embedding_settings(PROJECT_ROOT)
    client = OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=30.0,
        max_retries=1,
    )
    provider = OpenAIEmbeddingProvider(
        client=client,
        config=OpenAIEmbeddingConfig(
            model=settings.model,
            batch_size=(
                settings.batch_size if args.batch_size is None else args.batch_size
            ),
            dimensions=settings.dimensions,
        ),
    )
    hybrid_config = HybridRetrieverConfig(
        candidate_k=args.candidate_k,
        rrf_k=args.rrf_k,
        keyword_weight=args.keyword_weight,
        vector_weight=args.vector_weight,
    )
    cases = load_rag_eval_cases(args.case_dir)
    try:
        run = run_hybrid_baseline(
            cases,
            workspace=args.workspace,
            embedding_provider=provider,
            hybrid_config=hybrid_config,
        )
    except HybridBaselineError as exc:
        raise SystemExit(f"Hybrid baseline 失败: {exc}") from None

    report = render_hybrid_baseline_report(
        run,
        generated_at=datetime.now(UTC).isoformat(),
        commit_id=_current_revision(),
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    json_output = output.with_suffix(".json")
    json_output.write_text(
        summarize_hybrid_baseline_run(run).model_dump_json(indent=2),
        encoding="utf-8",
    )

    metrics = run.hybrid_run.metrics
    print(f"Hybrid RAG baseline 已生成: {output}")
    print(f"Hybrid RAG summary 已生成: {json_output}")
    print(
        "真实 Hybrid 验收: PASS；"
        f"Hit@5 {metrics.evidence_hit_rate * 100:.1f}%；"
        f"MRR@5 {metrics.mrr_at_5 * 100:.1f}%；"
        f"Empty {metrics.empty_result_accuracy * 100:.1f}%；"
        f"query p95 {metrics.p95_latency_ms:.2f} ms"
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
