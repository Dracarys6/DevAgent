import json
from collections.abc import Callable
from math import ceil
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from devagent.agent import AgentRunStatus, AgentRuntime
from devagent.llm import LLMClient, tool_registry_to_openai_tools
from devagent.memory import RetrievalResult
from devagent.tools import KnowledgeRetrieveTool, ToolRegistry, ToolResult
from devagent.tools.knowledge_tools import KnowledgeRetriever, knowledge_retrieve

from .runner import RAGEvalCase, RAGEvalConfigurationError

MAX_LIVE_EVAL_ATTEMPTS = 3
LiveLLMClientFactory = Callable[[list[dict[str, Any]]], LLMClient]


class LiveRAGEvalModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class RAGAgentAnswer(LiveRAGEvalModel):
    answer: str = Field(min_length=1, max_length=4_000)
    cited_paths: list[str] = Field(default_factory=list, max_length=20)
    insufficient_evidence: bool = Field(strict=True)

    @field_validator("cited_paths")
    @classmethod
    def validate_cited_paths(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("cited_paths 不能重复")
        for value in values:
            path = PurePosixPath(value)
            if (
                value != value.strip()
                or value in {"", "."}
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in value
            ):
                raise ValueError("cited_paths 必须是语料库内 POSIX 相对路径")
        return values


class LiveRAGPrediction(LiveRAGEvalModel):
    case_id: str = Field(min_length=1, max_length=100)
    run_success: bool = Field(strict=True)
    run_status: AgentRunStatus
    tool_called: bool = Field(strict=True)
    tool_success: bool = Field(strict=True)
    retrieval_result: RetrievalResult | None = None
    answer: RAGAgentAnswer | None = None
    raw_final_answer: str = Field(default="", max_length=8_000)
    latency_ms: float = Field(ge=0)
    steps: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    attempt_count: int = Field(ge=1, le=MAX_LIVE_EVAL_ATTEMPTS)
    attempt_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_prediction_shape(self) -> "LiveRAGPrediction":
        if self.tool_success != (self.retrieval_result is not None):
            raise ValueError("tool_success 与 retrieval_result 不一致")
        if self.answer is not None and not self.run_success:
            raise ValueError("运行失败时不能包含有效 answer")
        if self.run_success != (self.run_status == AgentRunStatus.SUCCESS):
            raise ValueError("run_success 与 run_status 不一致")
        return self


class LiveRAGMetrics(LiveRAGEvalModel):
    case_count: int = Field(ge=1)
    positive_case_count: int = Field(ge=1)
    negative_case_count: int = Field(ge=1)
    valid_answer_count: int = Field(ge=0)
    tool_hit_count: int = Field(ge=0)
    tool_success_count: int = Field(ge=0)
    evidence_hit_count: int = Field(ge=0)
    matched_answer_keyword_count: int = Field(ge=0)
    expected_answer_keyword_count: int = Field(ge=1)
    expected_path_citation_count: int = Field(ge=0)
    grounded_citation_count: int = Field(ge=0)
    returned_citation_count: int = Field(ge=0)
    correct_abstention_count: int = Field(ge=0)
    end_to_end_success_count: int = Field(ge=0)
    valid_answer_rate: float = Field(ge=0, le=1)
    tool_hit_rate: float = Field(ge=0, le=1)
    tool_success_rate: float = Field(ge=0, le=1)
    evidence_hit_rate: float = Field(ge=0, le=1)
    answer_keyword_hit_rate: float = Field(ge=0, le=1)
    expected_path_citation_rate: float = Field(ge=0, le=1)
    grounded_citation_rate: float = Field(ge=0, le=1)
    abstention_accuracy: float = Field(ge=0, le=1)
    end_to_end_success_rate: float = Field(ge=0, le=1)
    average_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    failed_case_ids: list[str]
    failure_reasons: dict[str, list[str]] = Field(default_factory=dict)


class LiveRAGEvalRun(LiveRAGEvalModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    api_mode: str = Field(min_length=1, max_length=100)
    metrics: LiveRAGMetrics
    predictions: list[LiveRAGPrediction] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_prediction_count(self) -> "LiveRAGEvalRun":
        if self.metrics.case_count != len(self.predictions):
            raise ValueError("metrics.case_count 必须等于 predictions 数量")
        return self


def run_live_rag_agent_eval(
    cases: list[RAGEvalCase],
    *,
    workspace: str | Path,
    llm_client_factory: LiveLLMClientFactory,
    provider: str,
    model: str,
    api_mode: str,
    knowledge_retriever: KnowledgeRetriever = knowledge_retrieve,
    max_attempts: int = 2,
) -> LiveRAGEvalRun:
    """通过真实 AgentRuntime、LLMClient 和 knowledge tool 执行 RAG case。"""
    _validate_live_cases(cases)
    if (
        isinstance(max_attempts, bool)
        or max_attempts < 1
        or max_attempts > MAX_LIVE_EVAL_ATTEMPTS
    ):
        raise ValueError(f"max_attempts 必须在 1 到 {MAX_LIVE_EVAL_ATTEMPTS} 之间")
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise RAGEvalConfigurationError("Live RAG workspace 不存在或不是目录")

    predictions = [
        _run_live_case(
            case,
            workspace=root,
            llm_client_factory=llm_client_factory,
            knowledge_retriever=knowledge_retriever,
            max_attempts=max_attempts,
        )
        for case in cases
    ]
    return LiveRAGEvalRun(
        provider=provider,
        model=model,
        api_mode=api_mode,
        metrics=evaluate_live_rag_predictions(cases, predictions),
        predictions=predictions,
    )


def evaluate_live_rag_predictions(
    cases: list[RAGEvalCase],
    predictions: list[LiveRAGPrediction],
) -> LiveRAGMetrics:
    """使用人工标注对真实 Agent 的工具、答案、引用和拒答做确定性评分。"""
    _validate_live_cases(cases)
    prediction_by_id = _validate_live_predictions(cases, predictions)
    positive_cases = [case for case in cases if not case.expect_empty]
    negative_cases = [case for case in cases if case.expect_empty]

    valid_answer_count = 0
    tool_hit_count = 0
    tool_success_count = 0
    evidence_hit_count = 0
    matched_keyword_count = 0
    expected_keyword_count = 0
    expected_path_citation_count = 0
    grounded_citation_count = 0
    returned_citation_count = 0
    correct_abstention_count = 0
    end_to_end_success_count = 0
    failed_case_ids: list[str] = []
    failure_reasons: dict[str, list[str]] = {}

    for case in cases:
        prediction = prediction_by_id[case.case_id]
        case_reasons: list[str] = []
        valid_answer_count += int(prediction.answer is not None)
        tool_hit_count += int(prediction.tool_called)
        tool_success_count += int(prediction.tool_success)
        retrieved_paths = {
            item.path
            for item in (
                prediction.retrieval_result.items
                if prediction.retrieval_result is not None
                else []
            )
        }
        cited_paths = (
            set(prediction.answer.cited_paths)
            if prediction.answer is not None
            else set()
        )
        grounded_citation_count += len(cited_paths & retrieved_paths)
        returned_citation_count += len(cited_paths)
        if not prediction.run_success:
            case_reasons.append(f"runtime_status={prediction.run_status.value}")
        if prediction.answer is None:
            case_reasons.append("invalid_or_missing_final_answer")
        if not prediction.tool_called:
            case_reasons.append("knowledge_retrieve_not_called")
        elif not prediction.tool_success:
            case_reasons.append("knowledge_retrieve_failed")

        if case.expect_empty:
            correct_abstention = bool(
                prediction.answer is not None
                and prediction.answer.insufficient_evidence
                and not cited_paths
                and not retrieved_paths
            )
            correct_abstention_count += int(correct_abstention)
            if retrieved_paths:
                case_reasons.append("negative_case_returned_evidence")
            if prediction.answer is not None:
                if not prediction.answer.insufficient_evidence:
                    case_reasons.append("negative_case_did_not_abstain")
                if cited_paths:
                    case_reasons.append("negative_case_returned_citations")
        else:
            expected_paths = set(case.expected_paths)
            evidence_hit = bool(retrieved_paths & expected_paths)
            expected_path_cited = bool(cited_paths & expected_paths)
            evidence_hit_count += int(evidence_hit)
            expected_path_citation_count += int(expected_path_cited)
            expected_keyword_count += len(case.expected_keywords)
            answer_text = prediction.answer.answer if prediction.answer else ""
            matched_keywords = [
                keyword
                for keyword in case.expected_keywords
                if keyword.casefold() in answer_text.casefold()
            ]
            missing_keywords = [
                keyword
                for keyword in case.expected_keywords
                if keyword.casefold() not in answer_text.casefold()
            ]
            matched_keyword_count += len(matched_keywords)
            all_citations_grounded = cited_paths <= retrieved_paths
            if not evidence_hit:
                case_reasons.append("expected_evidence_not_retrieved")
            if (
                prediction.answer is not None
                and prediction.answer.insufficient_evidence
            ):
                case_reasons.append("positive_case_abstained")
            case_reasons.extend(
                f"missing_answer_keyword={keyword}" for keyword in missing_keywords
            )
            if not expected_path_cited:
                case_reasons.append("expected_path_not_cited")
            if not all_citations_grounded:
                case_reasons.append("ungrounded_citation")

        if not case_reasons:
            end_to_end_success_count += 1
        else:
            failed_case_ids.append(case.case_id)
            failure_reasons[case.case_id] = case_reasons

    latencies = [prediction.latency_ms for prediction in predictions]
    return LiveRAGMetrics(
        case_count=len(cases),
        positive_case_count=len(positive_cases),
        negative_case_count=len(negative_cases),
        valid_answer_count=valid_answer_count,
        tool_hit_count=tool_hit_count,
        tool_success_count=tool_success_count,
        evidence_hit_count=evidence_hit_count,
        matched_answer_keyword_count=matched_keyword_count,
        expected_answer_keyword_count=expected_keyword_count,
        expected_path_citation_count=expected_path_citation_count,
        grounded_citation_count=grounded_citation_count,
        returned_citation_count=returned_citation_count,
        correct_abstention_count=correct_abstention_count,
        end_to_end_success_count=end_to_end_success_count,
        valid_answer_rate=valid_answer_count / len(cases),
        tool_hit_rate=tool_hit_count / len(cases),
        tool_success_rate=tool_success_count / len(cases),
        evidence_hit_rate=evidence_hit_count / len(positive_cases),
        answer_keyword_hit_rate=matched_keyword_count / expected_keyword_count,
        expected_path_citation_rate=(
            expected_path_citation_count / len(positive_cases)
        ),
        grounded_citation_rate=(
            grounded_citation_count / returned_citation_count
            if returned_citation_count
            else 1
        ),
        abstention_accuracy=correct_abstention_count / len(negative_cases),
        end_to_end_success_rate=end_to_end_success_count / len(cases),
        average_latency_ms=sum(latencies) / len(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
        failed_case_ids=failed_case_ids,
        failure_reasons=failure_reasons,
    )


def render_live_rag_report(
    run: LiveRAGEvalRun,
    *,
    generated_at: str,
    commit_id: str,
) -> str:
    """渲染包含真实模型标识、指标、失败 case 和答案的脱敏报告。"""
    metrics = run.metrics

    def percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    lines = [
        "# Live RAG Agent Evaluation",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Commit: `{commit_id}`",
        f"- Provider: `{run.provider}`",
        f"- Model: `{run.model}`",
        f"- API mode: `{run.api_mode}`",
        f"- Cases: {metrics.case_count}",
        "",
        "## End-to-End Metrics",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Valid Answer Rate | {percent(metrics.valid_answer_rate)} |",
        f"| knowledge_retrieve Tool Call Rate | {percent(metrics.tool_hit_rate)} |",
        f"| Tool Success Rate | {percent(metrics.tool_success_rate)} |",
        f"| Evidence Hit Rate | {percent(metrics.evidence_hit_rate)} |",
        f"| Answer Keyword Hit Rate | {percent(metrics.answer_keyword_hit_rate)} |",
        f"| Expected Path Citation Rate | {percent(metrics.expected_path_citation_rate)} |",
        f"| Grounded Citation Rate | {percent(metrics.grounded_citation_rate)} |",
        f"| Abstention Accuracy | {percent(metrics.abstention_accuracy)} |",
        f"| End-to-End Success Rate | {percent(metrics.end_to_end_success_rate)} |",
        f"| Average Latency | {metrics.average_latency_ms:.2f} ms |",
        f"| End-to-End p95 | {metrics.p95_latency_ms:.2f} ms |",
        "",
        f"- Failed cases: {_render_values(metrics.failed_case_ids)}",
        *[
            f"- `{case_id}`: {', '.join(reasons)}"
            for case_id, reasons in metrics.failure_reasons.items()
        ],
        "",
        "## Case Results",
        "",
    ]
    for prediction in run.predictions:
        retrieval = prediction.retrieval_result
        retrieved_paths = (
            [item.path for item in retrieval.items] if retrieval is not None else []
        )
        answer = prediction.answer
        lines.extend(
            [
                f"### {prediction.case_id}",
                "",
                f"- Run status: `{prediction.run_status.value}`",
                f"- Tool called / success: {prediction.tool_called} / {prediction.tool_success}",
                f"- Retrieved paths: {_render_values(retrieved_paths)}",
                (
                    f"- Cited paths: {_render_values(answer.cited_paths)}"
                    if answer is not None
                    else "- Cited paths: None"
                ),
                (
                    f"- Insufficient evidence: {answer.insufficient_evidence}"
                    if answer is not None
                    else "- Insufficient evidence: unknown"
                ),
                f"- Latency: {prediction.latency_ms:.2f} ms",
                f"- Attempts: {prediction.attempt_count}",
                f"- Attempt errors: {_render_values(prediction.attempt_errors)}",
                "",
                "```text",
                answer.answer if answer is not None else prediction.raw_final_answer,
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Acceptance Boundary",
            "",
            "This report was produced by a live LLM provider through AgentRuntime and the real knowledge_retrieve tool.",
            "Deterministic labels score tool use, expected keywords, citations, abstention, and latency.",
            "It is stronger than a mock baseline but still represents the listed cases, model, provider, and run time rather than universal production accuracy.",
            "",
        ]
    )
    return "\n".join(lines)


def _run_live_case(
    case: RAGEvalCase,
    *,
    workspace: Path,
    llm_client_factory: LiveLLMClientFactory,
    knowledge_retriever: KnowledgeRetriever,
    max_attempts: int,
) -> LiveRAGPrediction:
    attempt_errors: list[str] = []
    last_prediction: LiveRAGPrediction | None = None

    for attempt in range(1, max_attempts + 1):
        registry = ToolRegistry()
        registry.register(KnowledgeRetrieveTool(retriever=knowledge_retriever))
        client = llm_client_factory(tool_registry_to_openai_tools(registry))
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            system_prompt=_build_live_rag_system_prompt(workspace),
            max_steps=3,
            max_tool_calls=2,
            workspace=str(workspace),
        )
        started_at = perf_counter()
        result = runtime.run(case.query)
        latency_ms = (perf_counter() - started_at) * 1000
        retrieval_result, tool_called = _extract_retrieval_result(result.messages)
        answer: RAGAgentAnswer | None = None
        parse_error: str | None = None
        if result.success:
            try:
                answer = RAGAgentAnswer.model_validate_json(result.final_answer)
            except ValidationError:
                parse_error = "INVALID_FINAL_ANSWER"
        else:
            parse_error = result.status.value
        if not tool_called:
            parse_error = parse_error or "KNOWLEDGE_TOOL_NOT_CALLED"
        elif retrieval_result is None:
            parse_error = parse_error or "KNOWLEDGE_TOOL_FAILED"

        if parse_error is not None:
            attempt_errors.append(parse_error)
        last_prediction = LiveRAGPrediction(
            case_id=case.case_id,
            run_success=result.success,
            run_status=result.status,
            tool_called=tool_called,
            tool_success=retrieval_result is not None,
            retrieval_result=retrieval_result,
            answer=answer,
            raw_final_answer=result.final_answer,
            latency_ms=latency_ms,
            steps=result.steps,
            tool_call_count=result.tool_call_count,
            attempt_count=attempt,
            attempt_errors=list(attempt_errors),
        )
        if answer is not None and retrieval_result is not None:
            return last_prediction

    if last_prediction is None:
        raise AssertionError("Live RAG case 至少应执行一次")
    return last_prediction


def _build_live_rag_system_prompt(workspace: Path) -> str:
    schema = json.dumps(
        RAGAgentAnswer.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "你是 DevAgent 的证据驱动研发助手。回答项目问题时必须先调用 "
        "knowledge_retrieve，不得依赖模型记忆猜测。"
        f"工具 workspace 必须使用 {workspace}，top_k 使用 5。"
        "最终答案只能依据工具返回的 EvidenceSnippet。"
        "cited_paths 只能填写工具结果中的 path；证据无法回答时设置 "
        "insufficient_evidence=true、cited_paths=[]，并明确说明缺少证据。"
        "有足够证据时设置 insufficient_evidence=false，并在 answer 中回答问题。"
        "最终只输出匹配以下 JSON Schema 的 JSON 对象，不要 Markdown："
        f"{schema}"
    )


def _extract_retrieval_result(
    messages: list[dict[str, Any]],
) -> tuple[RetrievalResult | None, bool]:
    tool_called = any(
        call.get("function", {}).get("name") == "knowledge_retrieve"
        for message in messages
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    )
    for message in messages:
        if message.get("role") != "tool" or message.get("name") != "knowledge_retrieve":
            continue
        try:
            result = ToolResult.model_validate_json(message["content"])
            if not result.success:
                return None, tool_called
            return RetrievalResult.model_validate_json(result.content), tool_called
        except (KeyError, TypeError, ValidationError):
            return None, tool_called
    return None, tool_called


def _validate_live_cases(cases: list[RAGEvalCase]) -> None:
    if not cases:
        raise RAGEvalConfigurationError("Live RAG eval cases 不能为空")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise RAGEvalConfigurationError("Live RAG case_id 必须唯一")
    if not any(not case.expect_empty for case in cases):
        raise RAGEvalConfigurationError("Live RAG eval 至少需要一个正样本")
    if not any(case.expect_empty for case in cases):
        raise RAGEvalConfigurationError("Live RAG eval 至少需要一个负样本")


def _validate_live_predictions(
    cases: list[RAGEvalCase],
    predictions: list[LiveRAGPrediction],
) -> dict[str, LiveRAGPrediction]:
    case_ids = {case.case_id for case in cases}
    prediction_ids = [prediction.case_id for prediction in predictions]
    if len(prediction_ids) != len(set(prediction_ids)):
        raise RAGEvalConfigurationError("Live RAG prediction case_id 不能重复")
    missing = sorted(case_ids - set(prediction_ids))
    unknown = sorted(set(prediction_ids) - case_ids)
    if missing:
        raise RAGEvalConfigurationError(f"缺少 live prediction: {', '.join(missing)}")
    if unknown:
        raise RAGEvalConfigurationError(
            f"存在未知 live prediction: {', '.join(unknown)}"
        )
    return {prediction.case_id: prediction for prediction in predictions}


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _render_values(values: list[str]) -> str:
    if not values:
        return "None"
    return ", ".join(f"`{value}`" for value in values)
