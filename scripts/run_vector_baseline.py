import os
import subprocess
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from openai import OpenAI

from devagent.eval import (
    VectorBaselineError,
    load_rag_eval_cases,
    render_vector_baseline_report,
    run_vector_baseline,
    summarize_vector_baseline_run,
)
from devagent.memory import OpenAIEmbeddingConfig, OpenAIEmbeddingProvider

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = PROJECT_ROOT / "eval" / "cases" / "rag"
DEFAULT_WORKSPACE = DEFAULT_CASE_DIR / "workspace"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "rag_vector_baseline.md"


@dataclass(frozen=True)
class LiveEmbeddingSettings:
    api_key: str
    model: str
    base_url: str
    dimensions: int | None
    batch_size: int


def main() -> None:
    parser = ArgumentParser(
        description="显式调用真实 embedding provider 生成向量检索 baseline"
    )
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int)
    args = parser.parse_args()

    settings = _load_live_settings()
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
    cases = load_rag_eval_cases(args.case_dir)
    try:
        run = run_vector_baseline(
            cases,
            workspace=args.workspace,
            embedding_provider=provider,
        )
    except VectorBaselineError as exc:
        raise SystemExit(f"向量 baseline 失败: {exc}") from None
    report = render_vector_baseline_report(
        run,
        generated_at=datetime.now(UTC).isoformat(),
        commit_id=_current_revision(),
    )

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    json_output = output.with_suffix(".json")
    json_output.write_text(
        summarize_vector_baseline_run(run).model_dump_json(indent=2),
        encoding="utf-8",
    )

    metrics = run.vector_run.metrics
    print(f"Vector RAG baseline 已生成: {output}")
    print(f"Vector RAG summary 已生成: {json_output}")
    print(
        "真实向量验收: PASS；"
        f"Hit@5 {metrics.evidence_hit_rate * 100:.1f}%；"
        f"MRR@5 {metrics.mrr_at_5 * 100:.1f}%；"
        f"query p95 {metrics.p95_latency_ms:.2f} ms"
    )


def _load_live_settings() -> LiveEmbeddingSettings:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
    if os.getenv("DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL") != "1":
        raise SystemExit(
            "真实 Embedding Evaluation 未启用；"
            "请显式设置 DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL=1"
        )

    api_key = os.getenv("DEVAGENT_EMBEDDING_API_KEY", "").strip()
    model = os.getenv("DEVAGENT_EMBEDDING_MODEL", "").strip()
    base_url = os.getenv("DEVAGENT_EMBEDDING_BASE_URL", "").strip()
    if not api_key:
        raise SystemExit("真实 Embedding Evaluation 缺少 DEVAGENT_EMBEDDING_API_KEY")
    if not model:
        raise SystemExit("真实 Embedding Evaluation 缺少 DEVAGENT_EMBEDDING_MODEL")
    if not base_url:
        raise SystemExit("真实 Embedding Evaluation 缺少 DEVAGENT_EMBEDDING_BASE_URL")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("DEVAGENT_EMBEDDING_BASE_URL 必须是 HTTP(S) API 根路径")
    if parsed.path.rstrip("/").endswith("/embeddings"):
        raise SystemExit(
            "DEVAGENT_EMBEDDING_BASE_URL 应为 API 根路径，不能包含 /embeddings"
        )

    dimensions_text = os.getenv("DEVAGENT_EMBEDDING_DIMENSIONS", "").strip()
    dimensions: int | None = None
    if dimensions_text:
        try:
            dimensions = int(dimensions_text)
        except ValueError as exc:
            raise SystemExit("DEVAGENT_EMBEDDING_DIMENSIONS 必须是正整数") from exc
        if dimensions < 1:
            raise SystemExit("DEVAGENT_EMBEDDING_DIMENSIONS 必须是正整数")
    batch_size_text = os.getenv("DEVAGENT_EMBEDDING_BATCH_SIZE", "10").strip()
    try:
        batch_size = int(batch_size_text)
    except ValueError as exc:
        raise SystemExit(
            "DEVAGENT_EMBEDDING_BATCH_SIZE 必须是 1 到 2048 的整数"
        ) from exc
    if not 1 <= batch_size <= 2_048:
        raise SystemExit("DEVAGENT_EMBEDDING_BATCH_SIZE 必须是 1 到 2048 的整数")
    return LiveEmbeddingSettings(
        api_key=api_key,
        model=model,
        base_url=base_url,
        dimensions=dimensions,
        batch_size=batch_size,
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
