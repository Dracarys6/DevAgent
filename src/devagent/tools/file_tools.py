from pathlib import Path
import subprocess

MAX_READ_LINES = 200


class ReadFileError(Exception):
    """读取文件失败时抛出的异常。"""


def ensure_workspace_path(workspace: str | Path, path: str | Path) -> Path:
    """解析路径，并确保目标路径位于工作区内。"""
    root = Path(workspace).resolve()
    requested_path = Path(path)
    if requested_path.is_absolute():
        target = requested_path.resolve()
    else:
        target = (root / requested_path).resolve()

    if not target.is_relative_to(root):
        raise ReadFileError(f"文件位于工作区之外: {path}")
    return target


def read_file(
    file_path: str | Path,
    start_line: int = 1,
    end_line: int | None = None,
    encoding: str = "utf-8",
    max_lines: int = MAX_READ_LINES,
    workspace: str | Path | None = None,
) -> str:
    """读取文本文件，并返回带有行号的内容。"""
    if workspace is None:
        path = Path(file_path)
    else:
        path = ensure_workspace_path(workspace, file_path)

    if start_line < 1:
        raise ReadFileError("start_line 必须大于或等于 1")
    if end_line is not None and end_line < start_line:
        raise ReadFileError("end_line 必须大于或等于 start_line")
    if max_lines < 1:
        raise ReadFileError("max_lines 必须大于或等于 1")
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if not path.is_file():
        raise ReadFileError(f"路径不是普通文件: {path}")

    lines = path.read_text(encoding=encoding).splitlines()
    total_lines = len(lines)

    if end_line is None:
        end_line = min(start_line + max_lines - 1, total_lines)
    else:
        end_line = min(end_line, start_line + max_lines - 1, total_lines)

    selected = lines[start_line - 1 : end_line]
    return "\n".join(
        f"{line_no}: {line}" for line_no, line in enumerate(selected, start=start_line)
    )


def read_file_safe(
    file_path: str | Path,
    start_line: int = 1,
    end_line: int | None = None,
    encoding: str = "utf-8",
    workspace: str | Path | None = None,
) -> str:
    """捕获读取异常，并返回便于阅读的错误信息。"""
    try:
        return read_file(
            file_path,
            start_line=start_line,
            end_line=end_line,
            encoding=encoding,
            workspace=workspace,
        )
    except (
        FileNotFoundError,
        PermissionError,
        UnicodeDecodeError,
        ReadFileError,
    ) as exc:
        return f"读取文件失败: {exc}"
