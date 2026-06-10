from pathlib import Path

import pytest

from devagent.tools.search_code_tools import SearchCodeError, search_code


def test_search_code_returns_matching_lines(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "def hello():\n    return 'needle'\n", encoding="utf-8"
    )

    result = search_code("needle", tmp_path)

    assert "./app.py:2:    return 'needle'" in result


def test_search_code_applies_file_pattern(tmp_path: Path):
    (tmp_path / "app.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("needle\n", encoding="utf-8")

    result = search_code("needle", tmp_path, file_pattern="*.py")

    assert "app.py" in result
    assert "notes.txt" not in result


def test_search_code_returns_empty_string_when_no_match(tmp_path: Path):
    (tmp_path / "app.py").write_text("hello\n", encoding="utf-8")

    assert search_code("needle", tmp_path) == ""


def test_search_code_truncates_output(tmp_path: Path):
    (tmp_path / "app.py").write_text("needle\n" * 20, encoding="utf-8")

    result = search_code("needle", tmp_path, max_chars=60)

    assert len(result) == 60
    assert result.endswith("... 搜索结果过长，已截断 ...")


def test_search_code_rejects_invalid_workspace(tmp_path: Path):
    with pytest.raises(SearchCodeError):
        search_code("needle", tmp_path / "missing")


def test_search_code_handles_query_starting_with_dash(tmp_path: Path):
    (tmp_path / "app.py").write_text("-needle\n", encoding="utf-8")

    assert "app.py" in search_code("-needle", tmp_path)
