from collections.abc import Callable
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.diagnosis import (
    CIEvidenceCollector,
    DiagnosisReport,
    DiagnosisService,
    DiagnosisServiceError,
    DiagnosisStatus,
    EvidenceKind,
    FindingKind,
    LocalCIEvidenceCollector,
)
from devagent.llm import LLMClient

MAX_LIVE_DIAGNOSIS_ATTEMPTS = 3
LiveDiagnosisClientFactory = Callable[[], LLMClient]


class LiveCIDiagnosisModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class LiveCIDiagnosisMetrics(LiveCIDiagnosisModel):
    diagnosed: bool = Field(strict=True)
    required_evidence_covered: bool = Field(strict=True)
    evidence_references_grounded: bool = Field(strict=True)
    root_cause_finding_count: int = Field(ge=0)
    recommendation_count: int = Field(ge=0)
    expected_keyword_hit_count: int = Field(ge=0)
    expected_keyword_count: int = Field(ge=1)
    expected_keyword_hit_rate: float = Field(ge=0, le=1)
    passed: bool = Field(strict=True)


class LiveCIDiagnosisRun(LiveCIDiagnosisModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    api_mode: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=255)
    workspace_label: str = Field(min_length=1, max_length=500)
    expected_keywords: list[str] = Field(min_length=1, max_length=20)
    latency_ms: float = Field(ge=0)
    attempt_count: int = Field(ge=1, le=MAX_LIVE_DIAGNOSIS_ATTEMPTS)
    attempt_errors: list[str] = Field(default_factory=list)
    report: DiagnosisReport | None = None
    metrics: LiveCIDiagnosisMetrics

    @model_validator(mode="after")
    def validate_run_shape(self) -> "LiveCIDiagnosisRun":
        if self.metrics.passed and self.report is None:
            raise ValueError("通过的 CI live evaluation 必须包含诊断报告")
        return self


def run_live_ci_diagnosis(
    *,
    llm_client_factory: LiveDiagnosisClientFactory,
    commit_id: str,
    workspace: str,
    workspace_label: str,
    provider: str,
    model: str,
    api_mode: str,
    expected_keywords: list[str],
    ci_evidence_collector: CIEvidenceCollector | None = None,
    max_attempts: int = 2,
) -> LiveCIDiagnosisRun:
    """通过真实诊断服务执行固定 CI case，并计算可重复验收指标。"""
    if (
        isinstance(max_attempts, bool)
        or max_attempts < 1
        or max_attempts > MAX_LIVE_DIAGNOSIS_ATTEMPTS
    ):
        raise ValueError(f"max_attempts 必须在 1 到 {MAX_LIVE_DIAGNOSIS_ATTEMPTS} 之间")
    normalized_keywords = _validate_expected_keywords(expected_keywords)
    collector = ci_evidence_collector or LocalCIEvidenceCollector()
    attempt_errors: list[str] = []
    report: DiagnosisReport | None = None
    started_at = perf_counter()

    for attempt in range(1, max_attempts + 1):
        service = DiagnosisService(
            llm_client=llm_client_factory(),
            ci_evidence_collector=collector,
        )
        try:
            report = service.diagnose_ci(
                commit_id=commit_id,
                workspace=workspace,
            )
            attempt_count = attempt
            break
        except DiagnosisServiceError as exc:
            attempt_errors.append(exc.code.value)
    else:
        attempt_count = max_attempts

    latency_ms = (perf_counter() - started_at) * 1000
    metrics = evaluate_live_ci_diagnosis(report, normalized_keywords)
    return LiveCIDiagnosisRun(
        provider=provider,
        model=model,
        api_mode=api_mode,
        target=commit_id,
        workspace_label=workspace_label,
        expected_keywords=normalized_keywords,
        latency_ms=latency_ms,
        attempt_count=attempt_count,
        attempt_errors=attempt_errors,
        report=report,
        metrics=metrics,
    )


