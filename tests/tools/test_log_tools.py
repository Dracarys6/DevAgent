import json
from pathlib import Path

import pytest

from devagent.tools.log_tools import (
    DEFAULT_LOG_DATA_DIR,
    MAX_LOG_CHARS,
    MAX_LOG_ENTRIES,
    LogLevel,
    SearchLogError,
    search_log,
)


def make_log_entry(
    sequence_id: int,
    *,
    task_id: str = "task_test",
    timestamp: str | None = None,
    level: str = "INFO",
    service: str = "app",
    message: str = "message",
    source: str | None = "src/app.py:10",
    context: dict | None = None,
) -> dict:
    return {
        "timestamp": timestamp or f"2026-07-13T09:00:{sequence_id:02d}Z",
        "sequence_id": sequence_id,
        "task_id": task_id,
        "level": level,
        "service": service,
        "message": message,
        "source": source,
        "context": context or {},
    }


def write_log_entries(data_dir: Path, task_id: str, entries: list[dict]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{task_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries),
        encoding="utf-8",
    )
    return path


def test_search_log_returns_entries_in_chronological_order(tmp_path: Path):
    write_log_entries(
        tmp_path,
        "task_test",
        [
            make_log_entry(3, timestamp="2026-07-13T09:00:02Z"),
            make_log_entry(2, timestamp="2026-07-13T09:00:01Z"),
            make_log_entry(1, timestamp="2026-07-13T09:00:01Z"),
        ],
    )

    result = json.loads(search_log("task_test", data_dir=tmp_path))

    assert [entry["sequence_id"] for entry in result["entries"]] == [1, 2, 3]


def test_search_log_identifies_first_anomaly():
    result = json.loads(search_log("task_001"))

    assert result["summary"] == {
        "total_entry_count": 6,
        "matched_entry_count": 6,
        "returned_entry_count": 6,
        "truncated": False,
    }
    assert result["first_anomaly"]["sequence_id"] == 3
    assert result["first_anomaly"]["level"] == "ERROR"
    assert result["first_anomaly"]["service"] == "uploader"
    assert result["first_anomaly"]["source"] == "src/sample_app/uploader.py:42"


def test_search_log_returns_no_anomaly_for_successful_task():
    result = json.loads(search_log("task_002"))

    assert result["summary"]["total_entry_count"] == 2
    assert result["first_anomaly"] is None
    assert all(entry["task_id"] == "task_002" for entry in _raw_entries("task_002"))


def _raw_entries(task_id: str) -> list[dict]:
    path = DEFAULT_LOG_DATA_DIR / f"{task_id}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_search_log_filters_exact_level():
    result = json.loads(search_log("task_001", level=LogLevel.ERROR))

    assert result["filters"]["level"] == "ERROR"
    assert [entry["sequence_id"] for entry in result["entries"]] == [3, 5]


def test_search_log_accepts_case_insensitive_string_level():
    result = json.loads(search_log("task_001", level="critical"))

    assert [entry["sequence_id"] for entry in result["entries"]] == [6]


@pytest.mark.parametrize(
    ("keyword", "expected_sequence_ids"),
    [
        ("UPLOADTIMEOUTERROR", [3]),
        ("retry", [4, 5]),
        ("uploader.py:42", [3]),
        ("expected_seconds", [3]),
    ],
)
def test_search_log_filters_keyword_across_evidence_fields(
    keyword: str,
    expected_sequence_ids: list[int],
):
    result = json.loads(search_log("task_001", keyword=keyword))

    assert [entry["sequence_id"] for entry in result["entries"]] == (
        expected_sequence_ids
    )


def test_search_log_combines_level_and_keyword_filters():
    result = json.loads(
        search_log("task_001", level="ERROR", keyword="retry")
    )

    assert [entry["sequence_id"] for entry in result["entries"]] == [5]


def test_search_log_returns_empty_entries_when_no_match():
    result = json.loads(search_log("task_001", keyword="database"))

    assert result["summary"]["matched_entry_count"] == 0
    assert result["entries"] == []
    assert result["first_anomaly"]["sequence_id"] == 3


def test_search_log_keeps_first_anomaly_when_filter_excludes_it():
    result = json.loads(search_log("task_001", keyword="RetryExhaustedError"))

    assert [entry["sequence_id"] for entry in result["entries"]] == [5]
    assert result["first_anomaly"]["sequence_id"] == 3


def test_search_log_reduces_context_without_hiding_first_anomaly():
    raw = (DEFAULT_LOG_DATA_DIR / "task_001.jsonl").read_text(encoding="utf-8")

    content = search_log("task_001", keyword="RetryExhaustedError")
    result = json.loads(content)

    assert 1 - len(content) / len(raw) >= 0.50
    assert result["first_anomaly"]["sequence_id"] == 3
    assert [entry["sequence_id"] for entry in result["entries"]] == [5]


