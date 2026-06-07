import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_CHARS = 20_000
DEFAULT_SHELL_TIMEOUT = 10.0
TRUNCATION_MARKER = "\n... 命令输出过长，已截断 ..."


class RunShellError(Exception):
    """Shell 命令无法安全执行时抛出的异常。"""


@dataclass(frozen=True)
class RunShellResult:
    """一次 Shell 命令执行完成后的结构化结果。"""

    command: tuple[str, ...]
    cwd: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


def _resolve_cwd(cwd: str | Path, workspace: str | Path | None = None) -> Path:
    if workspace is None:
        target = Path(cwd).resolve()
    else:
        root = Path(workspace).resolve()
        if not root.exists():
            raise RunShellError(f"工作区不存在: {workspace}")
        if not root.is_dir():
            raise RunShellError(f"工作区不是目录: {workspace}")

        requested_cwd = Path(cwd)
        target = (
            requested_cwd.resolve()
            if requested_cwd.is_absolute()
            else (root / requested_cwd).resolve()
        )
        if not target.is_relative_to(root):
            raise RunShellError(f"命令工作目录位于工作区之外: {cwd}")

    if not target.exists():
        raise RunShellError(f"命令工作目录不存在: {target}")
    if not target.is_dir():
        raise RunShellError(f"命令工作目录不是目录: {target}")
    return target


def _truncate_output(output: str, max_chars: int) -> str:
    if len(output) <= max_chars:
        return output
    if max_chars <= len(TRUNCATION_MARKER):
        return TRUNCATION_MARKER[:max_chars]
    content_size = max_chars - len(TRUNCATION_MARKER)
    return output[:content_size] + TRUNCATION_MARKER


def run_shell(
    command: list[str],
    cwd: str | Path = ".",
    timeout: float = DEFAULT_SHELL_TIMEOUT,
    max_chars: int = MAX_OUTPUT_CHARS,
    workspace: str | Path | None = None,
) -> RunShellResult:
    """执行参数列表形式的命令，并返回 stdout、stderr 和 returncode。"""
    if not command:
        raise RunShellError("command 命令不能为空")
    if any(not isinstance(argument, str) for argument in command):
        raise RunShellError("command 中的每个参数都必须是字符串")
    if timeout <= 0:
        raise RunShellError("timeout 必须大于 0")
    if max_chars < 1:
        raise RunShellError("max_chars 必须大于或等于 1")

    resolved_cwd = _resolve_cwd(cwd, workspace)

    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            cwd=resolved_cwd,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RunShellError(f"未找到命令: {command[0]}") from exc
    except PermissionError as exc:
        raise RunShellError(f"没有权限执行命令: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RunShellError(f"命令执行超时，限制时间为 {timeout} 秒。") from exc
    except OSError as exc:
        raise RunShellError(f"命令启动失败: {exc}") from exc

    return RunShellResult(
        command=tuple(command),
        cwd=str(resolved_cwd),
        returncode=result.returncode,
        stdout=_truncate_output(result.stdout, max_chars),
        stderr=_truncate_output(result.stderr, max_chars),
    )
