from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError

from devagent.diagnosis.models import Evidence, EvidenceKind, MissingEvidence
from devagent.llm import LLMClient, LLMResponse, LLMResponseType
from devagent.prompts.code_review import (
    CODE_REVIEW_SYSTEM_PROMPT,
    build_code_review_prompt,
)
from devagent.tools.git_tools import (
    GitCompareError,
    GitCompareResult,
    git_compare,
)
from devagent.tools.read_file_tools import ReadFileError, read_file

from .models import CodeReviewInput, CodeReviewReport, ReviewStatus

MAX_REVIEW_EVIDENCE_CHARS = 4_000
MAX_CONTEXT_FILES = 5
MAX_CONTEXT_LINES_PER_FILE = 200

ReviewIdFactory = Callable[[], str]
GitCompareReader = Callable[[str, str, str | Path], GitCompareResult]


class ReviewFileReader(Protocol):
    def __call__(
        self,
        file_path: str | Path,
        *,
        start_line: int = 1,
        end_line: int | None = None,
        max_lines: int = MAX_CONTEXT_LINES_PER_FILE,
        workspace: str | Path | None = None,
    ) -> str: ...


class CodeReviewServiceErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    EVIDENCE_COLLECTION_FAILED = "evidence_collection_failed"
    LLM_CALL_FAILED = "llm_call_failed"
    UNEXPECTED_LLM_RESPONSE = "unexpected_llm_response"
    EMPTY_LLM_RESPONSE = "empty_llm_response"
    INVALID_REPORT = "invalid_report"
    REPORT_MISMATCH = "report_mismatch"


class CodeReviewServiceError(Exception):
    """代码审查服务无法形成可信报告时抛出的结构化异常。"""

    def __init__(self, *, code: CodeReviewServiceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CodeReviewEvidenceCollector(Protocol):
    """把 Git 变更和文件内容标准化为代码审查输入。"""

    def collect(
        self,
        *,
        review_id: str,
        base_ref: str,
        head_ref: str,
        workspace: Path,
    ) -> CodeReviewInput: ...


class LocalCodeReviewEvidenceCollector:
    """从本地 Git 仓库采集有界的代码审查证据。"""

    def __init__(
        self,
        *,
        git_compare_reader: GitCompareReader = git_compare,
        file_reader: ReviewFileReader = read_file,
    ) -> None:
        self._git_compare_reader = git_compare_reader
        self._file_reader = file_reader

    def collect(
        self,
        *,
        review_id: str,
        base_ref: str,
        head_ref: str,
        workspace: Path,
    ) -> CodeReviewInput:
        evidence: list[Evidence] = []
        missing_evidence: list[MissingEvidence] = []

        try:
            result = self._git_compare_reader(base_ref, head_ref, workspace)
        except GitCompareError as exc:
            missing_evidence.append(
                MissingEvidence(
                    needed=f"从 {base_ref} 到 {head_ref} 的代码差异",
                    reason=str(exc),
                    suggested_tool="git_compare",
                )
            )
            return _build_review_input(
                review_id=review_id,
                base_ref=base_ref,
                head_ref=head_ref,
                workspace=workspace,
                evidence=evidence,
                missing_evidence=missing_evidence,
            )
        except Exception as exc:
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="Git compare 返回了无法标准化的数据",
            ) from exc

        try:
            if result.base_ref != base_ref or result.head_ref != head_ref:
                raise ValueError("git_compare 返回的 refs 与请求不一致")
            _append_diff_evidence(
                result=result,
                base_ref=base_ref,
                head_ref=head_ref,
                evidence=evidence,
                missing_evidence=missing_evidence,
            )
            self._append_file_evidence(
                result=result,
                workspace=workspace,
                evidence=evidence,
                missing_evidence=missing_evidence,
            )
            return _build_review_input(
                review_id=review_id,
                base_ref=base_ref,
                head_ref=head_ref,
                workspace=workspace,
                evidence=evidence,
                missing_evidence=missing_evidence,
            )
        except CodeReviewServiceError:
            raise
        except Exception as exc:
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="Git compare 返回了无法标准化的数据",
            ) from exc

    def _append_file_evidence(
        self,
        *,
        result: GitCompareResult,
        workspace: Path,
        evidence: list[Evidence],
        missing_evidence: list[MissingEvidence],
    ) -> None:
        for relative_path in _select_context_paths(result):
            try:
                excerpt = self._file_reader(
                    relative_path,
                    start_line=1,
                    max_lines=MAX_CONTEXT_LINES_PER_FILE,
                    workspace=workspace,
                )
                if not isinstance(excerpt, str):
                    raise TypeError("read_file 必须返回字符串")
            except (FileNotFoundError, PermissionError, UnicodeDecodeError, ReadFileError) as exc:
                missing_evidence.append(
                    MissingEvidence(
                        needed=f"变更文件 {relative_path} 的代码上下文",
                        reason=_safe_file_error_reason(exc),
                        suggested_tool="read_file",
                    )
                )
                continue
            except Exception as exc:
                raise CodeReviewServiceError(
                    code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                    message="文件读取工具返回了无法标准化的数据",
                ) from exc

            # * 空文件没有正文可补充，文件存在性和删除/新增状态仍保留在 diff 证据中。
            if not excerpt.strip():
                continue
            returned_lines = len(excerpt.splitlines())
            evidence.append(
                Evidence(
                    evidence_id=_next_evidence_id(evidence),
                    kind=EvidenceKind.CODE,
                    tool_name="read_file",
                    source=str(workspace),
                    locator=f"path={relative_path};lines=1-{returned_lines}",
                    excerpt=_truncate_excerpt(excerpt),
                )
            )


