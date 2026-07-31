import json
from collections.abc import Callable
from enum import Enum
from json import JSONDecodeError
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError

from devagent.llm import LLMClient, LLMResponse, LLMResponseType
from devagent.prompts import (
    CI_DIAGNOSIS_SYSTEM_PROMPT,
    LOG_DIAGNOSIS_SYSTEM_PROMPT,
    build_ci_diagnosis_prompt,
    build_log_diagnosis_prompt,
)
from devagent.tools.ci_tools import CIResultError, get_ci_result
from devagent.tools.git_tools import GitDiffError, git_diff
from devagent.tools.log_tools import SearchLogError, search_log

from .models import (
    DiagnosisInput,
    DiagnosisReport,
    DiagnosisReportDraft,
    DiagnosisScenario,
    Evidence,
    EvidenceKind,
    LogDiagnosisInput,
    MissingEvidence,
)

MAX_EVIDENCE_EXCERPT_CHARS = 4_000
ReportIdFactory = Callable[[], str]
CIResultReader = Callable[[str], str]
GitDiffReader = Callable[[str, str], str]
LogResultReader = Callable[[str, str], str]
CI_GIT_PATHS = ("*.py",)


class DiagnosisServiceErrorCode(str, Enum):
    EVIDENCE_COLLECTION_FAILED = "evidence_collection_failed"
    LLM_CALL_FAILED = "llm_call_failed"
    UNEXPECTED_LLM_RESPONSE = "unexpected_llm_response"
    EMPTY_LLM_RESPONSE = "empty_llm_response"
    INVALID_REPORT = "invalid_report"
    REPORT_MISMATCH = "report_mismatch"
    CONFIGURATION_ERROR = "configuration_error"


