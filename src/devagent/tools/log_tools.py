import json
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError


TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
DEFAULT_LOG_DATA_DIR = Path("examples/sample_logs")
DEFAULT_MAX_LOG_ENTRIES = 50
MAX_LOG_ENTRIES = 200
DEFAULT_MAX_LOG_CHARS = 8_000
MAX_LOG_CHARS = 50_000
MIN_LOG_CHARS = 500


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogEntry(BaseModel):
    timestamp: datetime
    sequence_id: int = Field(ge=1)
    task_id: str = Field(min_length=1)
    level: LogLevel
    service: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class SearchLogError(Exception):
    """日志无法安全读取、校验或检索时抛出的异常。"""


class SearchLogArgs(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    level: LogLevel | None = None
    keyword: str | None = Field(default=None, max_length=200)
    data_dir: str = str(DEFAULT_LOG_DATA_DIR)
    max_entries: int = Field(
        default=DEFAULT_MAX_LOG_ENTRIES,
        ge=1,
        le=MAX_LOG_ENTRIES,
    )
    max_chars: int = Field(
        default=DEFAULT_MAX_LOG_CHARS,
        ge=MIN_LOG_CHARS,
        le=MAX_LOG_CHARS,
    )


def search_log(
    task_id: str,
    level: LogLevel | str | None = None,
    keyword: str | None = None,
    data_dir: str | Path = DEFAULT_LOG_DATA_DIR,
    max_entries: int = DEFAULT_MAX_LOG_ENTRIES,
    max_chars: int = DEFAULT_MAX_LOG_CHARS,
) -> str:
    """检索指定任务的结构化日志并返回大小受控的 JSON 证据。"""
    normalized_task_id = _validate_task_id(task_id)
    normalized_level = _normalize_level(level)
    normalized_keyword = _normalize_keyword(keyword)
    _validate_limits(max_entries, max_chars)

    path = _resolve_log_path(data_dir, normalized_task_id)
    entries = _load_log_entries(path, normalized_task_id)
    _validate_unique_sequence_ids(entries)
    entries.sort(key=lambda entry: (entry.timestamp, entry.sequence_id))

    first_anomaly = _find_first_anomaly(entries)
    matches = [
        entry
        for entry in entries
        if _matches(entry, normalized_level, normalized_keyword)
    ]

    return _serialize_search_result(
        task_id=normalized_task_id,
        level=normalized_level,
        keyword=normalized_keyword,
        entries=entries,
        matches=matches,
        first_anomaly=first_anomaly,
        max_entries=max_entries,
        max_chars=max_chars,
    )


def _validate_task_id(task_id: str) -> str:
    normalized = task_id.strip()
    if not TASK_ID_PATTERN.fullmatch(normalized):
        raise SearchLogError("task_id 只能包含字母、数字、下划线和连字符")
    return normalized


def _resolve_log_path(data_dir: str | Path, task_id: str) -> Path:
    root = Path(data_dir).resolve()
    if not root.exists():
        raise SearchLogError(f"日志数据目录不存在: {root}")
    if not root.is_dir():
        raise SearchLogError(f"日志数据路径不是目录: {root}")

    target = (root / f"{task_id}.jsonl").resolve()
    if not target.is_relative_to(root):
        raise SearchLogError("日志数据文件位于 data_dir 之外")
    if not target.exists():
        raise SearchLogError(f"未找到 task_id 对应的日志数据文件: {task_id}")
    if not target.is_file():
        raise SearchLogError(f"日志数据路径不是文件: {target}")
    return target


def _load_log_entries(path: Path, expected_task_id: str) -> list[LogEntry]:
    """逐行加载日志，并保留损坏数据所在的行号。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SearchLogError(f"日志数据文件不是有效的 UTF-8 文本: {path}") from exc

    entries: list[LogEntry] = []
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            entry = LogEntry.model_validate_json(raw_line)
        except ValidationError as exc:
            raise SearchLogError(
                f"日志第 {line_number} 行格式校验失败: {path}"
            ) from exc
        if entry.task_id != expected_task_id:
            raise SearchLogError(
                f"日志第 {line_number} 行 task_id 与请求不匹配: "
                f"{entry.task_id} != {expected_task_id}"
            )
        entries.append(entry)
    return entries


def _normalize_level(level: LogLevel | str | None) -> LogLevel | None:
    if level is None:
        return None
    if isinstance(level, LogLevel):
        return level
    if not isinstance(level, str):
        raise SearchLogError(f"level 必须是有效的日志级别: {level}")
    try:
        return LogLevel(level.strip().upper())
    except ValueError as exc:
        raise SearchLogError(f"level 必须是有效的日志级别: {level}") from exc


def _normalize_keyword(keyword: str | None) -> str | None:
    if keyword is None:
        return None
    normalized = keyword.strip()
    if not normalized:
        raise SearchLogError("keyword 不能为空字符串")
    return normalized


def _validate_limits(max_entries: int, max_chars: int) -> None:
    if not 1 <= max_entries <= MAX_LOG_ENTRIES:
        raise SearchLogError(
            f"max_entries 必须在 1 到 {MAX_LOG_ENTRIES} 之间"
        )
    if not MIN_LOG_CHARS <= max_chars <= MAX_LOG_CHARS:
        raise SearchLogError(
            f"max_chars 必须在 {MIN_LOG_CHARS} 到 {MAX_LOG_CHARS} 之间"
        )


def _validate_unique_sequence_ids(entries: list[LogEntry]) -> None:
    seen_sequence_ids: set[int] = set()
    for entry in entries:
        if entry.sequence_id in seen_sequence_ids:
            raise SearchLogError(f"日志中存在重复的 sequence_id: {entry.sequence_id}")
        seen_sequence_ids.add(entry.sequence_id)


def _find_first_anomaly(entries: list[LogEntry]) -> LogEntry | None:
    """返回完整时间线中首个 ERROR 或 CRITICAL 日志。"""
    return next(
        (
            entry
            for entry in entries
            if entry.level in {LogLevel.ERROR, LogLevel.CRITICAL}
        ),
        None,
    )


def _matches(entry: LogEntry, level: LogLevel | None, keyword: str | None) -> bool:
    if level is not None and entry.level != level:
        return False
    if keyword is None:
        return True

    haystack = " ".join(
        [
            entry.message,
            entry.service,
            entry.source or "",
            json.dumps(entry.context, ensure_ascii=False, sort_keys=True),
        ]
    ).casefold()
    return keyword.casefold() in haystack


def _serialize_search_result(
    task_id: str,
    level: LogLevel | None,
    keyword: str | None,
    entries: list[LogEntry],
    matches: list[LogEntry],
    first_anomaly: LogEntry | None,
    max_entries: int,
    max_chars: int,
) -> str:
    limited_matches = matches[:max_entries]
    anomaly = _serialize_entry(first_anomaly) if first_anomaly is not None else None

    result = _build_result(
        task_id=task_id,
        level=level,
        keyword=keyword,
        total_count=len(entries),
        matched_count=len(matches),
        entries=[],
        first_anomaly=anomaly,
        truncated=bool(matches),
    )

    if len(_dump_json(result)) > max_chars and anomaly is not None:
        result["first_anomaly"] = _compact_entry(anomaly)
    if len(_dump_json(result)) > max_chars:
        raise SearchLogError("max_chars 太小，无法容纳最小日志结果")

    returned_entries: list[dict[str, Any]] = []
    for entry in limited_matches:
        candidate_entries = [*returned_entries, _serialize_entry(entry)]
        candidate = _build_result(
            task_id=task_id,
            level=level,
            keyword=keyword,
            total_count=len(entries),
            matched_count=len(matches),
            entries=candidate_entries,
            first_anomaly=result["first_anomaly"],
            truncated=(len(candidate_entries) < len(matches)),
        )
        if len(_dump_json(candidate)) > max_chars:
            break
        returned_entries = candidate_entries

    final_result = _build_result(
        task_id=task_id,
        level=level,
        keyword=keyword,
        total_count=len(entries),
        matched_count=len(matches),
        entries=returned_entries,
        first_anomaly=result["first_anomaly"],
        truncated=(len(returned_entries) < len(matches)),
    )
    content = _dump_json(final_result)
    if len(content) > max_chars:
        raise SearchLogError("max_chars 太小，无法容纳最小日志结果")
    return content


def _serialize_entry(entry: LogEntry) -> dict[str, Any]:
    return entry.model_dump(mode="json", exclude={"task_id"})


def _compact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    compact = dict(entry)
    compact["message"] = _truncate_text(str(compact["message"]), 120)
    compact["source"] = (
        _truncate_text(str(compact["source"]), 80)
        if compact["source"]
        else None
    )
    compact["context"] = {}
    return compact


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _build_result(
    *,
    task_id: str,
    level: LogLevel | None,
    keyword: str | None,
    total_count: int,
    matched_count: int,
    entries: list[dict[str, Any]],
    first_anomaly: dict[str, Any] | None,
    truncated: bool,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "filters": {
            "level": level.value if level is not None else None,
            "keyword": keyword,
        },
        "summary": {
            "total_entry_count": total_count,
            "matched_entry_count": matched_count,
            "returned_entry_count": len(entries),
            "truncated": truncated,
        },
        "first_anomaly": first_anomaly,
        "entries": entries,
    }


def _dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
