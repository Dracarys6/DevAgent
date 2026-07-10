import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

MAX_GIT_DIFF_CHARS = 20_000
DEFAULT_GIT_TIMEOUT = 10.0
TRUNCATION_MARKER = "\n... git diff 输出过长，已截断 ..."


class GitDiffError(Exception):
    """Git diff 无法安全读取时抛出执行失败的异常。"""


class GitDiffArgs(BaseModel):
    commit_id: str = Field(min_length=1)
    workspace: str
    max_chars: int = Field(
        default=20_000,
        ge=1,
        le=100_000,
    )
    timeout: float = Field(default=10.0, gt=0, le=60)


def git_diff(
    commit_id: str,
    workspace: str | Path,
    max_chars: int = MAX_GIT_DIFF_CHARS,
    timeout: float = DEFAULT_GIT_TIMEOUT,
) -> str:
    """返回指定 commit 引入的 patch，并限制执行时间和输出大小。"""
    if not commit_id.strip():
        raise GitDiffError("commit_id 不能为空")
    if max_chars < 1:
        raise GitDiffError("max_chars 必须大于或等于 1")
    if timeout <= 0:
        raise GitDiffError("timeout 必须大于 0")

    root = _resolve_workspace(workspace)
    command = [
        "git",
        "show",
        "--format=",
        "--no-ext-diff",
        "--no-textconv",
        "--unified=3",
        "--end-of-options",
        commit_id,
        "--",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitDiffError(f"Git diff 命令执行超时: {timeout} 秒") from exc
    except FileNotFoundError as exc:
        raise GitDiffError("未找到 git 命令，请确保已安装 Git") from exc
    except PermissionError as exc:
        raise GitDiffError("没有权限执行 git 命令，请检查权限设置") from exc
    except OSError as exc:
        raise GitDiffError(f"git 命令启动失败: {exc}") from exc

    if result.returncode != 0:
        if "not a git repository" in result.stderr.lower():
            raise GitDiffError(f"工作区不是 Git 仓库: {root}")
        raise GitDiffError(f"无法读取 Git commit: {commit_id}")

    return _truncate_output(result.stdout, max_chars)


def _truncate_output(output: str, max_chars: int) -> str:
    if len(output) <= max_chars:
        return output
    if max_chars <= len(TRUNCATION_MARKER):
        return TRUNCATION_MARKER[:max_chars]
    content_size = max_chars - len(TRUNCATION_MARKER)
    return output[:content_size] + TRUNCATION_MARKER


def _resolve_workspace(workspace: str | Path) -> Path:
    """解析工作区路径；Git 仓库状态由 git show 自身判定。"""
    root = Path(workspace).resolve()
    if not root.exists():
        raise GitDiffError(f"工作区不存在: {root}")
    if not root.is_dir():
        raise GitDiffError(f"工作区不是目录: {root}")
    return root
