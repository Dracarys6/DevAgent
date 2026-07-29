import json
from math import ceil
from pathlib import Path, PurePosixPath
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from devagent.memory import RetrievalResult
from devagent.tools import KnowledgeRetrieveTool, ToolRegistry


class RAGEvalConfigurationError(ValueError):
    """RAG Evaluation fixture 或 prediction 无法形成可信指标。"""


class RAGEvalModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class RAGEvalCase(RAGEvalModel):
    case_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=2_000)
    expected_tool_name: str = Field(
        default="knowledge_retrieve",
        min_length=1,
        max_length=100,
    )
    top_k: int = Field(default=5, ge=1, le=50, strict=True)
    expect_empty: bool = Field(default=False, strict=True)
    expected_paths: list[str] = Field(default_factory=list)
    expected_keywords: list[str] = Field(default_factory=list)

    @field_validator("expected_paths")
    @classmethod
    def validate_expected_paths(cls, values: list[str]) -> list[str]:
        validated = [_validate_relative_path(value) for value in values]
        if len(validated) != len(set(validated)):
            raise ValueError("expected_paths 不能重复")
        return validated

    @field_validator("expected_keywords")
    @classmethod
    def validate_expected_keywords(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("expected_keywords 不能包含空字符串")
        normalized = [value.casefold() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("expected_keywords 忽略大小写后不能重复")
        return values

    @model_validator(mode="after")
    def validate_expected_evidence(self) -> "RAGEvalCase":
        if self.expect_empty:
            if self.expected_paths or self.expected_keywords:
                raise ValueError("负样本不能声明 expected_paths 或 expected_keywords")
            return self
        if not self.expected_paths:
            raise ValueError("正样本至少需要一个 expected_path")
        if not self.expected_keywords:
            raise ValueError("正样本至少需要一个 expected_keyword")
        return self


class RAGEvalPrediction(RAGEvalModel):
    case_id: str = Field(min_length=1, max_length=100)
    predicted_tool_name: str = Field(min_length=1, max_length=100)
    tool_success: bool = Field(strict=True)
    retrieval_result: RetrievalResult | None = None
    answer_text: str = ""
    latency_ms: float = Field(ge=0)
    error_code: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_tool_outcome(self) -> "RAGEvalPrediction":
        if self.tool_success:
            if self.retrieval_result is None:
                raise ValueError("成功 prediction 必须包含 retrieval_result")
            if self.error_code is not None:
                raise ValueError("成功 prediction 不能包含 error_code")
            return self
        if self.retrieval_result is not None:
            raise ValueError("失败 prediction 不能包含 retrieval_result")
        if self.error_code is None:
            raise ValueError("失败 prediction 必须包含 error_code")
        return self


class RAGEvalMetrics(RAGEvalModel):
    case_count: int = Field(ge=1)
    positive_case_count: int = Field(ge=1)
    negative_case_count: int = Field(ge=1)
    tool_hit_count: int = Field(ge=0)
    evidence_hit_count: int = Field(ge=0)
    matched_answer_keyword_count: int = Field(ge=0)
    expected_answer_keyword_count: int = Field(ge=1)
    correct_empty_count: int = Field(ge=0)
    located_evidence_count: int = Field(ge=0)
    returned_evidence_count: int = Field(ge=0)
    tool_hit_rate: float = Field(ge=0, le=1)
    evidence_hit_rate: float = Field(ge=0, le=1)
    answer_keyword_hit_rate: float = Field(ge=0, le=1)
    empty_result_accuracy: float = Field(ge=0, le=1)
    evidence_location_completeness: float = Field(ge=0, le=1)
    average_latency_ms: float = Field(ge=0)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    failed_tool_case_ids: list[str]
    missed_evidence_case_ids: list[str]
    missing_answer_keywords: list[str]
    incorrect_non_empty_case_ids: list[str]


class RAGEvalRun(RAGEvalModel):
    metrics: RAGEvalMetrics
    predictions: list[RAGEvalPrediction] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_count(self) -> "RAGEvalRun":
        if self.metrics.case_count != len(self.predictions):
            raise ValueError("metrics.case_count 必须等于 predictions 数量")
        return self


def load_rag_eval_cases(case_dir: str | Path) -> list[RAGEvalCase]:
    """稳定加载并验证一个 RAG Evaluation case 集。"""
    root = Path(case_dir).expanduser().resolve()
    if not root.is_dir():
        raise RAGEvalConfigurationError("RAG eval case 目录不存在")

    cases: list[RAGEvalCase] = []
    for path in sorted(root.glob("*.json")):
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
            items = decoded if isinstance(decoded, list) else [decoded]
            cases.extend(RAGEvalCase.model_validate(item) for item in items)
        except Exception as exc:
            raise RAGEvalConfigurationError(
                f"无法加载 RAG eval fixture: {path.name}"
            ) from exc

    if not cases:
        raise RAGEvalConfigurationError("RAG eval case 目录没有 JSON fixture")
    _validate_case_collection(cases)
    return cases


def evaluate_rag_predictions(
    cases: list[RAGEvalCase],
    predictions: list[RAGEvalPrediction],
) -> RAGEvalMetrics:
    """使用固定标注对 runner 的实际观察做确定性评分。"""
    _validate_case_collection(cases)
    prediction_by_id = _validate_predictions(cases, predictions)
    positive_cases = [case for case in cases if not case.expect_empty]
    negative_cases = [case for case in cases if case.expect_empty]

    tool_hit_count = 0
    evidence_hit_count = 0
    matched_keyword_count = 0
    expected_keyword_count = 0
    correct_empty_count = 0
    located_evidence_count = 0
    returned_evidence_count = 0
    failed_tool_case_ids: list[str] = []
    missed_evidence_case_ids: list[str] = []
    missing_answer_keywords: list[str] = []
    incorrect_non_empty_case_ids: list[str] = []

    for case in cases:
        prediction = prediction_by_id[case.case_id]
        if (
            prediction.predicted_tool_name == case.expected_tool_name
            and prediction.tool_success
        ):
            tool_hit_count += 1
        if not prediction.tool_success:
            failed_tool_case_ids.append(case.case_id)

        items = (
            prediction.retrieval_result.items
            if prediction.retrieval_result is not None
            else []
        )
        returned_evidence_count += len(items)
        located_evidence_count += sum(_has_complete_location(item) for item in items)

        if case.expect_empty:
            if prediction.tool_success and not items:
                correct_empty_count += 1
            elif items:
                incorrect_non_empty_case_ids.append(case.case_id)
            continue

        actual_paths = {item.path for item in items}
        if actual_paths & set(case.expected_paths):
            evidence_hit_count += 1
        else:
            missed_evidence_case_ids.append(case.case_id)

        folded_answer = prediction.answer_text.casefold()
        expected_keyword_count += len(case.expected_keywords)
        for keyword in case.expected_keywords:
            if keyword.casefold() in folded_answer:
                matched_keyword_count += 1
            else:
                missing_answer_keywords.append(f"{case.case_id}:{keyword}")

    latencies = [prediction.latency_ms for prediction in predictions]
    return RAGEvalMetrics(
        case_count=len(cases),
        positive_case_count=len(positive_cases),
        negative_case_count=len(negative_cases),
        tool_hit_count=tool_hit_count,
        evidence_hit_count=evidence_hit_count,
        matched_answer_keyword_count=matched_keyword_count,
        expected_answer_keyword_count=expected_keyword_count,
        correct_empty_count=correct_empty_count,
        located_evidence_count=located_evidence_count,
        returned_evidence_count=returned_evidence_count,
        tool_hit_rate=tool_hit_count / len(cases),
        evidence_hit_rate=evidence_hit_count / len(positive_cases),
        answer_keyword_hit_rate=matched_keyword_count / expected_keyword_count,
        empty_result_accuracy=correct_empty_count / len(negative_cases),
        evidence_location_completeness=(
            located_evidence_count / returned_evidence_count
            if returned_evidence_count
            else 1
        ),
        average_latency_ms=sum(latencies) / len(latencies),
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        failed_tool_case_ids=failed_tool_case_ids,
        missed_evidence_case_ids=missed_evidence_case_ids,
        missing_answer_keywords=missing_answer_keywords,
        incorrect_non_empty_case_ids=incorrect_non_empty_case_ids,
    )


def run_rag_eval(
    cases: list[RAGEvalCase],
    *,
    workspace: str | Path,
    registry: ToolRegistry | None = None,
) -> RAGEvalRun:
    """通过真实工具协议执行 cases，并保留每条样本的可诊断结果。"""
    _validate_case_collection(cases)
    resolved_registry = registry or _create_rag_registry()
    predictions: list[RAGEvalPrediction] = []

    for case in cases:
        started_at = perf_counter()
        result = resolved_registry.execute(
            case.expected_tool_name,
            {
                "query": case.query,
                "workspace": str(workspace),
                "top_k": case.top_k,
            },
        )
        retrieval_result: RetrievalResult | None = None
        answer_text = ""
        tool_success = result.success
        error_code = result.error_code.value if result.error_code is not None else None

        if result.success:
            try:
                retrieval_result = RetrievalResult.model_validate_json(result.content)
                answer_text = "\n\n".join(
                    item.excerpt for item in retrieval_result.items
                )
            except Exception:
                # ! Provider or adapter content is untrusted even when ToolResult says success.
                tool_success = False
                error_code = "INVALID_TOOL_CONTENT"

        if not tool_success and error_code is None:
            error_code = "TOOL_EXECUTION_ERROR"

        predictions.append(
            RAGEvalPrediction(
                case_id=case.case_id,
                predicted_tool_name=case.expected_tool_name,
                tool_success=tool_success,
                retrieval_result=retrieval_result if tool_success else None,
                answer_text=answer_text if tool_success else "",
                latency_ms=(perf_counter() - started_at) * 1000,
                error_code=error_code,
            )
        )

    return RAGEvalRun(
        metrics=evaluate_rag_predictions(cases, predictions),
        predictions=predictions,
    )


def _create_rag_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(KnowledgeRetrieveTool())
    return registry


def _validate_case_collection(cases: list[RAGEvalCase]) -> None:
    if not cases:
        raise RAGEvalConfigurationError("RAG eval cases 不能为空")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise RAGEvalConfigurationError("case_id 必须在 Eval 集内唯一")
    if not any(not case.expect_empty for case in cases):
        raise RAGEvalConfigurationError("Eval 集至少需要一个正样本")
    if not any(case.expect_empty for case in cases):
        raise RAGEvalConfigurationError("Eval 集至少需要一个负样本")


def _validate_predictions(
    cases: list[RAGEvalCase],
    predictions: list[RAGEvalPrediction],
) -> dict[str, RAGEvalPrediction]:
    prediction_ids = [prediction.case_id for prediction in predictions]
    if len(prediction_ids) != len(set(prediction_ids)):
        raise RAGEvalConfigurationError("prediction case_id 不能重复")

    case_ids = {case.case_id for case in cases}
    prediction_id_set = set(prediction_ids)
    missing = sorted(case_ids - prediction_id_set)
    unknown = sorted(prediction_id_set - case_ids)
    if missing:
        raise RAGEvalConfigurationError(f"缺少 prediction: {', '.join(missing)}")
    if unknown:
        raise RAGEvalConfigurationError(f"存在未知 prediction: {', '.join(unknown)}")
    return {prediction.case_id: prediction for prediction in predictions}


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise RAGEvalConfigurationError("Latency 样本不能为空")
    ordered = sorted(values)
    index = max(0, ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _validate_relative_path(value: str) -> str:
    if not _is_relative_path(value):
        raise ValueError("expected path 必须是语料库内 POSIX 相对路径")
    return value


def _is_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return not (
        value != value.strip()
        or value in {"", "."}
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
    )


def _has_complete_location(item: object) -> bool:
    source = getattr(item, "source", "")
    path = getattr(item, "path", "")
    line_range = getattr(item, "line_range", None)
    return bool(
        isinstance(source, str)
        and source.strip()
        and isinstance(path, str)
        and _is_relative_path(path)
        and line_range is not None
        and getattr(line_range, "start", 0) >= 1
        and getattr(line_range, "end", 0) >= getattr(line_range, "start", 0)
    )
