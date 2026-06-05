from pathlib import Path

import pytest

from devagent.tools.file_tools import (
    ReadFileError,
    ensure_workspace_path,
    read_file,
    read_file_safe,
)


def test_read_file_with_line_numbers(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    assert read_file(file_path, start_line=2, end_line=3) == "2: beta\n3: gamma"


def test_read_file_limits_max_lines(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("\n".join(str(i) for i in range(1, 6)), encoding="utf-8")

    assert read_file(file_path, start_line=1, end_line=5, max_lines=2) == "1: 1\n2: 2"


def test_read_file_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_file(tmp_path / "missing.txt")


def test_read_file_invalid_line_range_raises(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    with pytest.raises(ReadFileError):
        read_file(file_path, start_line=3, end_line=2)


def test_read_file_safe_returns_error_message(tmp_path: Path):
    result = read_file_safe(tmp_path / "missing.txt")

    assert result.startswith("读取文件失败:")


def test_ensure_workspace_path_allows_relative_path_inside_workspace(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    assert ensure_workspace_path(tmp_path, "sample.txt") == file_path.resolve()


def test_ensure_workspace_path_blocks_parent_traversal(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    with pytest.raises(ReadFileError):
        ensure_workspace_path(tmp_path, "../outside.txt")


def test_read_file_with_workspace_allows_file_inside_workspace(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")

    assert read_file("sample.txt", workspace=tmp_path) == "1: alpha"


def test_read_file_safe_blocks_file_out_of_workspace(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    result = read_file_safe(outside, workspace=tmp_path)

    assert result.startswith("读取文件失败:")
