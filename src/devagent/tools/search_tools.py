import subprocess
from pathlib import Path

MAX_SEARCH_CHARS = 20_000
DEFAULT_SEARCH_TIMEOUT = 10.0
TRUNCATION_MARKER = "\n... 搜索结果过长，已截断 ..."


class SearchCodeError(Exception):
    """代码搜索无法安全执行时抛出的异常。"""


def _resolve_workspace(workspace: str | Path) -> Path:
    root = Path(workspace).resolve()
    if not root.exists():
        raise SearchCodeError(f"工作区不存在: {workspace}")
    if not root.is_dir():
        raise SearchCodeError(f"工作区不是目录: {workspace}")
    return root


def _truncate_output(output: str, max_chars: int) -> str:
    if len(output) <= max_chars:
        return output
    if max_chars <= len(TRUNCATION_MARKER):
        return TRUNCATION_MARKER[:max_chars]
    content_size = max_chars - len(TRUNCATION_MARKER)
    return output[:content_size] + TRUNCATION_MARKER


def search_code(
    query: str,
    workspace: str | Path,
    file_pattern: str | None = None,
    max_chars: int = MAX_SEARCH_CHARS,
    timeout: float = DEFAULT_SEARCH_TIMEOUT,
) -> str:
    """使用 ripgrep 在工作区内搜索文本，并返回匹配行。"""
    if not query:
        raise SearchCodeError("query 不能为空")
    if max_chars < 1:
        raise SearchCodeError("max_chars 必须大于或等于 1")
    if timeout <= 0:
        raise SearchCodeError("timeout 必须大于 0")

    root = _resolve_workspace(workspace)
    command = ["rg", "--line-number", "--no-heading", "--color", "never"]
    if file_pattern is not None:
        command.extend(["--glob", file_pattern])

    # Everything after -- is treated as a positional argument, not an rg option.
    command.extend(["--", query, "."])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=root,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SearchCodeError("未找到 rg 命令，请先安装 ripgrep。") from exc
    except subprocess.TimeoutExpired as exc:
        raise SearchCodeError(f"搜索超时，限制时间为 {timeout} 秒。") from exc

    if result.returncode == 0:
        return _truncate_output(result.stdout, max_chars)
    if result.returncode == 1:
        return ""

    error = result.stderr.strip() or f"ripgrep 退出码为 {result.returncode}"
    raise SearchCodeError(f"搜索执行失败: {error}")
