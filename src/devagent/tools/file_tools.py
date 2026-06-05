from pathlib import Path

MAX_READ_LINES = 200


class ReadFileError(Exception):
    """Raised when read_file receives invalid input."""


def ensure_workspace_path(workspace: str | Path, path: str | Path) -> Path:
    """Resolve path and ensure it stays inside workspace."""
    root = Path(workspace).resolve()
    requested_path = Path(path)
    if requested_path.is_absolute():
        target = requested_path.resolve()
    else:
        target = (root / requested_path).resolve()

    if not target.is_relative_to(root):
        raise ReadFileError(f"file is out of workspace: {path}")
    return target


def read_file(
    file_path: str | Path,
    start_line: int = 1,
    end_line: int | None = None,
    encoding: str = "utf-8",
    max_lines: int = MAX_READ_LINES,
    workspace: str | Path | None = None,
) -> str:
    """Read a text file and return content with 1-based line numbers."""
    if workspace is None:
        path = Path(file_path)
    else:
        path = ensure_workspace_path(workspace, file_path)

    if start_line < 1:
        raise ReadFileError("start_line must be greater than or equal to 1")
    if end_line is not None and end_line < start_line:
        raise ReadFileError("end_line must be greater than or equal to start_line")
    if max_lines < 1:
        raise ReadFileError("max_lines must be greater than or equal to 1")
    if not path.exists():
        raise FileNotFoundError(f"file does not exist: {path}")
    if not path.is_file():
        raise ReadFileError(f"path is not a regular file: {path}")

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
    """Compatibility wrapper that returns readable error messages."""
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
