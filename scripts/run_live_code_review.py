import os
import subprocess
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from devagent.eval import (
    LiveCodeReviewRun,
    LiveReviewExpectedFinding,
    evaluate_live_code_review,
    render_live_code_review_report,
    run_live_code_review,
)
from devagent.llm import create_openai_llm_client
from devagent.review import (
    ReviewCategory,
    ReviewLineSide,
    ReviewSeverity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_REF = "7229c86^"
DEFAULT_HEAD_REF = "7229c86"
DEFAULT_WORKSPACE = PROJECT_ROOT / "examples" / "sample_repo"
DEFAULT_WORKSPACE_LABEL = "examples/sample_repo"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "code_review_live.md"
DEFAULT_EXPECTED_FINDING = LiveReviewExpectedFinding(
    category=ReviewCategory.CORRECTNESS,
    severities=[
        ReviewSeverity.MEDIUM,
        ReviewSeverity.HIGH,
        ReviewSeverity.CRITICAL,
    ],
    file_path="src/sample_app/uploader.py",
    line=24,
    side=ReviewLineSide.HEAD,
    keywords=["build_upload_timeout", "min_timeout_seconds"],
)


def main() -> None:
    parser = ArgumentParser(
        description="显式调用真实 LLM provider 执行固定 Local Code Review 验收"
    )
    parser.add_argument("--base-ref", default=DEFAULT_BASE_REF)
    parser.add_argument("--head-ref", default=DEFAULT_HEAD_REF)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument(
        "--input-json",
        type=Path,
        help="不调用网络，重新渲染已有的脱敏 live JSON",
    )
    args = parser.parse_args()

    if args.input_json is not None:
        run = LiveCodeReviewRun.model_validate_json(
            args.input_json.expanduser().resolve().read_text(encoding="utf-8")
        )
        run = run.model_copy(
            update={
                "expected_finding": DEFAULT_EXPECTED_FINDING,
                "metrics": evaluate_live_code_review(
                    run.report,
                    DEFAULT_EXPECTED_FINDING,
                ),
            }
        )
    else:
        settings = _load_live_settings()

        def client_factory():
            return create_openai_llm_client(
                api_key=settings["api_key"],
                model=settings["model"],
                base_url=settings["base_url"],
                api_mode=settings["api_mode"],
                response_format={"type": "json_object"},
                reasoning_effort=settings["reasoning_effort"],
                max_tokens=8_192,
            )

        workspace = args.workspace.expanduser().resolve()
        run = run_live_code_review(
            llm_client_factory=client_factory,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            workspace=workspace,
            workspace_label=_workspace_label(workspace),
            provider="openai-compatible-live",
            model=settings["model"],
            api_mode=settings["api_mode"],
            expected_finding=DEFAULT_EXPECTED_FINDING,
            max_attempts=args.max_attempts,
        )

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_live_code_review_report(
        run,
        generated_at=datetime.now(UTC).isoformat(),
        commit_id=_current_revision(),
    )
    output.write_text(markdown, encoding="utf-8")
    json_output = output.with_suffix(".json")
    json_output.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    print(f"Live Code Review report 已生成: {output}")
    print(f"Live Code Review raw result 已生成: {json_output}")
    print(
        "端到端验收: "
        f"{'PASS' if run.metrics.passed else 'FAIL'}；"
        f"延迟 {run.latency_ms:.2f} ms；"
        f"模型尝试 {run.attempt_count} 次"
    )
    if not run.metrics.passed:
        raise SystemExit(1)


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


def _workspace_label(workspace: Path) -> str:
    try:
        return workspace.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return workspace.name


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
