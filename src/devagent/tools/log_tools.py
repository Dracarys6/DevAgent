import json
import re
from datetime import datetime
from enum import Enum
from typing import Any
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError

from .models import ErrorCode

TASK_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{6,64}$")
DEFAULT_LOG_DATA_DIR = "./examples/sample_logs"


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
    max_entries: int = Field(default=50, ge=1, le=200)
    max_chars: int = Field(default=8000, ge=500, le=50000)


def search_log(
    task_id: str,
    level: LogLevel | None = None,
    keyword: str | None = None,
    data_dir: str = DEFAULT_LOG_DATA_DIR,
    max_entries: int = 50,
    max_chars: int = 8000,
) -> list[LogEntry]:
    normalized_task_id = _validate_task_id(task_id)
    normalized_level = _normalize_level(level)
    normalized_keyword = _normalize_keyword(keyword)
    _validate_limits(max_entries, max_chars)

    path = _resolve_log_path(data_dir, normalized_task_id)
    entries = _load_log_entries(path, normalized_task_id)
    _validate_unique_sequence_ids(entries)
    entries.sort(key=lambda e: (e.timestamp, e.sequence_id))  # 排序 task 的 log 时间线

    first_anomaly = _find_first_anomaly(entries)
    matches = [
        entry
        for entry in entries
        if _matches(entry, normalized_level, normalized_keyword)
    ]

    return _serialize_search_result(
        task_id=normalized_task_id,
        level=normalized_level,
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
        raise SearchLogError(f"未找到 task_id 对应的 日志数据文件: {task_id}")
    if not target.is_file():
        raise SearchLogError(f"日志数据路径不是文件: {target}")
    return target


def _load_log_entries(path: Path, expected_task_id: str) -> list[LogEntry]:
    """加载对应 task_id 的日志条目"""
    entries: list[LogEntry] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            entry = LogEntry.model_validate_json(raw_line)
        except ValidationError as exc:
            raise SearchLogError(f"日志第 {line_number} 行格式校验失败: {exc}") from exc
        if entry.task_id != expected_task_id:
            raise SearchLogError(
                f"日志第 {line_number} 行 task_id 与请求不匹配: {entry.task_id} != {expected_task_id}"
            )
        entries.append(entry)
    return entries


def _normalize_level(level: LogLevel | None) -> LogLevel | None:
    if level is None:
        return None
    if not isinstance(level, LogLevel):
        raise SearchLogError(f"level 必须是 LogLevel 枚举值: {level}")
    return level


def _normalize_keyword(keyword: str | None) -> str | None:
    if keyword is None:
        return None
    normalized = keyword.strip()
    if not normalized:
        raise SearchLogError("keyword 不能为空字符串")
    return normalized


def _validate_limits(max_entries: int, max_chars: int) -> None:
    if max_entries < 1:
        raise SearchLogError("max_entries 必须大于或等于 1")
    if max_chars < 1:
        raise SearchLogError("max_chars 必须大于或等于 1")


def _validate_unique_sequence_ids(entries: list[LogEntry]) -> None:
    seen_sequence_ids = set()
    for entry in entries:
        if entry.sequence_id in seen_sequence_ids:
            raise SearchLogError(f"日志中存在重复的 sequence_id: {entry.sequence_id}")
        seen_sequence_ids.add(entry.sequence_id)


def _find_first_anomaly(entries: list[LogEntry]) -> LogEntry | None:
    """返回第一个 ERROR 或 CRITICAL 日志条目，若无则返回 None"""
    for entry in entries:
        if entry.level in {LogLevel.ERROR, LogLevel.CRITICAL}:
            return entry
    return None


def _matches(entry: LogEntry, level: LogLevel | None, keyword: str | None) -> bool:
    if level is not None and entry.level != level:
        return False
    if keyword is not None:
        haystack = " ".join(
            [
                entry.message,
                entry.service,
                entry.source or "",
                json.dumps(entry.context, ensure_ascii=False, sort_keys=True),
            ]
        ).casefold()
        if keyword.casefold() not in haystack:
            return False
    return True


def _serialize_search_result(
    task_id: str,
    level: LogLevel | None,
    entries: list[LogEntry],
    matches: list[LogEntry],
    first_anomaly: LogEntry | None,
    max_entries: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    """将匹配的日志条目序列化为字典，并截断到指定数量和字符数"""
    serialized = [entry.model_dump() for entry in matches[:max_entries]]
    serialized_str = json.dumps(serialized, ensure_ascii=False)
    if len(serialized_str) > max_chars:
        truncated_str = serialized_str[:max_chars] + "..."
        return json.loads(truncated_str)
    return serialized
