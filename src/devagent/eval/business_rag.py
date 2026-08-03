import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.diagnosis import Evidence, EvidenceKind, MissingEvidence

MIN_CONTEXT_REDUCTION_RATE = 0.40
_KNOWLEDGE_LOCATOR_PATTERN = re.compile(
    r"^path=(?P<path>[^;]+);"
    r"lines=(?P<start>[1-9][0-9]*)-(?P<end>[1-9][0-9]*);"
    r"chunk_id=(?P<chunk_id>[^;]+);"
    r"rank=(?P<rank>[1-9][0-9]*)$"
)


class BusinessRAGModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class BusinessRAGCase(BusinessRAGModel):
    case_id: str = Field(min_length=1, max_length=128)
    scenario: str = Field(min_length=1, max_length=64)
    baseline_context_chars: int = Field(ge=1)
    evidence: list[Evidence] = Field(min_length=1)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class BusinessRAGCaseMetrics(BusinessRAGModel):
    case_id: str
    scenario: str
    baseline_context_chars: int = Field(ge=1)
    optimized_context_chars: int = Field(ge=1)
    domain_evidence_chars: int = Field(ge=1)
    retrieval_evidence_chars: int = Field(ge=0)
    retrieval_evidence_count: int = Field(ge=0)
    complete_locator_count: int = Field(ge=0)
    duplicate_location_count: int = Field(ge=0)
    retrieval_fallback_recorded: bool = Field(strict=True)
    context_reduction_rate: float = Field(le=1)
    domain_flow_available: bool = Field(strict=True)


class BusinessRAGMetrics(BusinessRAGModel):
    case_count: int = Field(ge=1)
    retrieval_case_count: int = Field(ge=1)
    retrieval_evidence_count: int = Field(ge=1)
    average_context_reduction_rate: float = Field(le=1)
    retrieval_locator_completeness_rate: float = Field(ge=0, le=1)
    domain_flow_availability_rate: float = Field(ge=0, le=1)
    duplicate_location_count: int = Field(ge=0)
    fallback_case_count: int = Field(ge=0)
    passed: bool = Field(strict=True)


class BusinessRAGEvalRun(BusinessRAGModel):
    metrics: BusinessRAGMetrics
    cases: list[BusinessRAGCaseMetrics] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_count(self) -> "BusinessRAGEvalRun":
        if self.metrics.case_count != len(self.cases):
            raise ValueError("metrics.case_count 与 cases 数量不一致")
        return self


def evaluate_business_rag(cases: list[BusinessRAGCase]) -> BusinessRAGEvalRun:
    """评估业务检索的上下文成本、定位、去重和降级可用性。"""
    if not cases:
        raise ValueError("Business RAG eval cases 不能为空")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Business RAG case_id 不能重复")

    case_metrics = [_evaluate_case(case) for case in cases]
    retrieval_evidence_count = sum(
        item.retrieval_evidence_count for item in case_metrics
    )
    if retrieval_evidence_count == 0:
        raise ValueError("Business RAG eval 至少需要一条检索 evidence")
    complete_locator_count = sum(item.complete_locator_count for item in case_metrics)
    duplicate_location_count = sum(
        item.duplicate_location_count for item in case_metrics
    )
    average_reduction = sum(item.context_reduction_rate for item in case_metrics) / len(
        case_metrics
    )
    locator_rate = complete_locator_count / retrieval_evidence_count
    domain_availability_rate = sum(
        item.domain_flow_available for item in case_metrics
    ) / len(case_metrics)
    passed = all(
        (
            average_reduction >= MIN_CONTEXT_REDUCTION_RATE,
            locator_rate == 1,
            domain_availability_rate == 1,
            duplicate_location_count == 0,
        )
    )
    return BusinessRAGEvalRun(
        metrics=BusinessRAGMetrics(
            case_count=len(case_metrics),
            retrieval_case_count=sum(
                item.retrieval_evidence_count > 0 for item in case_metrics
            ),
            retrieval_evidence_count=retrieval_evidence_count,
            average_context_reduction_rate=average_reduction,
            retrieval_locator_completeness_rate=locator_rate,
            domain_flow_availability_rate=domain_availability_rate,
            duplicate_location_count=duplicate_location_count,
            fallback_case_count=sum(
                item.retrieval_fallback_recorded for item in case_metrics
            ),
            passed=passed,
        ),
        cases=case_metrics,
    )


