import os
import subprocess
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from devagent.eval import (
    RAGEvalCase,
    RerankBaselineError,
    load_live_embedding_settings,
    load_rag_eval_cases,
    render_rerank_baseline_report,
    run_rerank_baseline,
    summarize_rerank_baseline_run,
)
from devagent.llm import create_openai_llm_client
from devagent.memory import OpenAIEmbeddingConfig, OpenAIEmbeddingProvider
from devagent.memory.llm_reranker import LLMReranker, LLMRerankerConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = PROJECT_ROOT / "eval" / "cases" / "rag"
DEFAULT_WORKSPACE = DEFAULT_CASE_DIR / "workspace"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "rag_rerank_live.md"
DEFAULT_LIVE_CASE_IDS = (
    "github-inline-fallback",
    "event-bus-publish",
    "ci-upload-timeout",
    "log-upload-timeout",
    "diagnosis-evidence-binding",
    "review-diff-location",
    "negative-payment-billing",
    "negative-kubernetes-deployment",
)


@dataclass(frozen=True)
class LiveLLMSettings:
    api_key: str
    model: str
    base_url: str | None
    api_mode: str
    reasoning_effort: str | None


def main() -> None:
    parser = ArgumentParser(
        description="显式调用真实 Embedding 与 LLM provider 执行 RAG rerank 评测"
    )
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--all-cases", action="store_true")
    parser.add_argument("--candidate-k", type=int, default=10)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--llm-timeout", type=float, default=45.0)
    parser.add_argument("--llm-max-retries", type=int, default=0)
    args = parser.parse_args()

    # ! 两个显式开关都必须先通过，之后才能创建任何付费 provider client。
    embedding_settings = load_live_embedding_settings(PROJECT_ROOT)
    llm_settings = _load_live_llm_settings()
    cases = _select_cases(
        load_rag_eval_cases(args.case_dir),
        requested_case_ids=args.case_id,
        all_cases=args.all_cases,
    )

    embedding_client = OpenAI(
        api_key=embedding_settings.api_key,
        base_url=embedding_settings.base_url,
        timeout=30.0,
        max_retries=1,
    )
    embedding_provider = OpenAIEmbeddingProvider(
        client=embedding_client,
        config=OpenAIEmbeddingConfig(
            model=embedding_settings.model,
            batch_size=embedding_settings.batch_size,
            dimensions=embedding_settings.dimensions,
        ),
    )
    llm_client = create_openai_llm_client(
        api_key=llm_settings.api_key,
        model=llm_settings.model,
        tools=[],
        base_url=llm_settings.base_url,
        api_mode=llm_settings.api_mode,
        response_format={"type": "json_object"},
        reasoning_effort=llm_settings.reasoning_effort,
        max_tokens=2_048,
        timeout_seconds=args.llm_timeout,
        max_retries=args.llm_max_retries,
    )
    reranker = LLMReranker(
        llm_client=llm_client,
        config=LLMRerankerConfig(
            model_name=llm_settings.model,
            max_attempts=args.max_attempts,
            max_candidates=args.candidate_k,
        ),
    )
    try:
        run = run_rerank_baseline(
            cases,
            workspace=args.workspace,
            embedding_provider=embedding_provider,
            reranker=reranker,
            candidate_k=args.candidate_k,
        )
    except RerankBaselineError as exc:
        raise SystemExit(f"Rerank baseline 失败: {exc}") from None

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_rerank_baseline_report(
            run,
            generated_at=datetime.now(UTC).isoformat(),
            commit_id=_current_revision(),
        ),
        encoding="utf-8",
    )
    json_output = output.with_suffix(".json")
    json_output.write_text(
        summarize_rerank_baseline_run(run).model_dump_json(indent=2),
        encoding="utf-8",
    )

    before = run.before_run.metrics
    after = run.after_run.metrics
    successful_rerank_count = sum(
        item.rerank_status == "success" for item in run.observations
    )
    known_gap = next(
        (item for item in run.observations if item.case_id == "github-inline-fallback"),
        None,
    )
    passed = (
        run.metadata_completeness == 1
        and after.evidence_hit_rate >= before.evidence_hit_rate
        and after.mrr_at_5 >= before.mrr_at_5
        and successful_rerank_count > 0
        and (known_gap is None or known_gap.after_relevant_rank == 1)
    )
    availability = successful_rerank_count / run.query_count
    provider_status = "HEALTHY" if run.fallback_count == 0 else "DEGRADED"
    print(f"Live RAG rerank report 已生成: {output}")
    print(f"Live RAG rerank summary 已生成: {json_output}")
    print(
        f"真实 Rerank 链路验收: {'PASS' if passed else 'FAIL'}；"
        f"MRR@5 {before.mrr_at_5 * 100:.1f}% -> {after.mrr_at_5 * 100:.1f}%；"
        f"provider {provider_status} {availability * 100:.1f}%；"
        f"fallback {run.fallback_count}；"
        f"请求/修复 {run.reranker_request_count}/{run.reranker_repair_count}"
    )
    if not passed:
        raise SystemExit(1)


def _load_live_llm_settings() -> LiveLLMSettings:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
    if os.getenv("DEVAGENT_ENABLE_LIVE_EVAL") != "1":
        raise SystemExit(
            "真实 LLM Evaluation 未启用；请显式设置 DEVAGENT_ENABLE_LIVE_EVAL=1"
        )
    api_key = (os.getenv("DEVAGENT_LLM_API_KEY") or "").strip()
    model = (os.getenv("DEVAGENT_LLM_MODEL") or "").strip()
    if not api_key:
        raise SystemExit("真实 LLM Evaluation 缺少 DEVAGENT_LLM_API_KEY")
    if not model:
        raise SystemExit("真实 LLM Evaluation 缺少 DEVAGENT_LLM_MODEL")
    return LiveLLMSettings(
        api_key=api_key,
        model=model,
        base_url=(os.getenv("DEVAGENT_LLM_BASE_URL") or "").strip() or None,
        api_mode=(os.getenv("DEVAGENT_LLM_API_MODE") or "chat_completions").strip(),
        reasoning_effort=(
            (os.getenv("DEVAGENT_LLM_REASONING_EFFORT") or "").strip() or None
        ),
    )


def _select_cases(
    cases: list[RAGEvalCase],
    *,
    requested_case_ids: list[str],
    all_cases: bool,
) -> list[RAGEvalCase]:
    if all_cases and requested_case_ids:
        raise SystemExit("--all-cases 与 --case-id 不能同时使用")
    selected_ids = (
        [case.case_id for case in cases]
        if all_cases
        else requested_case_ids or list(DEFAULT_LIVE_CASE_IDS)
    )
    if len(selected_ids) != len(set(selected_ids)):
        raise SystemExit("Live Rerank case_id 不能重复")
    case_by_id = {case.case_id: case for case in cases}
    unknown = [case_id for case_id in selected_ids if case_id not in case_by_id]
    if unknown:
        raise SystemExit(f"未知 Live Rerank case: {', '.join(unknown)}")
    selected = [case_by_id[case_id] for case_id in selected_ids]
    if not any(not case.expect_empty for case in selected):
        raise SystemExit("Live Rerank case 必须包含正样本")
    if not any(case.expect_empty for case in selected):
        raise SystemExit("Live Rerank case 必须包含负样本")
    return selected


def _current_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return f"{result.stdout.strip()} + working tree"


if __name__ == "__main__":
    main()
