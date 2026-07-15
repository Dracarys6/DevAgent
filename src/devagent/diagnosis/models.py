from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvidenceId = Annotated[str, Field(pattern=r"^E[1-9][0-9]*$")]
NonEmptyText = Annotated[str, Field(min_length=1)]


class DiagnosisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceKind(str, Enum):
    CI_RESULT = "ci_result"
    CODE = "code"
    GIT_DIFF = "git_diff"
    LOG = "log"
    USER_INPUT = "user_input"


class Evidence(DiagnosisModel):
    evidence_id: EvidenceId
    kind: EvidenceKind
    tool_name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    excerpt: str = Field(min_length=1, max_length=4_000)


class FindingKind(str, Enum):
    SYMPTOM = "symptom"
    ROOT_CAUSE = "root_cause"
    RELATED_CHANGE = "related_change"
    ENVIRONMENT = "environment"


class Confidence(str, Enum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    UNKNOWN = "unknown"


class Finding(DiagnosisModel):
    kind: FindingKind
    statement: str = Field(min_length=1, max_length=1_000)
    confidence: Confidence
    evidence_ids: list[EvidenceId] = Field(min_length=1)


class Recommendation(DiagnosisModel):
    action: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[EvidenceId] = Field(min_length=1)
    verification_steps: list[NonEmptyText] = Field(min_length=1, max_length=8)


class MissingEvidence(DiagnosisModel):
    needed: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    suggested_tool: str | None = Field(default=None, min_length=1)


class DiagnosisStatus(str, Enum):
    DIAGNOSED = "diagnosed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DiagnosisScenario(str, Enum):
    CI_FAILURE = "ci_failure"
    LOG_FAILURE = "log_failure"


class DiagnosisReport(DiagnosisModel):
    report_id: str = Field(min_length=1)
    scenario: DiagnosisScenario = DiagnosisScenario.CI_FAILURE
    target: str = Field(min_length=1)
    status: DiagnosisStatus
    summary: str = Field(min_length=1, max_length=2_000)
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_references(self) -> "DiagnosisReport":
        known_ids = [item.evidence_id for item in self.evidence]
        _validate_unique_evidence_ids(known_ids)

        known_id_set = set(known_ids)
        references = [
            evidence_id
            for finding in self.findings
            for evidence_id in finding.evidence_ids
        ]
        references.extend(
            evidence_id
            for recommendation in self.recommendations
            for evidence_id in recommendation.evidence_ids
        )
        dangling_ids = sorted(set(references) - known_id_set)
        if dangling_ids:
            raise ValueError(f"引用了不存在的 evidence_id: {dangling_ids}")
        if self.status == DiagnosisStatus.DIAGNOSED and not self.findings:
            raise ValueError("已诊断报告至少需要一条 finding")
        if (
            self.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
            and not self.missing_evidence
        ):
            raise ValueError("证据不足报告必须说明 missing_evidence")
        return self


class DiagnosisInput(DiagnosisModel):
    report_id: str = Field(min_length=1)
    commit_id: str = Field(min_length=1)
    workspace: str = Field(default=".", min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_evidence_ids(self) -> "DiagnosisInput":
        _validate_unique_evidence_ids(
            [item.evidence_id for item in self.evidence]
        )
        return self


class LogDiagnosisInput(DiagnosisModel):
    report_id: str = Field(min_length=1)
    task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    workspace: str = Field(default=".", min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_evidence_ids(self) -> "LogDiagnosisInput":
        _validate_unique_evidence_ids(
            [item.evidence_id for item in self.evidence]
        )
        return self


def _validate_unique_evidence_ids(evidence_ids: list[str]) -> None:
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence_id 不能重复")
