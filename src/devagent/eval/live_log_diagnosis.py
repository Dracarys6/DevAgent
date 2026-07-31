from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.diagnosis import (
    Confidence,
    DiagnosisReport,
    DiagnosisService,
    DiagnosisServiceError,
    DiagnosisStatus,
    EvidenceKind,
    FindingKind,
    LocalCIEvidenceCollector,
    LocalLogEvidenceCollector,
)
from devagent.llm import LLMClient

MAX_LIVE_LOG_DIAGNOSIS_ATTEMPTS = 3
LiveLogDiagnosisClientFactory = Callable[[], LLMClient]


class LiveLogDiagnosisModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class LiveLogDiagnosisMetrics(LiveLogDiagnosisModel):
    diagnosed: bool = Field(strict=True)
    log_evidence_covered: bool = Field(strict=True)
    evidence_references_grounded: bool = Field(strict=True)
    first_anomaly_identified: bool = Field(strict=True)
    cascade_error_identified: bool = Field(strict=True)
    confirmed_root_cause_count: int = Field(ge=0)
    code_evidence_gap_recorded: bool = Field(strict=True)
    recommendation_count: int = Field(ge=0)
    expected_keyword_hit_count: int = Field(ge=0)
    expected_keyword_count: int = Field(ge=1)
    expected_keyword_hit_rate: float = Field(ge=0, le=1)
    passed: bool = Field(strict=True)


class LiveLogDiagnosisRun(LiveLogDiagnosisModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    api_mode: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=128)
    data_dir_label: str = Field(min_length=1, max_length=500)
    expected_keywords: list[str] = Field(min_length=1, max_length=20)
    latency_ms: float = Field(ge=0)
    attempt_count: int = Field(ge=1, le=MAX_LIVE_LOG_DIAGNOSIS_ATTEMPTS)
    attempt_errors: list[str] = Field(default_factory=list)
    report: DiagnosisReport | None = None
    metrics: LiveLogDiagnosisMetrics

    @model_validator(mode="after")
    def validate_run_shape(self) -> "LiveLogDiagnosisRun":
        if self.metrics.passed and self.report is None:
            raise ValueError("通过的日志 live evaluation 必须包含诊断报告")
        return self