class CodeReviewService:
    """协调代码证据采集、模型调用和审查报告校验。"""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        evidence_collector: CodeReviewEvidenceCollector,
        review_id_factory: ReviewIdFactory | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._evidence_collector = evidence_collector
        self._review_id_factory = review_id_factory or (lambda: str(uuid4()))

    def review(
        self,
        *,
        base_ref: str,
        head_ref: str,
        workspace: str | Path,
    ) -> CodeReviewReport:
        root = _validate_request(base_ref=base_ref, head_ref=head_ref, workspace=workspace)
        try:
            review_id = self._review_id_factory()
        except Exception as exc:
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="无法生成代码审查标识",
            ) from exc
        if not isinstance(review_id, str) or not review_id.strip():
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="review_id 生成器返回了无效标识",
            )

        try:
            review_input = self._evidence_collector.collect(
                review_id=review_id,
                base_ref=base_ref,
                head_ref=head_ref,
                workspace=root,
            )
        except CodeReviewServiceError:
            raise
        except Exception as exc:
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="代码审查证据采集失败",
            ) from exc

        self._validate_collected_input(
            review_input=review_input,
            review_id=review_id,
            base_ref=base_ref,
            head_ref=head_ref,
            workspace=root,
        )
        if not review_input.evidence:
            missing_evidence = review_input.missing_evidence or [
                MissingEvidence(
                    needed="待审查变更的代码证据",
                    reason="证据采集器未返回可用证据",
                    suggested_tool="git_compare",
                )
            ]
            return CodeReviewReport(
                review_id=review_id,
                base_ref=base_ref,
                head_ref=head_ref,
                status=ReviewStatus.INSUFFICIENT_EVIDENCE,
                summary="没有可用的证据进行代码审查",
                findings=[],
                evidence=[],
                missing_evidence=missing_evidence,
            )

        # * Service 已完成工具采集，模型在这里必须直接返回最终结构化报告。
        messages = [
            {"role": "system", "content": CODE_REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": build_code_review_prompt(review_input)},
        ]
        try:
            response = self._llm_client.chat(messages)
        except Exception as exc:
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.LLM_CALL_FAILED,
                message="调用代码审查模型失败",
            ) from exc

        report = self._parse_report(response)
        self._validate_report(report=report, review_input=review_input)
        return report

    @staticmethod
    def _parse_report(response: LLMResponse) -> CodeReviewReport:
        if response.response_type != LLMResponseType.FINAL_ANSWER:
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.UNEXPECTED_LLM_RESPONSE,
                message="代码审查模型必须返回 final_answer",
            )
        if not response.content or not response.content.strip():
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.EMPTY_LLM_RESPONSE,
                message="代码审查模型返回的内容为空",
            )
        try:
            return CodeReviewReport.model_validate_json(response.content)
        except ValidationError as exc:
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.INVALID_REPORT,
                message="模型返回的代码审查报告不符合契约",
            ) from exc

    @staticmethod
    def _validate_collected_input(
        *,
        review_input: CodeReviewInput,
        review_id: str,
        base_ref: str,
        head_ref: str,
        workspace: Path,
    ) -> None:
        if not isinstance(review_input, CodeReviewInput):
            raise CodeReviewServiceError(
                code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="证据采集器必须返回 CodeReviewInput",
            )
        expected_fields = {
            "review_id": (review_input.review_id, review_id),
            "base_ref": (review_input.base_ref, base_ref),
            "head_ref": (review_input.head_ref, head_ref),
            "workspace": (Path(review_input.workspace).resolve(), workspace),
        }
        for field, (actual, expected) in expected_fields.items():
            if actual != expected:
                raise CodeReviewServiceError(
                    code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                    message=f"证据采集结果的 {field} 字段与请求不匹配",
                )

    @staticmethod
    def _validate_report(
        *,
        report: CodeReviewReport,
        review_input: CodeReviewInput,
    ) -> None:
        expected_fields = {
            "review_id": (report.review_id, review_input.review_id),
            "base_ref": (report.base_ref, review_input.base_ref),
            "head_ref": (report.head_ref, review_input.head_ref),
            "evidence": (report.evidence, review_input.evidence),
        }
        for field, (actual, expected) in expected_fields.items():
            if actual != expected:
                raise CodeReviewServiceError(
                    code=CodeReviewServiceErrorCode.REPORT_MISMATCH,
                    message=f"代码审查报告的 {field} 字段与输入不匹配",
                )


