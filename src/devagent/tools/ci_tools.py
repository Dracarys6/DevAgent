import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

COMMIT_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{6,64}$")

DEFAULT_CI_DATA_DIR = Path("examples/sample_ci")
DEFAULT_CI_LOG_CHARS = 4_000
MAX_CI_LOG_CHARS = 20_000
CI_LOG_TRUNCATION_MARKER = "\n... CI 核心日志过长，已截断 ..."


CIStatus = Literal[
    "pending",
    "running",
    "passed",
    "failed",
    "cancelled",
]


class CITestCase(BaseModel):
    name: str = Field(min_length=1)
    status: CIStatus
    duration_seconds: float = Field(ge=0)
    error_type: str | None = None
    error_message: str | None = None
    location: str | None = None
    log_excerpt: list[str] = Field(default_factory=list)


class CIJob(BaseModel):
    name: str = Field(min_length=1)
    status: CIStatus
    duration_seconds: float = Field(ge=0)
    tests: list[CITestCase] = Field(default_factory=list)
    log_lines: list[str] = Field(default_factory=list)


class CIRun(BaseModel):
    pipeline_id: str = Field(min_length=1)
    commit_id: str = Field(min_length=1)
    status: CIStatus
    started_at: datetime
    finished_at: datetime
    jobs: list[CIJob] = Field(default_factory=list)


class CIResultError(Exception):
    """CI 结果无法安全读取或校验时抛出的异常。"""


class GetCIResultArgs(BaseModel):
    commit_id: str = Field(min_length=6, max_length=64)
    data_dir: str = str(DEFAULT_CI_DATA_DIR)
    max_log_chars: int = Field(
        default=DEFAULT_CI_LOG_CHARS,
        ge=1,
        le=MAX_CI_LOG_CHARS,
    )


def _validate_commit_id(commit_id: str) -> str:
    normalized = commit_id.strip()
    if not COMMIT_ID_PATTERN.fullmatch(normalized):
        raise CIResultError("commit_id 必须是 6 到 64 位十六进制字符")
    return normalized


def _validate_data_dir(data_dir: str | Path, commit_id: str) -> Path:
    root = Path(data_dir).resolve()
    if not root.exists():
        raise CIResultError(f"CI 数据目录不存在: {root}")
    if not root.is_dir():
        raise CIResultError(f"CI 数据路径不是目录: {root}")

    target = (root / f"{commit_id}.json").resolve()
    if not target.is_relative_to(root):
        raise CIResultError("CI 数据文件位于 data_dir 之外")
    if not target.exists():
        raise CIResultError(f"未找到 commit 对应的 CI 数据文件: {commit_id}")
    if not target.is_file():
        raise CIResultError(f"CI 数据路径不是文件: {target}")
    return target


def _truncate_text(context: str, max_chars: int) -> str:
    if len(context) <= max_chars:
        return context
    if max_chars <= len(CI_LOG_TRUNCATION_MARKER):
        return CI_LOG_TRUNCATION_MARKER[:max_chars]
    size = max_chars - len(CI_LOG_TRUNCATION_MARKER)
    return context[:size] + CI_LOG_TRUNCATION_MARKER


def _deduplicate_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line and line not in seen:
            seen.add(line)
            result.append(line)
    return result


def _build_failed_job(job: CIJob) -> tuple[dict[str, object], list[str], int]:
    failed_tests = [test for test in job.tests if test.status == "failed"]
    core_log_lines: list[str] = []
    test_summaries: list[dict[str, object]] = []

    for test in failed_tests:
        test_summaries.append(
            {
                "name": test.name,
                "error_type": test.error_type,
                "error_message": test.error_message,
                "location": test.location,
                "log_excerpt": test.log_excerpt,
            }
        )
        core_log_lines.extend(test.log_excerpt)

    core_log_lines.extend(job.log_lines)
    return (
        {
            "name": job.name,
            "status": job.status,
            "duration_seconds": job.duration_seconds,
            "failed_tests": test_summaries,
        },
        core_log_lines,
        len(failed_tests),
    )


def get_ci_result(
    commit_id: str,
    data_dir: str | Path = DEFAULT_CI_DATA_DIR,
    max_log_chars: int = DEFAULT_CI_LOG_CHARS,
) -> str:
    """读取并压缩指定 commit 的 CI 失败证据。"""
    if max_log_chars < 1:
        raise CIResultError("max_log_chars 必须大于或等于 1")
    if max_log_chars > MAX_CI_LOG_CHARS:
        raise CIResultError(f"max_log_chars 不能超过 {MAX_CI_LOG_CHARS}")

    normalized_commit_id = _validate_commit_id(commit_id)
    result_path = _validate_data_dir(data_dir, normalized_commit_id)

    try:
        raw_json = result_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CIResultError(f"CI 数据文件不是有效的 UTF-8 文本: {result_path}") from exc
    except PermissionError as exc:
        raise CIResultError(f"没有权限读取 CI 数据文件: {result_path}") from exc
    except OSError as exc:
        raise CIResultError(f"读取 CI 数据文件失败: {result_path}") from exc

    try:
        ci_run = CIRun.model_validate_json(raw_json)
    except ValidationError as exc:
        raise CIResultError(f"CI 数据格式校验失败: {result_path}") from exc

    if ci_run.commit_id != normalized_commit_id:
        raise CIResultError("CI 数据文件中的 commit_id 与请求的 commit_id 不匹配")

    failed_job_summaries: list[dict[str, object]] = []
    core_log_lines: list[str] = []
    failed_test_count = 0
    for job in ci_run.jobs:
        if job.status != "failed":
            continue
        job_summary, job_log_lines, job_failed_test_count = _build_failed_job(job)
        failed_job_summaries.append(job_summary)
        core_log_lines.extend(job_log_lines)
        failed_test_count += job_failed_test_count

    summary = {
        "pipeline_id": ci_run.pipeline_id,
        "commit_id": ci_run.commit_id,
        "status": ci_run.status,
        "summary": {
            "total_job_count": len(ci_run.jobs),
            "failed_job_count": len(failed_job_summaries),
            "failed_test_count": failed_test_count,
        },
        "failed_jobs": failed_job_summaries,
        "core_log": _truncate_text(
            "\n".join(_deduplicate_lines(core_log_lines)),
            max_log_chars,
        ),
    }
    return json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
