from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
import subprocess

from devagent.eval import (
    evaluate_review_cases,
    load_review_eval_cases,
    render_review_baseline_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = PROJECT_ROOT / "eval" / "cases" / "code_review"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "code_review_baseline.md"


def main() -> None:
    parser = ArgumentParser(description="生成固定 Code Review Evaluation baseline")
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = load_review_eval_cases(args.case_dir)
    metrics = evaluate_review_cases(cases)
    report = render_review_baseline_report(
        metrics,
        commit_id=_current_revision(),
        generated_at=datetime.now(UTC).isoformat(),
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Review baseline 已生成: {output}")


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
