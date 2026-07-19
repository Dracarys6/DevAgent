import re
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, Field

MAX_GIT_DIFF_CHARS = 20_000
MAX_GIT_COMPARE_CHARS = 20_000
DEFAULT_GIT_TIMEOUT = 10.0
TRUNCATION_MARKER = "\n... git diff 输出过长，已截断 ..."


HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE
)


class GitDiffError(Exception):
    """Git diff 无法安全读取时抛出执行失败的异常。"""


class GitCompareError(Exception):
    """Git compare 无法安全读取时抛出执行失败的异常。"""


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
    """解析工作区路径；Git 仓库状态由后续只读 Git 命令判定。"""
    root = Path(workspace).resolve()
    if not root.exists():
        raise GitDiffError(f"工作区不存在: {root}")
    if not root.is_dir():
        raise GitDiffError(f"工作区不是目录: {root}")
    return root


class GitCompareArgs(BaseModel):
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    workspace: str
    max_chars: int = Field(default=20_000, ge=1, le=100_000)
    timeout: float = Field(default=10.0, gt=0, le=60)


class GitChangedFile(BaseModel):
    status: str
    old_path: str | None = None
    new_path: str | None = None
    similarity: int | None = Field(default=None, ge=0, le=100)  # * 相似度


class GitCompareResult(BaseModel):
    base_ref: str  # * 基准分支
    head_ref: str  # * 待对比的目标分支
    base_sha: str  # * 基准分支的提交 commit hash
    head_sha: str  # * 待对比的目标分支的提交 commit hash
    merge_base: str  # * 基准分支和目标分支的共同祖先 commit hash
    changed_files: list[GitChangedFile]  # * 变更的文件列表
    patch: str  # * 差异补丁文本
    hunk_count: int = Field(ge=0)  # * 变更块总数
    truncated: bool  # * 补丁是否被截断
    original_patch_chars: int
    returned_patch_chars: int


def git_compare(
    base_ref: str,
    head_ref: str,
    workspace: str | Path,
    max_chars: int = MAX_GIT_COMPARE_CHARS,
    timeout: float = DEFAULT_GIT_TIMEOUT,
) -> GitCompareResult:
    """返回 base/head 合入范围的结构化变更证据。"""
    _validate_compare_parameters(base_ref, head_ref, max_chars, timeout)

    try:
        root = _resolve_workspace(workspace)
    except GitDiffError as exc:
        raise GitCompareError(str(exc)) from exc

    deadline = time.monotonic() + timeout
    base_sha = _get_commit_sha(
        base_ref,
        root,
        timeout=_remaining_timeout(deadline, timeout),
        ref_name="base_ref",
    )
    head_sha = _get_commit_sha(
        head_ref,
        root,
        timeout=_remaining_timeout(deadline, timeout),
        ref_name="head_ref",
    )
    if base_sha == head_sha:
        raise GitCompareError("base_ref 和 head_ref 不能解析到同一 commit")

    merge_base = _get_merge_base(
        base_sha,
        head_sha,
        root,
        timeout=_remaining_timeout(deadline, timeout),
    )
    changed_files_output = _run_git_compare(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames",
            "--find-copies",
            merge_base,
            head_sha,
            "--",
        ],
        root,
        timeout=_remaining_timeout(deadline, timeout),
        failure_message="无法读取 Git 文件变更状态",
    )
    patch = _run_git_compare(
        [
            "git",
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames",
            "--find-copies",
            "--unified=3",
            merge_base,
            head_sha,
            "--",
        ],
        root,
        timeout=_remaining_timeout(deadline, timeout),
        failure_message="无法读取 Git compare patch",
    )
    returned_patch, truncated = _truncate_patch(patch, max_chars)

    return GitCompareResult(
        base_ref=base_ref,
        head_ref=head_ref,
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base=merge_base,
        changed_files=_parse_changed_files(changed_files_output),
        patch=returned_patch,
        hunk_count=len(HUNK_HEADER_PATTERN.findall(patch)),
        truncated=truncated,
        original_patch_chars=len(patch),
        returned_patch_chars=len(returned_patch),
    )


