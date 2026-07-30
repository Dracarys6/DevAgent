import os
import subprocess
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from devagent.eval import (
    LiveRAGEvalRun,
    RAGEvalCase,
    evaluate_live_rag_predictions,
    load_rag_eval_cases,
    render_live_rag_report,
    run_live_rag_agent_eval,
)
from devagent.llm import create_openai_llm_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = PROJECT_ROOT / "eval" / "cases" / "rag"
DEFAULT_WORKSPACE = DEFAULT_CASE_DIR / "workspace"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "rag_live_provider.md"
DEFAULT_LIVE_CASE_IDS = (
    "event-bus-publish",
    "ci-upload-timeout",
    "log-upload-timeout",
    "diagnosis-evidence-binding",
    "review-diff-location",
    "bm25-ranking",
    "negative-payment-billing",
    "negative-kubernetes-deployment",
)


def main() -> None:
    parser = ArgumentParser(
        description="显式调用真实 LLM provider 执行 RAG Agent Evaluation"
    )
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--all-cases", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument(
        "--input-json",
        type=Path,
        help="不调用网络，重新评分已有的脱敏 live JSON",
    )
    args = parser.parse_args()

    all_cases = load_rag_eval_cases(args.case_dir)
    if args.input_json is not None:
        if args.case_id or args.all_cases:
            raise SystemExit("--input-json 不能与 --case-id 或 --all-cases 同时使用")
        input_path = args.input_json.expanduser().resolve()
        run = LiveRAGEvalRun.model_validate_json(input_path.read_text(encoding="utf-8"))
        cases = _select_cases(
            all_cases,
            requested_case_ids=[prediction.case_id for prediction in run.predictions],
            all_cases=False,
        )
        run = run.model_copy(
            update={"metrics": evaluate_live_rag_predictions(cases, run.predictions)}
        )
    else:
        settings = _load_live_settings()
        cases = _select_cases(
            all_cases,
            requested_case_ids=args.case_id,
            all_cases=args.all_cases,
        )

        def client_factory(tools):
            return create_openai_llm_client(
                api_key=settings["api_key"],
                model=settings["model"],
                tools=tools,
                base_url=settings["base_url"],
                api_mode=settings["api_mode"],
                response_format={"type": "json_object"},
                reasoning_effort=settings["reasoning_effort"],
                max_tokens=4_096,
            )

        run = run_live_rag_agent_eval(
            cases,
            workspace=args.workspace,
            llm_client_factory=client_factory,
            provider="openai-compatible-live",
            model=settings["model"],
            api_mode=settings["api_mode"],
            max_attempts=args.max_attempts,
        )
    generated_at = datetime.now(UTC).isoformat()
    revision = _current_revision()
    markdown = render_live_rag_report(
        run,
        generated_at=generated_at,
        commit_id=revision,
    )

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    json_output = output.with_suffix(".json")
    json_output.write_text(
        run.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"Live RAG report 已生成: {output}")
    print(f"Live RAG raw result 已生成: {json_output}")
    print(
        "端到端成功率: "
        f"{run.metrics.end_to_end_success_rate * 100:.1f}% "
        f"({run.metrics.end_to_end_success_count}/{run.metrics.case_count})"
    )


def _load_live_settings() -> dict[str, str | None]:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
    if os.getenv("DEVAGENT_ENABLE_LIVE_EVAL") != "1":
        raise SystemExit("真实模型评测未启用；请显式设置 DEVAGENT_ENABLE_LIVE_EVAL=1")

    api_key = os.getenv("DEVAGENT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("DEVAGENT_LLM_MODEL")
    if not api_key:
        raise SystemExit("真实模型评测缺少 DEVAGENT_LLM_API_KEY")
    if not model:
        raise SystemExit("真实模型评测缺少 DEVAGENT_LLM_MODEL")
    return {
        "api_key": api_key,
        "model": model,
        "base_url": os.getenv("DEVAGENT_LLM_BASE_URL") or None,
        "api_mode": os.getenv("DEVAGENT_LLM_API_MODE", "chat_completions"),
        "reasoning_effort": os.getenv("DEVAGENT_LLM_REASONING_EFFORT") or None,
    }


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
        raise SystemExit("Live RAG case_id 不能重复")

    case_by_id = {case.case_id: case for case in cases}
    unknown = [case_id for case_id in selected_ids if case_id not in case_by_id]
    if unknown:
        raise SystemExit(f"未知 Live RAG case: {', '.join(unknown)}")
    selected = [case_by_id[case_id] for case_id in selected_ids]
    if not any(not case.expect_empty for case in selected):
        raise SystemExit("Live RAG case 必须包含正样本")
    if not any(case.expect_empty for case in selected):
        raise SystemExit("Live RAG case 必须包含负样本")
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