def _evaluate_case(case: BusinessRAGCase) -> BusinessRAGCaseMetrics:
    domain_evidence = [
        item for item in case.evidence if item.kind != EvidenceKind.KNOWLEDGE
    ]
    retrieval_evidence = [
        item for item in case.evidence if item.kind == EvidenceKind.KNOWLEDGE
    ]
    if not domain_evidence:
        raise ValueError(f"{case.case_id} 缺少领域权威 evidence")
    optimized_chars = sum(len(item.excerpt) for item in case.evidence)
    domain_chars = sum(len(item.excerpt) for item in domain_evidence)
    retrieval_chars = optimized_chars - domain_chars
    locations: list[tuple[str, str, str]] = []
    complete_locator_count = 0
    for item in retrieval_evidence:
        match = _KNOWLEDGE_LOCATOR_PATTERN.fullmatch(item.locator)
        if match is None:
            continue
        complete_locator_count += 1
        locations.append(
            (
                item.source,
                match.group("path"),
                f"{match.group('start')}-{match.group('end')}",
            )
        )
    duplicate_count = len(locations) - len(set(locations))
    return BusinessRAGCaseMetrics(
        case_id=case.case_id,
        scenario=case.scenario,
        baseline_context_chars=case.baseline_context_chars,
        optimized_context_chars=optimized_chars,
        domain_evidence_chars=domain_chars,
        retrieval_evidence_chars=retrieval_chars,
        retrieval_evidence_count=len(retrieval_evidence),
        complete_locator_count=complete_locator_count,
        duplicate_location_count=duplicate_count,
        retrieval_fallback_recorded=any(
            item.suggested_tool == "knowledge_retrieve"
            for item in case.missing_evidence
        ),
        context_reduction_rate=(1 - optimized_chars / case.baseline_context_chars),
        domain_flow_available=bool(domain_evidence),
    )


def render_business_rag_report(
    run: BusinessRAGEvalRun,
    *,
    generated_at: str,
    revision: str,
) -> str:
    """渲染不包含工作区正文的业务检索指标报告。"""
    metrics = run.metrics
    lines = [
        "# Business RAG Evaluation",
        "",
        f"- Generated at: `{generated_at}`",
        f"- DevAgent revision: `{revision}`",
        "- Baseline: domain evidence + all indexable workspace document text",
        "- Optimized: actual bounded domain and retrieved Evidence excerpts",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Cases | {metrics.case_count} |",
        f"| Retrieval Evidence | {metrics.retrieval_evidence_count} |",
        (
            "| Average Context Reduction | "
            f"{metrics.average_context_reduction_rate * 100:.1f}% |"
        ),
        (
            "| Retrieval Locator Completeness | "
            f"{metrics.retrieval_locator_completeness_rate * 100:.1f}% |"
        ),
        (
            "| Domain Flow Availability | "
            f"{metrics.domain_flow_availability_rate * 100:.1f}% |"
        ),
        f"| Duplicate Locations | {metrics.duplicate_location_count} |",
        f"| Fallback Cases | {metrics.fallback_case_count} |",
        f"| Passed | {metrics.passed} |",
        "",
        "## Cases",
        "",
        "| Case | Scenario | Baseline | Optimized | Reduction | Retrieved |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        (
            f"| {case.case_id} | {case.scenario} | "
            f"{case.baseline_context_chars} | {case.optimized_context_chars} | "
            f"{case.context_reduction_rate * 100:.1f}% | "
            f"{case.retrieval_evidence_count} |"
        )
        for case in run.cases
    )
    lines.extend(
        [
            "",
            (
                "This deterministic report measures evidence context and metadata. "
                "Generated-answer quality requires the separate live-provider business run."
            ),
            "",
        ]
    )
    return "\n".join(lines)