def _validate_compare_parameters(
    base_ref: str,
    head_ref: str,
    max_chars: int,
    timeout: float,
) -> None:
    if not base_ref.strip():
        raise GitCompareError("base_ref 不能为空")
    if not head_ref.strip():
        raise GitCompareError("head_ref 不能为空")
    if base_ref != base_ref.strip() or head_ref != head_ref.strip():
        raise GitCompareError("base_ref 和 head_ref 不能包含首尾空白")
    if base_ref == head_ref:
        raise GitCompareError("base_ref 和 head_ref 不能相同")
    if max_chars < 1:
        raise GitCompareError("max_chars 必须大于或等于 1")
    if timeout <= 0:
        raise GitCompareError("timeout 必须大于 0")


def _get_commit_sha(
    ref: str,
    workspace: Path,
    timeout: float,
    ref_name: str,
) -> str:
    """获取指定 ref 的 commit hash。"""
    command = ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"]
    sha = _run_git_compare(
        command,
        workspace,
        timeout=timeout,
        failure_message=f"无法解析 {ref_name}: {ref}",
    ).strip()
    if re.fullmatch(r"[0-9a-f]{40,64}", sha) is None:
        raise GitCompareError(f"{ref_name} 未解析为有效 commit SHA")
    return sha


def _get_merge_base(
    base_sha: str,
    head_sha: str,
    workspace: Path,
    timeout: float,
) -> str:
    """获取两个分支的共同祖先 commit hash。"""
    command = ["git", "merge-base", "--", base_sha, head_sha]
    merge_base = _run_git_compare(
        command,
        workspace,
        timeout=timeout,
        failure_message="base_ref 和 head_ref 没有共同祖先",
    ).strip()
    if re.fullmatch(r"[0-9a-f]{40,64}", merge_base) is None:
        raise GitCompareError("merge-base 未返回有效 commit SHA")
    return merge_base


def _run_git_compare(
    command: list[str],
    workspace: Path,
    timeout: float,
    failure_message: str,
) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitCompareError(f"Git compare 命令执行超时: {timeout} 秒") from exc
    except FileNotFoundError as exc:
        raise GitCompareError("未找到 git 命令，请确保已安装 Git") from exc
    except PermissionError as exc:
        raise GitCompareError("没有权限执行 git 命令，请检查权限设置") from exc
    except OSError as exc:
        raise GitCompareError(f"git 命令启动失败: {exc}") from exc

    if result.returncode != 0:
        if "not a git repository" in result.stderr.lower():
            raise GitCompareError(f"工作区不是 Git 仓库: {workspace}")
        raise GitCompareError(failure_message)
    return result.stdout


def _parse_changed_files(output: str) -> list[GitChangedFile]:
    """解析 ``git diff --name-status -z`` 的 NUL 分隔输出。"""
    fields = output.split("\0")
    if fields and fields[-1] == "":
        fields.pop()

    changed_files: list[GitChangedFile] = []
    index = 0
    while index < len(fields):
        status_token = fields[index]
        index += 1
        if not status_token:
            raise GitCompareError("Git 文件状态输出格式无效")

        status = status_token[0]
        similarity_text = status_token[1:]
        similarity = int(similarity_text) if similarity_text.isdigit() else None
        if status in {"R", "C"}:
            if index + 1 >= len(fields):
                raise GitCompareError("Git rename/copy 状态缺少路径")
            old_path, new_path = fields[index], fields[index + 1]
            index += 2
        elif status in {"A", "M", "D", "T", "U", "X", "B"}:
            if index >= len(fields):
                raise GitCompareError("Git 文件状态缺少路径")
            path = fields[index]
            index += 1
            old_path = None if status == "A" else path
            new_path = None if status == "D" else path
        else:
            raise GitCompareError(f"无法识别 Git 文件状态: {status_token}")

        changed_files.append(
            GitChangedFile(
                status=status,
                old_path=old_path,
                new_path=new_path,
                similarity=similarity,
            )
        )
    return changed_files


def _truncate_patch(patch: str, max_chars: int) -> tuple[str, bool]:
    if len(patch) <= max_chars:
        return patch, False
    return patch[:max_chars], True


def _remaining_timeout(deadline: float, total_timeout: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GitCompareError(f"Git compare 命令执行超时: {total_timeout} 秒")
    return remaining
