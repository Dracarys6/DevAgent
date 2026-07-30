from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
import subprocess

from devagent.eval import (
    evaluate_rag_context,
    load_rag_eval_cases,
    render_rag_baseline_report,
    run_rag_eval,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = PROJECT_ROOT / "eval" / "cases" / "rag"
DEFAULT_WORKSPACE = DEFAULT_CASE_DIR / "workspace"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "rag_baseline.md"


def main() -> None:
    parser = ArgumentParser(description="生成固定 RAG Evaluation baseline")
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = load_rag_eval_cases(args.case_dir)
    run = run_rag_eval(cases, workspace=args.workspace)
    context_metrics = evaluate_rag_context(
        cases,
        run.predictions,
        workspace=args.workspace,
    )
    report = render_rag_baseline_report(
        run=run,
        context_metrics=context_metrics,
        commit_id=_current_revision(),
        generated_at=datetime.now(UTC).isoformat(),
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"RAG baseline 已生成: {output}")


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
