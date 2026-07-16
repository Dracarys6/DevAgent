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
    build_ci_diagnosis_prompt,
)
from devagent.tools.ci_tools import CIResultError, get_ci_result
from devagent.tools.git_tools import GitDiffError, git_diff

from .models import (
    DiagnosisInput,
    DiagnosisReport,
    DiagnosisScenario,
    Evidence,
    EvidenceKind,
    MissingEvidence,
)

MAX_EVIDENCE_EXCERPT_CHARS = 4_000
ReportIdFactory = Callable[[], str]
CIResultReader = Callable[[str], str]
GitDiffReader = Callable[[str, str], str]


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


class LocalCIEvidenceCollector:
    """使用本地 CI 数据和 Git 仓库收集 CI 诊断证据。"""

    def __init__(
        self,
        *,
        ci_result_reader: CIResultReader = get_ci_result,
        git_diff_reader: GitDiffReader = git_diff,
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
        report_id_factory: ReportIdFactory | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._ci_evidence_collector = ci_evidence_collector
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
        messages = [
            {
                "role": "system",
                "content": CI_DIAGNOSIS_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": build_ci_diagnosis_prompt(diagnosis_input),
            },
        ]

        try:
            response = self._llm_client.chat(messages)
        except Exception as exc:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.LLM_CALL_FAILED,
                message="调用诊断模型失败",
            ) from exc

        report = self._parse_report(response)
        self._validate_ci_report(
            report=report,
            diagnosis_input=diagnosis_input,
        )
        return report

    @staticmethod
    def _parse_report(response: LLMResponse) -> DiagnosisReport:
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
            return DiagnosisReport.model_validate_json(response.content)
        except ValidationError as exc:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.INVALID_REPORT,
                message="模型返回的诊断报告不符合契约",
            ) from exc

    @staticmethod
    def _validate_ci_report(
        *,
        report: DiagnosisReport,
        diagnosis_input: DiagnosisInput,
    ) -> None:
        expected_fields = {
            "report_id": (report.report_id, diagnosis_input.report_id),
            "scenario": (report.scenario, DiagnosisScenario.CI_FAILURE),
            "target": (report.target, diagnosis_input.commit_id),
            "evidence": (report.evidence, diagnosis_input.evidence),
        }
        for field, (actual, expected) in expected_fields.items():
            if actual != expected:
                raise DiagnosisServiceError(
                    code=DiagnosisServiceErrorCode.REPORT_MISMATCH,
                    message=f"诊断报告的 {field} 字段与输入不匹配",
                )
