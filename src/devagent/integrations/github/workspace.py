from collections.abc import Callable
from pathlib import Path
import re
import subprocess

from .client import GitHubClientError

GitRunner = Callable[[list[str], Path, float], str]


class ControlledGitHubWorkspace:
    """为一个 allowlist GitHub 仓库准备只读审查 refs。"""

    def __init__(
        self,
        *,
        allowed_repository: str,
        workspace: str | Path,
        allowed_root: str | Path | None = None,
        git_runner: GitRunner | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self._allowed_repository = _normalize_repository(allowed_repository)
        self._workspace = Path(workspace).expanduser().resolve()
        self._allowed_root = Path(allowed_root or self._workspace.parent).expanduser().resolve()
        try:
            self._workspace.relative_to(self._allowed_root)
        except ValueError as exc:
            raise ValueError("GitHub workspace 必须位于 allowed_root 内") from exc
        self._git_runner = git_runner or _run_git
        self._timeout_seconds = timeout_seconds

    def prepare(
        self,
        *,
        repository: str,
        pull_number: int,
        base_sha: str,
        head_sha: str,
    ) -> Path:
        if _normalize_repository(repository) != self._allowed_repository:
            raise GitHubClientError("GitHub repository 不在 workspace allowlist 中")
        if isinstance(pull_number, bool) or pull_number < 1:
            raise ValueError("pull_number 必须大于或等于 1")
        _validate_sha(base_sha)
        _validate_sha(head_sha)
        if not self._workspace.is_dir():
            raise GitHubClientError("受控 GitHub workspace 不存在")

        try:
            root = Path(
                self._git_runner(
                    ["rev-parse", "--show-toplevel"],
                    self._workspace,
                    self._timeout_seconds,
                )
            ).resolve()
            if root != self._workspace:
                raise GitHubClientError("GitHub workspace 必须是仓库根目录")
            remote = self._git_runner(
                ["remote", "get-url", "origin"],
                self._workspace,
                self._timeout_seconds,
            ).strip()
            if _repository_from_remote(remote) != self._allowed_repository:
                raise GitHubClientError("GitHub workspace origin 与 allowlist 不匹配")
            self._git_runner(
                [
                    "fetch",
                    "--no-tags",
                    "origin",
                    f"+refs/pull/{pull_number}/head:refs/devagent/pull/{pull_number}/head",
                ],
                self._workspace,
                self._timeout_seconds,
            )
            for sha in (base_sha, head_sha):
                self._git_runner(
                    ["cat-file", "-e", f"{sha}^{{commit}}"],
                    self._workspace,
                    self._timeout_seconds,
                )
        except GitHubClientError:
            raise
        except Exception as exc:
            raise GitHubClientError("无法准备受控 GitHub workspace") from exc
        return self._workspace


def _run_git(args: list[str], workspace: Path, timeout_seconds: float) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitHubClientError("受控 Git workspace 命令失败") from exc
    return result.stdout.strip()


def _normalize_repository(repository: str) -> str:
    if not isinstance(repository, str) or repository != repository.strip():
        raise ValueError("repository 格式无效")
    parts = repository.split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        raise ValueError("repository 必须使用 owner/repo 格式")
    return repository.lower()


def _repository_from_remote(remote: str) -> str:
    patterns = (
        r"https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"ssh://git@github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, remote)
        if match:
            return _normalize_repository(match.group("repo"))
    raise GitHubClientError("GitHub workspace origin URL 不受支持")


def _validate_sha(value: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", value):
        raise ValueError("GitHub commit SHA 格式无效")