def _validate_request(
    *,
    base_ref: str,
    head_ref: str,
    workspace: str | Path,
) -> Path:
    if not base_ref.strip() or not head_ref.strip():
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.INVALID_REQUEST,
            message="base_ref 和 head_ref 不能为空",
        )
    if base_ref != base_ref.strip() or head_ref != head_ref.strip():
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.INVALID_REQUEST,
            message="base_ref 和 head_ref 不能包含首尾空白",
        )
    if base_ref == head_ref:
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.INVALID_REQUEST,
            message="base_ref 和 head_ref 不能相同",
        )

    root = Path(workspace).resolve()
    if not root.exists():
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.INVALID_REQUEST,
            message="workspace 不存在",
        )
    if not root.is_dir():
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.INVALID_REQUEST,
            message="workspace 不是目录",
        )
    return root


def _append_diff_evidence(
    *,
    result: GitCompareResult,
    base_ref: str,
    head_ref: str,
    evidence: list[Evidence],
    missing_evidence: list[MissingEvidence],
) -> None:
    if result.patch.strip():
        evidence.append(
            Evidence(
                evidence_id=_next_evidence_id(evidence),
                kind=EvidenceKind.GIT_DIFF,
                tool_name="git_compare",
                source=result.head_sha,
                locator=(
                    f"merge_base={result.merge_base};"
                    f"base_sha={result.base_sha};"
                    f"head_sha={result.head_sha};"
                    f"hunks={result.hunk_count};"
                    f"truncated={str(result.truncated).lower()}"
                ),
                excerpt=_truncate_excerpt(result.patch),
            )
        )
    else:
        missing_evidence.append(
            MissingEvidence(
                needed=f"从 {base_ref} 到 {head_ref} 的代码差异",
                reason="Git compare 未返回可用 patch",
                suggested_tool="git_compare",
            )
        )

    if result.truncated:
        missing_evidence.append(
            MissingEvidence(
                needed="完整的 merge-base diff",
                reason=(
                    "git_compare 输出已截断："
                    f"返回 {result.returned_patch_chars} 字符，"
                    f"原始内容 {result.original_patch_chars} 字符"
                ),
                suggested_tool="git_compare",
            )
        )


def _select_context_paths(result: GitCompareResult) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for changed_file in result.changed_files:
        path = changed_file.new_path
        if path is None or path in seen:
            continue
        seen.add(path)
        paths.append(path)
        if len(paths) == MAX_CONTEXT_FILES:
            break
    return paths


def _build_review_input(
    *,
    review_id: str,
    base_ref: str,
    head_ref: str,
    workspace: Path,
    evidence: list[Evidence],
    missing_evidence: list[MissingEvidence],
) -> CodeReviewInput:
    try:
        return CodeReviewInput(
            review_id=review_id,
            base_ref=base_ref,
            head_ref=head_ref,
            workspace=str(workspace),
            evidence=evidence,
            missing_evidence=missing_evidence,
        )
    except ValidationError as exc:
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
            message="证据采集结果不符合代码审查输入契约",
        ) from exc


def _safe_file_error_reason(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "变更文件不存在"
    if isinstance(exc, PermissionError):
        return "没有权限读取变更文件"
    if isinstance(exc, UnicodeDecodeError):
        return "变更文件不是可读取的 UTF-8 文本"
    return "无法安全读取变更文件"


def _truncate_excerpt(value: str) -> str:
    return value[:MAX_REVIEW_EVIDENCE_CHARS]


def _next_evidence_id(evidence: list[Evidence]) -> str:
    return f"E{len(evidence) + 1}"