def test_search_log_limits_entry_count():
    result = json.loads(search_log("task_001", max_entries=2))

    assert result["summary"]["matched_entry_count"] == 6
    assert result["summary"]["returned_entry_count"] == 2
    assert result["summary"]["truncated"] is True
    assert len(result["entries"]) == 2


def test_search_log_limits_output_chars_and_keeps_valid_json(tmp_path: Path):
    entries = [
        make_log_entry(
            sequence_id,
            level="ERROR" if sequence_id == 1 else "INFO",
            message="long-message-" + "x" * 900,
            context={"payload": "y" * 900},
        )
        for sequence_id in range(1, 10)
    ]
    write_log_entries(tmp_path, "task_test", entries)

    content = search_log("task_test", data_dir=tmp_path, max_chars=700)
    result = json.loads(content)

    assert len(content) <= 700
    assert result["summary"]["truncated"] is True
    assert result["first_anomaly"]["sequence_id"] == 1


@pytest.mark.parametrize("task_id", ["", "../secret", "task/001", "task.001"])
def test_search_log_rejects_invalid_task_id(task_id: str):
    with pytest.raises(SearchLogError, match="task_id 只能"):
        search_log(task_id)


@pytest.mark.parametrize("keyword", ["", "   "])
def test_search_log_rejects_empty_keyword(keyword: str):
    with pytest.raises(SearchLogError, match="keyword"):
        search_log("task_001", keyword=keyword)


def test_search_log_rejects_invalid_level():
    with pytest.raises(SearchLogError, match="level"):
        search_log("task_001", level="verbose")


@pytest.mark.parametrize(
    ("max_entries", "max_chars"),
    [
        (0, 8_000),
        (MAX_LOG_ENTRIES + 1, 8_000),
        (50, 499),
        (50, MAX_LOG_CHARS + 1),
    ],
)
def test_search_log_rejects_invalid_limits(max_entries: int, max_chars: int):
    with pytest.raises(SearchLogError, match="max_entries|max_chars"):
        search_log("task_001", max_entries=max_entries, max_chars=max_chars)


def test_search_log_rejects_missing_data_dir(tmp_path: Path):
    with pytest.raises(SearchLogError, match="日志数据目录不存在"):
        search_log("task_test", data_dir=tmp_path / "missing")


def test_search_log_rejects_data_dir_file(tmp_path: Path):
    data_file = tmp_path / "logs"
    data_file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(SearchLogError, match="日志数据路径不是目录"):
        search_log("task_test", data_dir=data_file)


def test_search_log_rejects_unknown_task(tmp_path: Path):
    with pytest.raises(SearchLogError, match="未找到 task_id"):
        search_log("task_test", data_dir=tmp_path)


def test_search_log_rejects_result_path_directory(tmp_path: Path):
    (tmp_path / "task_test.jsonl").mkdir()

    with pytest.raises(SearchLogError, match="日志数据路径不是文件"):
        search_log("task_test", data_dir=tmp_path)


def test_search_log_rejects_symlink_outside_data_dir(tmp_path: Path):
    data_dir = tmp_path / "logs"
    data_dir.mkdir()
    outside = tmp_path / "outside.jsonl"
    write_log_entries(tmp_path, "outside", [make_log_entry(1)])
    (data_dir / "task_test.jsonl").symlink_to(outside)

    with pytest.raises(SearchLogError, match="data_dir 之外"):
        search_log("task_test", data_dir=data_dir)


def test_search_log_reports_malformed_jsonl_line_number(tmp_path: Path):
    path = write_log_entries(tmp_path, "task_test", [make_log_entry(1)])
    path.write_text(path.read_text(encoding="utf-8") + "\n{bad json", encoding="utf-8")

    with pytest.raises(SearchLogError, match="第 2 行格式校验失败"):
        search_log("task_test", data_dir=tmp_path)


def test_search_log_rejects_log_task_id_mismatch(tmp_path: Path):
    write_log_entries(tmp_path, "task_test", [make_log_entry(1, task_id="other")])

    with pytest.raises(SearchLogError, match="第 1 行 task_id 与请求不匹配"):
        search_log("task_test", data_dir=tmp_path)


def test_search_log_rejects_duplicate_sequence_id(tmp_path: Path):
    write_log_entries(
        tmp_path,
        "task_test",
        [make_log_entry(1), make_log_entry(1, timestamp="2026-07-13T09:00:02Z")],
    )

    with pytest.raises(SearchLogError, match="重复的 sequence_id"):
        search_log("task_test", data_dir=tmp_path)


def test_search_log_rejects_non_utf8_file(tmp_path: Path):
    (tmp_path / "task_test.jsonl").write_bytes(b"\xff\xfe")

    with pytest.raises(SearchLogError, match="UTF-8"):
        search_log("task_test", data_dir=tmp_path)
