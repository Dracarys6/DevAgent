import json
from pathlib import Path

import pytest

from devagent.tools.ci_tools import (
    CI_LOG_TRUNCATION_MARKER,
    DEFAULT_CI_DATA_DIR,
    MAX_CI_LOG_CHARS,
    CIResultError,
    get_ci_result,
)


def make_ci_payload(commit_id: str = "abcdef") -> dict:
    return {
        "pipeline_id": "pipeline-test",
        "commit_id": commit_id,
        "status": "failed",
        "started_at": "2026-07-11T09:00:00Z",
        "finished_at": "2026-07-11T09:00:10Z",
        "jobs": [
            {
                "name": "lint",
                "status": "passed",
                "duration_seconds": 1,
                "tests": [],
                "log_lines": ["All checks passed"],
            },
            {
                "name": "unit-tests",
                "status": "failed",
                "duration_seconds": 9,
                "tests": [
                    {
                        "name": "tests/test_app.py::test_ok",
                        "status": "passed",
                        "duration_seconds": 0.01,
                    },
                    {
                        "name": "tests/test_app.py::test_failure",
                        "status": "failed",
                        "duration_seconds": 0.02,
                        "error_type": "AssertionError",
                        "error_message": "assert 1 == 2",
                        "location": "tests/test_app.py:20",
                        "log_excerpt": ["E assert 1 == 2"],
                    },
                ],
                "log_lines": ["FAILED test_failure", "AssertionError"],
            },
        ],
    }


def write_ci_payload(
    data_dir: Path,
    payload: dict,
    file_commit_id: str = "abcdef",
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"{file_commit_id}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_get_ci_result_returns_only_failed_evidence():
    result = json.loads(get_ci_result("abc123"))

    assert result["pipeline_id"] == "pipeline-1001"
    assert result["commit_id"] == "abc123"
    assert result["summary"] == {
        "total_job_count": 2,
        "failed_job_count": 1,
        "failed_test_count": 1,
    }
    assert [job["name"] for job in result["failed_jobs"]] == ["unit-tests"]
    failed_tests = result["failed_jobs"][0]["failed_tests"]
    assert [test["name"] for test in failed_tests] == [
        "tests/test_uploader.py::test_large_upload_uses_dynamic_timeout"
    ]
    assert failed_tests[0]["error_message"] == "assert 3 >= 12"
    assert failed_tests[0]["location"] == "tests/test_uploader.py:30"
    assert "All checks passed" not in result["core_log"]


def test_get_ci_result_returns_compact_json_and_reduces_context():
    raw = (DEFAULT_CI_DATA_DIR / "abc123.json").read_text(encoding="utf-8")

    content = get_ci_result("abc123")

    assert "\n  " not in content
    assert 1 - len(content) / len(raw) >= 0.40


def test_get_ci_result_truncates_core_log(tmp_path: Path):
    payload = make_ci_payload()
    payload["jobs"][1]["log_lines"] = ["failure " + "x" * 500]
    write_ci_payload(tmp_path, payload)

    result = json.loads(get_ci_result("abcdef", tmp_path, max_log_chars=80))

    assert len(result["core_log"]) == 80
    assert result["core_log"].endswith(CI_LOG_TRUNCATION_MARKER)
    assert result["failed_jobs"][0]["failed_tests"][0]["error_message"] == (
        "assert 1 == 2"
    )


def test_get_ci_result_returns_empty_failure_lists_for_passed_run(tmp_path: Path):
    payload = make_ci_payload()
    payload["status"] = "passed"
    payload["jobs"] = [payload["jobs"][0]]
    write_ci_payload(tmp_path, payload)

    result = json.loads(get_ci_result("abcdef", tmp_path))

    assert result["summary"]["failed_job_count"] == 0
    assert result["summary"]["failed_test_count"] == 0
    assert result["failed_jobs"] == []
    assert result["core_log"] == ""


@pytest.mark.parametrize("commit_id", ["", "abc12", "not-a-sha", "../../secret"])
def test_get_ci_result_rejects_invalid_commit_id(commit_id: str):
    with pytest.raises(CIResultError, match="commit_id 必须"):
        get_ci_result(commit_id)


@pytest.mark.parametrize("max_log_chars", [0, MAX_CI_LOG_CHARS + 1])
def test_get_ci_result_rejects_invalid_max_log_chars(max_log_chars: int):
    with pytest.raises(CIResultError, match="max_log_chars"):
        get_ci_result("abc123", max_log_chars=max_log_chars)


def test_get_ci_result_rejects_missing_data_dir(tmp_path: Path):
    with pytest.raises(CIResultError, match="CI 数据目录不存在"):
        get_ci_result("abcdef", tmp_path / "missing")


def test_get_ci_result_rejects_data_dir_file(tmp_path: Path):
    data_file = tmp_path / "data.json"
    data_file.write_text("{}", encoding="utf-8")

    with pytest.raises(CIResultError, match="CI 数据路径不是目录"):
        get_ci_result("abcdef", data_file)


def test_get_ci_result_rejects_unknown_commit(tmp_path: Path):
    with pytest.raises(CIResultError, match="未找到 commit"):
        get_ci_result("abcdef", tmp_path)


def test_get_ci_result_rejects_result_path_directory(tmp_path: Path):
    (tmp_path / "abcdef.json").mkdir()

    with pytest.raises(CIResultError, match="CI 数据路径不是文件"):
        get_ci_result("abcdef", tmp_path)


def test_get_ci_result_rejects_result_path_outside_data_dir(tmp_path: Path):
    data_dir = tmp_path / "ci"
    data_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(make_ci_payload()), encoding="utf-8")
    (data_dir / "abcdef.json").symlink_to(outside)

    with pytest.raises(CIResultError, match="data_dir 之外"):
        get_ci_result("abcdef", data_dir)


def test_get_ci_result_rejects_malformed_json(tmp_path: Path):
    tmp_path.joinpath("abcdef.json").write_text("{bad json", encoding="utf-8")

    with pytest.raises(CIResultError, match="格式校验失败"):
        get_ci_result("abcdef", tmp_path)


def test_get_ci_result_rejects_invalid_ci_fields(tmp_path: Path):
    payload = make_ci_payload()
    payload["jobs"][0]["status"] = "unknown"
    write_ci_payload(tmp_path, payload)

    with pytest.raises(CIResultError, match="格式校验失败"):
        get_ci_result("abcdef", tmp_path)


def test_get_ci_result_rejects_commit_id_mismatch(tmp_path: Path):
    write_ci_payload(tmp_path, make_ci_payload(commit_id="abc123"))

    with pytest.raises(CIResultError, match="commit_id 与请求的 commit_id 不匹配"):
        get_ci_result("abcdef", tmp_path)


def test_get_ci_result_rejects_non_utf8_data(tmp_path: Path):
    tmp_path.joinpath("abcdef.json").write_bytes(b"\xff\xfe")

    with pytest.raises(CIResultError, match="UTF-8"):
        get_ci_result("abcdef", tmp_path)