def run_live_log_diagnosis(
    *,
    llm_client_factory: LiveLogDiagnosisClientFactory,
    task_id: str,
    data_dir: str | Path,
    data_dir_label: str,
    provider: str,
    model: str,
    api_mode: str,
    expected_keywords: list[str],
    max_attempts: int = 2,
) -> LiveLogDiagnosisRun:
    """通过真实 DiagnosisService 执行固定日志诊断并评分。"""
    if (
        isinstance(max_attempts, bool)
        or max_attempts < 1
        or max_attempts > MAX_LIVE_LOG_DIAGNOSIS_ATTEMPTS
    ):
        raise ValueError(
            f"max_attempts 必须在 1 到 {MAX_LIVE_LOG_DIAGNOSIS_ATTEMPTS} 之间"
        )
    normalized_keywords = _validate_expected_keywords(expected_keywords)
    root = Path(data_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Live Log Diagnosis data_dir 不存在或不是目录")

    report: DiagnosisReport | None = None
    attempt_errors: list[str] = []
    started_at = perf_counter()
    for attempt in range(1, max_attempts + 1):
        service = DiagnosisService(
            llm_client=llm_client_factory(),
            ci_evidence_collector=LocalCIEvidenceCollector(),
            log_evidence_collector=LocalLogEvidenceCollector(),
        )
        try:
            report = service.diagnose_log(task_id=task_id, data_dir=str(root))
            attempt_count = attempt
            break
        except DiagnosisServiceError as exc:
            attempt_errors.append(exc.code.value)
    else:
        attempt_count = max_attempts

    latency_ms = (perf_counter() - started_at) * 1000
    if report is not None:
        report = _sanitize_report(report, root, data_dir_label)
    return LiveLogDiagnosisRun(
        provider=provider,
        model=model,
        api_mode=api_mode,
        target=task_id,
        data_dir_label=data_dir_label,
        expected_keywords=normalized_keywords,
        latency_ms=latency_ms,
        attempt_count=attempt_count,
        attempt_errors=attempt_errors,
        report=report,
        metrics=evaluate_live_log_diagnosis(report, normalized_keywords),
    )


def evaluate_live_log_diagnosis(
    report: DiagnosisReport | None,
    expected_keywords: list[str],
) -> LiveLogDiagnosisMetrics:
    """评分日志时间线、证据引用、根因置信边界和关键信息。"""
    normalized_keywords = _validate_expected_keywords(expected_keywords)
    if report is None:
        return _empty_metrics(normalized_keywords)

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
    evidence_references_grounded = bool(referenced_ids) and (
        referenced_ids <= evidence_ids
    )
    log_evidence_covered = EvidenceKind.LOG in {item.kind for item in report.evidence}
    finding_texts = [finding.statement.casefold() for finding in report.findings]
    first_anomaly_identified = any(
        "uploadtimeouterror" in statement for statement in finding_texts
    )
    cascade_error_identified = any(
        "retryexhaustederror" in statement for statement in finding_texts
    )
    confirmed_root_cause_count = sum(
        finding.kind == FindingKind.ROOT_CAUSE
        and finding.confidence == Confidence.CONFIRMED
        for finding in report.findings
    )
    code_evidence_gap_recorded = any(
        item.suggested_tool in {"read_file", "search_code"}
        for item in report.missing_evidence
    )
    searchable_text = " ".join(
        [
            report.summary,
            *(item.statement for item in report.findings),
            *(item.action for item in report.recommendations),
            *(item.rationale for item in report.recommendations),
        ]
    ).casefold()
    normalized_searchable_text = "".join(searchable_text.split())
    keyword_hits = sum(
        "".join(keyword.casefold().split()) in normalized_searchable_text
        for keyword in normalized_keywords
    )
    diagnosed = report.status == DiagnosisStatus.DIAGNOSED
    passed = all(
        (
            diagnosed,
            log_evidence_covered,
            evidence_references_grounded,
            first_anomaly_identified,
            cascade_error_identified,
            confirmed_root_cause_count == 0,
            code_evidence_gap_recorded,
            bool(report.recommendations),
            keyword_hits == len(normalized_keywords),
        )
    )
    return LiveLogDiagnosisMetrics(
        diagnosed=diagnosed,
        log_evidence_covered=log_evidence_covered,
        evidence_references_grounded=evidence_references_grounded,
        first_anomaly_identified=first_anomaly_identified,
        cascade_error_identified=cascade_error_identified,
        confirmed_root_cause_count=confirmed_root_cause_count,
        code_evidence_gap_recorded=code_evidence_gap_recorded,
        recommendation_count=len(report.recommendations),
        expected_keyword_hit_count=keyword_hits,
        expected_keyword_count=len(normalized_keywords),
        expected_keyword_hit_rate=keyword_hits / len(normalized_keywords),
        passed=passed,
    )


def render_live_log_diagnosis_report(
    run: LiveLogDiagnosisRun,
    *,
    generated_at: str,
    commit_id: str,
) -> str:
    """渲染不包含凭据和本机绝对路径的日志诊断验收报告。"""
    metrics = run.metrics
    lines = [
        "# Live Log Diagnosis Evaluation",
        "",
        f"- Generated at: `{generated_at}`",
        f"- DevAgent commit: `{commit_id}`",
        f"- Provider: `{run.provider}`",
        f"- Model: `{run.model}`",
        f"- API mode: `{run.api_mode}`",
        f"- Target: `{run.target}`",
        f"- Data dir: `{run.data_dir_label}`",
        f"- Latency: {run.latency_ms:.2f} ms",
        f"- Attempts: {run.attempt_count}",
        f"- Attempt errors: {_render_values(run.attempt_errors)}",
        "",
        "## Acceptance Metrics",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Diagnosed | {metrics.diagnosed} |",
        f"| Log Evidence Covered | {metrics.log_evidence_covered} |",
        f"| Evidence References Grounded | {metrics.evidence_references_grounded} |",
        f"| First Anomaly Identified | {metrics.first_anomaly_identified} |",
        f"| Cascade Error Identified | {metrics.cascade_error_identified} |",
        f"| Confirmed Root Causes | {metrics.confirmed_root_cause_count} |",
        f"| Code Evidence Gap Recorded | {metrics.code_evidence_gap_recorded} |",
        f"| Recommendations | {metrics.recommendation_count} |",
        (
            "| Expected Keyword Hit Rate | "
            f"{metrics.expected_keyword_hit_rate * 100:.1f}% "
            f"({metrics.expected_keyword_hit_count}/{metrics.expected_keyword_count}) |"
        ),
        f"| End-to-End Passed | {metrics.passed} |",
        "",
    ]
    if run.report is not None:
        lines.extend(
            [
                "## Diagnosis Result",
                "",
                f"- Report ID: `{run.report.report_id}`",
                f"- Status: `{run.report.status.value}`",
                f"- Evidence: {_render_values([item.evidence_id for item in run.report.evidence])}",
                "",
                "### Summary",
                "",
                run.report.summary,
                "",
                "### Findings",
                "",
                *[
                    (
                        f"- `{finding.kind.value}` / `{finding.confidence.value}` "
                        f"[{', '.join(finding.evidence_ids)}]: {finding.statement}"
                    )
                    for finding in run.report.findings
                ],
                "",
                "### Recommendations",
                "",
                *[
                    (
                        f"- [{', '.join(item.evidence_ids)}] {item.action} "
                        f"Reason: {item.rationale}"
                    )
                    for item in run.report.recommendations
                ],
                "",
                "### Missing Evidence",
                "",
                *[
                    (
                        f"- {item.needed}: {item.reason} "
                        f"Suggested tool: {item.suggested_tool or 'None'}"
                    )
                    for item in run.report.missing_evidence
                ],
                "",
            ]
        )
    lines.extend(
        [
            "## Acceptance Boundary",
            "",
            (
                "This report was produced by a live LLM provider through DiagnosisService "
                "and the real structured-log reader."
            ),
            (
                "The fixed case checks the first anomaly, cascade errors, evidence "
                "grounding, root-cause confidence, missing code evidence, recommendations, "
                "retries, and latency."
            ),
            (
                "It validates this listed task log and provider run rather than universal "
                "log diagnosis accuracy or a code-level confirmed root cause."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _sanitize_report(
    report: DiagnosisReport,
    data_dir: Path,
    data_dir_label: str,
) -> DiagnosisReport:
    payload = _replace_text(
        report.model_dump(mode="json"), str(data_dir), data_dir_label
    )
    return DiagnosisReport.model_validate(payload)


def _replace_text(value, target: str, replacement: str):
    if isinstance(value, str):
        return value.replace(target, replacement)
    if isinstance(value, list):
        return [_replace_text(item, target, replacement) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_text(item, target, replacement) for key, item in value.items()
        }
    return value


def _validate_expected_keywords(expected_keywords: list[str]) -> list[str]:
    normalized = [keyword.strip() for keyword in expected_keywords]
    if (
        not normalized
        or any(not keyword for keyword in normalized)
        or len(normalized) != len(set(normalized))
    ):
        raise ValueError("expected_keywords 必须是非空且不重复的字符串")
    return normalized


def _empty_metrics(expected_keywords: list[str]) -> LiveLogDiagnosisMetrics:
    return LiveLogDiagnosisMetrics(
        diagnosed=False,
        log_evidence_covered=False,
        evidence_references_grounded=False,
        first_anomaly_identified=False,
        cascade_error_identified=False,
        confirmed_root_cause_count=0,
        code_evidence_gap_recorded=False,
        recommendation_count=0,
        expected_keyword_hit_count=0,
        expected_keyword_count=len(expected_keywords),
        expected_keyword_hit_rate=0,
        passed=False,
    )


def _render_values(values: list[str]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{value}`" for value in values)