class DiagnosisServiceError(Exception):
    """诊断服务无法形成可信报告时抛出的结构化异常。"""

    def __init__(
        self,
        *,
        code: DiagnosisServiceErrorCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CIEvidenceCollector(Protocol):
    """把 CI 和 Git 工具结果标准化为诊断输入。"""

    def collect(
        self,
        *,
        report_id: str,
        commit_id: str,
        workspace: str,
    ) -> DiagnosisInput: ...


class LogEvidenceCollector(Protocol):
    """把结构化日志工具结果标准化为诊断输入。"""

    def collect(
        self,
        *,
        report_id: str,
        task_id: str,
        data_dir: str,
    ) -> LogDiagnosisInput: ...


def read_ci_git_diff(commit_id: str, workspace: str) -> str:
    """读取代码和测试变更，并移除可能直接泄露答案的纯注释行。"""
    patch = git_diff(commit_id, workspace, pathspecs=CI_GIT_PATHS)
    return _strip_comment_only_diff_lines(patch)


def _strip_comment_only_diff_lines(patch: str) -> str:
    lines: list[str] = []
    for line in patch.splitlines(keepends=True):
        is_file_marker = line.startswith(("+++", "---"))
        is_diff_content = line.startswith(("+", "-", " "))
        if is_diff_content and not is_file_marker and line[1:].lstrip().startswith("#"):
            continue
        lines.append(line)
    return "".join(lines)


class LocalCIEvidenceCollector:
    """使用本地 CI 数据和 Git 仓库收集 CI 诊断证据。"""

    def __init__(
        self,
        *,
        ci_result_reader: CIResultReader = get_ci_result,
        git_diff_reader: GitDiffReader = read_ci_git_diff,
    ) -> None:
        self._ci_result_reader = ci_result_reader
        self._git_diff_reader = git_diff_reader

    def collect(
        self,
        *,
        report_id: str,
        commit_id: str,
        workspace: str,
    ) -> DiagnosisInput:
        evidence: list[Evidence] = []
        missing_evidence: list[MissingEvidence] = []

        try:
            ci_result = self._ci_result_reader(commit_id)
            evidence.append(
                _build_ci_result_evidence(
                    commit_id=commit_id,
                    raw_result=ci_result,
                    evidence_id=_next_evidence_id(evidence),
                )
            )
        except CIResultError as exc:
            missing_evidence.append(
                MissingEvidence(
                    needed="该 commit 对应的 CI 运行结果",
                    reason=str(exc),
                    suggested_tool="get_ci_result",
                )
            )
        except (JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="CI 工具返回了无法标准化的数据",
            ) from exc

        try:
            diff = self._git_diff_reader(commit_id, workspace)
            if diff.strip():
                evidence.append(
                    Evidence(
                        evidence_id=_next_evidence_id(evidence),
                        kind=EvidenceKind.GIT_DIFF,
                        tool_name="git_diff",
                        source=commit_id,
                        locator="commit patch",
                        excerpt=_truncate_excerpt(diff),
                    )
                )
            else:
                missing_evidence.append(
                    MissingEvidence(
                        needed="该 commit 对应的代码改动",
                        reason="Git diff 未返回可用 patch",
                        suggested_tool="git_diff",
                    )
                )
        except GitDiffError as exc:
            missing_evidence.append(
                MissingEvidence(
                    needed="该 commit 对应的代码改动",
                    reason=str(exc),
                    suggested_tool="git_diff",
                )
            )

        return DiagnosisInput(
            report_id=report_id,
            commit_id=commit_id,
            workspace=workspace,
            evidence=evidence,
            missing_evidence=missing_evidence,
        )


def read_log_result(task_id: str, data_dir: str) -> str:
    """读取指定数据目录中的完整任务日志证据。"""
    return search_log(task_id, data_dir=data_dir)


class LocalLogEvidenceCollector:
    """使用本地结构化日志收集日志诊断证据。"""

    def __init__(
        self,
        *,
        log_result_reader: LogResultReader = read_log_result,
    ) -> None:
        self._log_result_reader = log_result_reader

    def collect(
        self,
        *,
        report_id: str,
        task_id: str,
        data_dir: str,
    ) -> LogDiagnosisInput:
        evidence: list[Evidence] = []
        missing_evidence: list[MissingEvidence] = []
        try:
            raw_result = self._log_result_reader(task_id, data_dir)
            payload = json.loads(raw_result)
            if payload["task_id"] != task_id:
                raise ValueError("日志结果中的 task_id 与请求不匹配")
            evidence.append(
                Evidence(
                    evidence_id="E1",
                    kind=EvidenceKind.LOG,
                    tool_name="search_log",
                    source=task_id,
                    locator=_build_log_locator(payload),
                    excerpt=_truncate_excerpt(raw_result),
                )
            )
            if payload.get("first_anomaly") is not None:
                # * 日志可以确认时间线，但没有代码或配置证据时不能把根因标为 confirmed。
                missing_evidence.append(
                    MissingEvidence(
                        needed="首个异常对应的代码、配置或依赖证据",
                        reason="日志只能证明异常时间线，不能单独确认代码根因",
                        suggested_tool="read_file",
                    )
                )
        except SearchLogError as exc:
            missing_evidence.append(
                MissingEvidence(
                    needed="该 task_id 对应的结构化日志",
                    reason=str(exc),
                    suggested_tool="search_log",
                )
            )
        except (JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="日志工具返回了无法标准化的数据",
            ) from exc

        return LogDiagnosisInput(
            report_id=report_id,
            task_id=task_id,
            workspace=data_dir,
            evidence=evidence,
            missing_evidence=missing_evidence,
        )


def _build_log_locator(payload: dict) -> str:
    summary = payload["summary"]
    first_anomaly = payload.get("first_anomaly")
    first_sequence = (
        first_anomaly.get("sequence_id") if isinstance(first_anomaly, dict) else None
    )
    return (
        f"task_id={payload['task_id']};"
        f"first_anomaly_sequence_id={first_sequence or 'none'};"
        f"entries={summary['total_entry_count']}"
    )


def _build_ci_result_evidence(
    *,
    commit_id: str,
    raw_result: str,
    evidence_id: str,
) -> Evidence:
    ci_payload = json.loads(raw_result)
    excerpt = json.dumps(
        {
            "status": ci_payload["status"],
            "failed_jobs": ci_payload["failed_jobs"],
            "core_log": ci_payload["core_log"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return Evidence(
        evidence_id=evidence_id,
        kind=EvidenceKind.CI_RESULT,
        tool_name="get_ci_result",
        source=ci_payload["pipeline_id"],
        locator=f"commit_id={commit_id}",
        excerpt=_truncate_excerpt(excerpt),
    )


def _truncate_excerpt(value: str) -> str:
    return value[:MAX_EVIDENCE_EXCERPT_CHARS]


def _next_evidence_id(evidence: list[Evidence]) -> str:
    return f"E{len(evidence) + 1}"


class DiagnosisService:
    """协调证据采集、模型调用和诊断报告校验。"""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        ci_evidence_collector: CIEvidenceCollector,
        log_evidence_collector: LogEvidenceCollector | None = None,
        report_id_factory: ReportIdFactory | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._ci_evidence_collector = ci_evidence_collector
        self._log_evidence_collector = log_evidence_collector
        self._report_id_factory = report_id_factory or (lambda: str(uuid4()))

    def diagnose_ci(
        self,
        *,
        commit_id: str,
        workspace: str = ".",
    ) -> DiagnosisReport:
        report_id = self._report_id_factory()
        diagnosis_input = self._ci_evidence_collector.collect(
            report_id=report_id,
            commit_id=commit_id,
            workspace=workspace,
        )
        draft = self._generate_draft(
            system_prompt=CI_DIAGNOSIS_SYSTEM_PROMPT,
            user_prompt=build_ci_diagnosis_prompt(diagnosis_input),
        )
        return self._bind_report(
            draft=draft,
            report_id=diagnosis_input.report_id,
            scenario=DiagnosisScenario.CI_FAILURE,
            target=diagnosis_input.commit_id,
            evidence=diagnosis_input.evidence,
        )

    def diagnose_log(
        self,
        *,
        task_id: str,
        data_dir: str = "examples/sample_logs",
    ) -> DiagnosisReport:
        if self._log_evidence_collector is None:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.CONFIGURATION_ERROR,
                message="日志诊断证据采集器未配置",
            )
        report_id = self._report_id_factory()
        diagnosis_input = self._log_evidence_collector.collect(
            report_id=report_id,
            task_id=task_id,
            data_dir=data_dir,
        )
        draft = self._generate_draft(
            system_prompt=LOG_DIAGNOSIS_SYSTEM_PROMPT,
            user_prompt=build_log_diagnosis_prompt(diagnosis_input),
        )
        return self._bind_report(
            draft=draft,
            report_id=diagnosis_input.report_id,
            scenario=DiagnosisScenario.LOG_FAILURE,
            target=diagnosis_input.task_id,
            evidence=diagnosis_input.evidence,
        )

    def _generate_draft(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> DiagnosisReportDraft:
        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ]

        try:
            response = self._llm_client.chat(messages)
        except Exception as exc:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.LLM_CALL_FAILED,
                message="调用诊断模型失败",
            ) from exc

        return self._parse_report(response)

    @staticmethod
    def _parse_report(response: LLMResponse) -> DiagnosisReportDraft:
        if response.response_type != LLMResponseType.FINAL_ANSWER:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.UNEXPECTED_LLM_RESPONSE,
                message="诊断模型必须返回 final_answer",
            )
        if not response.content or not response.content.strip():
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.EMPTY_LLM_RESPONSE,
                message="诊断模型返回的内容为空",
            )
        try:
            return DiagnosisReportDraft.model_validate_json(response.content)
        except ValidationError as exc:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.INVALID_REPORT,
                message="模型返回的诊断报告不符合契约",
            ) from exc

    @staticmethod
    def _bind_report(
        *,
        draft: DiagnosisReportDraft,
        report_id: str,
        scenario: DiagnosisScenario,
        target: str,
        evidence: list[Evidence],
    ) -> DiagnosisReport:
        try:
            return DiagnosisReport.model_validate(
                {
                    **draft.model_dump(),
                    "report_id": report_id,
                    "scenario": scenario,
                    "target": target,
                    "evidence": evidence,
                }
            )
        except ValidationError as exc:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.INVALID_REPORT,
                message="模型返回的诊断内容无法绑定到输入证据",
            ) from exc
