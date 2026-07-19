from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from devagent.diagnosis.models import Evidence, EvidenceId, MissingEvidence

# * Annotated 为基础类型附加可复用的 Pydantic 校验规则。
NonEmptyText = Annotated[str, Field(min_length=1)]
FindingId = Annotated[str, Field(pattern=r"^R[1-9][0-9]*$")]  # * 以 R 开头


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")  # * 拒绝模型返回未知字段


class ReviewSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewCategory(str, Enum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    COMPATIBILITY = "compatibility"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    TEST_GAP = "test_gap"  # * 是否缺少必要测试


class ReviewStatus(str, Enum):
    REVIEWED = "reviewed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ReviewLineSide(str, Enum):
    BASE = "base"  # * 问题定位在被删除或被替换的旧代码侧
    HEAD = "head"  # * 问题定位在新增或修改后的目标代码侧


class ReviewFinding(ReviewModel):
    finding_id: FindingId
    severity: ReviewSeverity
    category: ReviewCategory
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    file_path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(ge=1)
    line_end: int | None = Field(default=None, ge=1)
    side: ReviewLineSide = ReviewLineSide.HEAD
    evidence_ids: list[EvidenceId] = Field(default_factory=list, min_length=1)
    suggestion: str = Field(min_length=1, max_length=2000)
    verification_steps: list[NonEmptyText] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_line_range(self) -> "ReviewFinding":
        if self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end 不能小于 line_start")
        return self

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        """要求 finding 定位到仓库内的 POSIX 相对路径。"""
        if value != value.strip():
            raise ValueError("file_path 不能包含首尾空白")
        path = PurePosixPath(value)
        if value in {"", "."} or path.is_absolute() or ".." in path.parts:
            raise ValueError("file_path 必须是仓库内相对路径")
        if "\\" in value:
            raise ValueError("file_path 必须使用 POSIX 风格的路径分隔符 '/'")
        return value


class CodeReviewInput(ReviewModel):
    """代码评审输入"""

    review_id: str = Field(min_length=1)
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    workspace: str = Field(default=".", min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_input(self) -> "CodeReviewInput":
        _validate_distinct_refs(self.base_ref, self.head_ref)
        _validate_unique_values([e.evidence_id for e in self.evidence], "evidence_id")
        return self


def _validate_unique_values(values: list[str], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} 必须唯一")


def _validate_distinct_refs(base_ref: str, head_ref: str) -> None:
    if base_ref != base_ref.strip() or head_ref != head_ref.strip():
        raise ValueError("base_ref 和 head_ref 不能包含首尾空白")
    if base_ref == head_ref:
        raise ValueError("base_ref 和 head_ref 不能相同")


class CodeReviewReport(ReviewModel):
    """代码评审报告"""

    review_id: str = Field(min_length=1)
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    status: ReviewStatus
    summary: str = Field(min_length=1, max_length=2000)
    findings: list[ReviewFinding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report(self) -> "CodeReviewReport":
        _validate_distinct_refs(self.base_ref, self.head_ref)

        evidence_ids = [e.evidence_id for e in self.evidence]
        _validate_unique_values(evidence_ids, "evidence_id")

        finding_ids = [f.finding_id for f in self.findings]
        _validate_unique_values(finding_ids, "finding_id")

        known_evidence_ids = {e.evidence_id for e in self.evidence}
        referenced_evidence_ids = {
            evidence_id
            for finding in self.findings
            for evidence_id in finding.evidence_ids
        }
        dangling_ids = sorted(referenced_evidence_ids - known_evidence_ids)
        if dangling_ids:
            raise ValueError(f"引用了不存在的 evidence_id: {dangling_ids}")

        if (
            self.status == ReviewStatus.INSUFFICIENT_EVIDENCE
            and not self.missing_evidence
        ):
            raise ValueError("证据不足报告必须说明 missing_evidence")
        return self