def evaluate_live_ci_diagnosis(
    report: DiagnosisReport | None,
    expected_keywords: list[str],
) -> LiveCIDiagnosisMetrics:
    """对结构化报告的证据覆盖、引用完整性和关键根因事实评分。"""
    normalized_keywords = _validate_expected_keywords(expected_keywords)
    if report is None:
        return LiveCIDiagnosisMetrics(
            diagnosed=False,
            required_evidence_covered=False,
            evidence_references_grounded=False,
            root_cause_finding_count=0,
            recommendation_count=0,
            expected_keyword_hit_count=0,
            expected_keyword_count=len(normalized_keywords),
            expected_keyword_hit_rate=0,
            passed=False,
        )

    evidence_ids = {item.evidence_id for item in report.evidence}
    referenced_ids = {
        evidence_id
        for finding in report.findings
        for evidence_id in finding.evidence_ids
    }
    referenced_ids.update(
        evidence_id
        for recommendation in report.recommendations
        for evidence_id in recommendation.evidence_ids
    )
    evidence_kinds = {item.kind for item in report.evidence}
    required_evidence_covered = {
        EvidenceKind.CI_RESULT,
        EvidenceKind.GIT_DIFF,
    } <= evidence_kinds
    evidence_references_grounded = bool(referenced_ids) and (
        referenced_ids <= evidence_ids
    )
    root_cause_finding_count = sum(
        item.kind == FindingKind.ROOT_CAUSE for item in report.findings
    )
    searchable_text = " ".join(
        [
            report.summary,
            *(item.statement for item in report.findings),
            *(item.action for item in report.recommendations),
            *(item.rationale for item in report.recommendations),
        ]
    ).casefold()
    keyword_hit_count = sum(
        keyword.casefold() in searchable_text for keyword in normalized_keywords
    )
    diagnosed = report.status == DiagnosisStatus.DIAGNOSED
    passed = all(
        (
            diagnosed,
            required_evidence_covered,
            evidence_references_grounded,
            root_cause_finding_count > 0,
            bool(report.recommendations),
            keyword_hit_count == len(normalized_keywords),
        )
    )
    return LiveCIDiagnosisMetrics(
        diagnosed=diagnosed,
        required_evidence_covered=required_evidence_covered,
        evidence_references_grounded=evidence_references_grounded,
        root_cause_finding_count=root_cause_finding_count,
        recommendation_count=len(report.recommendations),
        expected_keyword_hit_count=keyword_hit_count,
        expected_keyword_count=len(normalized_keywords),
        expected_keyword_hit_rate=keyword_hit_count / len(normalized_keywords),
        passed=passed,
    )


def render_live_ci_diagnosis_report(
    run: LiveCIDiagnosisRun,
    *,
    generated_at: str,
    commit_id: str,
) -> str:
    """渲染不包含凭据和本机绝对路径的真实 CI 诊断验收报告。"""
    metrics = run.metrics
    report = run.report
    lines = [
        "# Live CI Diagnosis Evaluation",
        "",
        f"- Generated at: `{generated_at}`",
        f"- DevAgent commit: `{commit_id}`",
        f"- Provider: `{run.provider}`",
        f"- Model: `{run.model}`",
        f"- API mode: `{run.api_mode}`",
        f"- Target: `{run.target}`",
        f"- Workspace: `{run.workspace_label}`",
        f"- Latency: {run.latency_ms:.2f} ms",
        f"- Attempts: {run.attempt_count}",
        f"- Attempt errors: {_render_values(run.attempt_errors)}",
        "",
        "## Acceptance Metrics",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Diagnosed | {metrics.diagnosed} |",
        f"| CI + Git Evidence Covered | {metrics.required_evidence_covered} |",
        f"| Evidence References Grounded | {metrics.evidence_references_grounded} |",
        f"| Root Cause Findings | {metrics.root_cause_finding_count} |",
        f"| Recommendations | {metrics.recommendation_count} |",
        (
            "| Expected Keyword Hit Rate | "
            f"{metrics.expected_keyword_hit_rate * 100:.1f}% "
            f"({metrics.expected_keyword_hit_count}/{metrics.expected_keyword_count}) |"
        ),
        f"| End-to-End Passed | {metrics.passed} |",
        "",
    ]
    if report is not None:
        lines.extend(
            [
                "## Diagnosis Result",
                "",
                f"- Report ID: `{report.report_id}`",
                f"- Status: `{report.status.value}`",
                f"- Evidence: {_render_values([item.evidence_id for item in report.evidence])}",
                "",
                "### Summary",
                "",
                report.summary,
                "",
                "### Findings",
                "",
                *[
                    (
                        f"- `{finding.kind.value}` / `{finding.confidence.value}` "
                        f"[{', '.join(finding.evidence_ids)}]: {finding.statement}"
                    )
                    for finding in report.findings
                ],
                "",
                "### Recommendations",
                "",
                *[
                    (
                        f"- [{', '.join(item.evidence_ids)}] {item.action} "
                        f"Reason: {item.rationale}"
                    )
                    for item in report.recommendations
                ],
                "",
            ]
        )
    lines.extend(
        [
            "## Acceptance Boundary",
            "",
            (
                "This report was produced by a live LLM provider through "
                "DiagnosisService, the real CI fixture reader, and a code-only Git diff."
            ),
            (
                "The fixed case checks structured output, evidence coverage, grounded "
                "references, root-cause facts, recommendations, retries, and latency."
            ),
            (
                "It validates this listed case and provider run; it does not claim "
                "universal diagnosis accuracy."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _validate_expected_keywords(expected_keywords: list[str]) -> list[str]:
    normalized = [keyword.strip() for keyword in expected_keywords]
    if (
        not normalized
        or any(not keyword for keyword in normalized)
        or len(normalized) != len(set(normalized))
    ):
        raise ValueError("expected_keywords 必须是非空且不重复的字符串")
    return normalized


def _render_values(values: list[str]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{value}`" for value in values)
