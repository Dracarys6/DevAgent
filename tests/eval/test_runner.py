import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from devagent.eval import (
    RAGEvalCase,
    RAGEvalConfigurationError,
    RAGEvalRun,
    RAGEvalPrediction,
    evaluate_rag_predictions,
    load_rag_eval_cases,
    run_rag_eval,
)
from devagent.memory import EvidenceSnippet, LineRange, RetrievalResult
from devagent.tools import BaseTool, RiskLevel, ToolRegistry, ToolResult

PROJECT_ROOT = Path(__file__).parents[2]
RAG_CASE_DIR = PROJECT_ROOT / "eval" / "cases" / "rag"
RAG_WORKSPACE = RAG_CASE_DIR / "workspace"


def make_case(
    *,
    case_id: str = "positive",
    expect_empty: bool = False,
    query: str = "alpha",
    expected_paths: list[str] | None = None,
    expected_keywords: list[str] | None = None,
) -> RAGEvalCase:
    return RAGEvalCase(
        case_id=case_id,
        description="固定 RAG 评测样例",
        category="test",
        query=query,
        expect_empty=expect_empty,
        expected_paths=(
            []
            if expect_empty
            else (expected_paths if expected_paths is not None else ["src/app.py"])
        ),
        expected_keywords=(
            []
            if expect_empty
            else (
                expected_keywords
                if expected_keywords is not None
                else ["alpha", "beta"]
            )
        ),
    )


def make_result(
    *,
    query: str = "alpha",
    path: str = "src/app.py",
    excerpt: str = "alpha beta",
    empty: bool = False,
) -> RetrievalResult:
    items = (
        []
        if empty
        else [
            EvidenceSnippet(
                chunk_id="chunk-1",
                document_id="document-1",
                source="workspace",
                path=path,
                line_range=LineRange(start=1, end=2),
                excerpt=excerpt,
                score=1.5,
                rank=1,
            )
        ]
    )
    return RetrievalResult(
        query=query,
        top_k=5,
        total_candidates=len(items),
        items=items,
        retrieval_ms=0.5,
    )


def make_prediction(
    *,
    case_id: str = "positive",
    result: RetrievalResult | None = None,
    answer_text: str = "alpha beta",
    latency_ms: float = 1,
    success: bool = True,
) -> RAGEvalPrediction:
    return RAGEvalPrediction(
        case_id=case_id,
        predicted_tool_name="knowledge_retrieve",
        tool_success=success,
        retrieval_result=(result or make_result()) if success else None,
        answer_text=answer_text if success else "",
        latency_ms=latency_ms,
        error_code=None if success else "TOOL_EXECUTION_ERROR",
    )


def make_complete_eval_input() -> tuple[list[RAGEvalCase], list[RAGEvalPrediction]]:
    cases = [make_case(), make_case(case_id="negative", expect_empty=True)]
    predictions = [
        make_prediction(),
        make_prediction(
            case_id="negative",
            result=make_result(query="unknown", empty=True),
            answer_text="",
        ),
    ]
    return cases, predictions


def test_case_model_accepts_positive_and_negative_contracts() -> None:
    assert make_case().expect_empty is False
    assert make_case(case_id="negative", expect_empty=True).expected_paths == []


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"expected_paths": []}, "expected_path"),
        ({"expected_keywords": []}, "expected_keyword"),
        (
            {"expect_empty": True, "expected_paths": ["src/app.py"]},
            "负样本",
        ),
        (
            {"expect_empty": True, "expected_keywords": ["alpha"]},
            "负样本",
        ),
        ({"top_k": 0}, "greater than or equal"),
        ({"top_k": 51}, "less than or equal"),
        ({"top_k": True}, "valid integer"),
        ({"expected_paths": ["/src/app.py"]}, "POSIX"),
        ({"expected_paths": ["../app.py"]}, "POSIX"),
        ({"expected_paths": ["src\\app.py"]}, "POSIX"),
        ({"expected_paths": ["src/app.py", "src/app.py"]}, "不能重复"),
        ({"expected_keywords": ["Alpha", "alpha"]}, "不能重复"),
        ({"unexpected": "value"}, "Extra inputs"),
    ],
)
def test_case_model_rejects_invalid_contracts(
    updates: dict[str, object],
    error: str,
) -> None:
    payload = make_case().model_dump()
    payload.update(updates)

    with pytest.raises(ValidationError, match=error):
        RAGEvalCase.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "tool_success": True,
            "retrieval_result": None,
            "error_code": None,
        },
        {
            "tool_success": True,
            "retrieval_result": make_result(),
            "error_code": "UNEXPECTED",
        },
        {
            "tool_success": False,
            "retrieval_result": make_result(),
            "error_code": "FAILED",
        },
        {
            "tool_success": False,
            "retrieval_result": None,
            "error_code": None,
        },
    ],
)
def test_prediction_model_rejects_inconsistent_tool_outcomes(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RAGEvalPrediction(
            case_id="case",
            predicted_tool_name="knowledge_retrieve",
            answer_text="",
            latency_ms=1,
            **payload,
        )


def test_prediction_rejects_negative_latency() -> None:
    with pytest.raises(ValidationError, match="greater than or equal"):
        make_prediction(latency_ms=-1)


def test_loader_is_sorted_repeatable_and_accepts_object_or_list(
    tmp_path: Path,
) -> None:
    positive = make_case(case_id="a-positive")
    negative = make_case(case_id="z-negative", expect_empty=True)
    (tmp_path / "z.json").write_text(negative.model_dump_json(), encoding="utf-8")
    (tmp_path / "a.json").write_text(
        json.dumps([positive.model_dump(mode="json")]),
        encoding="utf-8",
    )

    first = load_rag_eval_cases(tmp_path)
    second = load_rag_eval_cases(tmp_path)

    assert [case.case_id for case in first] == ["a-positive", "z-negative"]
    assert first == second


def test_loader_rejects_missing_empty_and_invalid_directories(tmp_path: Path) -> None:
    with pytest.raises(RAGEvalConfigurationError, match="不存在"):
        load_rag_eval_cases(tmp_path / "missing")
    with pytest.raises(RAGEvalConfigurationError, match="没有 JSON"):
        load_rag_eval_cases(tmp_path)

    (tmp_path / "secret.json").write_text("{private-token", encoding="utf-8")
    with pytest.raises(RAGEvalConfigurationError) as exc_info:
        load_rag_eval_cases(tmp_path)
    assert "private-token" not in str(exc_info.value)


def test_loader_rejects_duplicate_ids_and_one_sided_collections(
    tmp_path: Path,
) -> None:
    duplicate = [make_case().model_dump(mode="json")] * 2
    (tmp_path / "cases.json").write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(RAGEvalConfigurationError, match="case_id"):
        load_rag_eval_cases(tmp_path)

    (tmp_path / "cases.json").write_text(
        make_case().model_dump_json(),
        encoding="utf-8",
    )
    with pytest.raises(RAGEvalConfigurationError, match="负样本"):
        load_rag_eval_cases(tmp_path)


def test_metrics_are_perfect_for_complete_positive_and_empty_negative() -> None:
    cases, predictions = make_complete_eval_input()

    metrics = evaluate_rag_predictions(cases, predictions)

    assert metrics.tool_hit_rate == 1
    assert metrics.evidence_hit_rate == 1
    assert metrics.answer_keyword_hit_rate == 1
    assert metrics.empty_result_accuracy == 1
    assert metrics.evidence_location_completeness == 1
    assert metrics.failed_tool_case_ids == []
    assert metrics.missed_evidence_case_ids == []


def test_metrics_expose_path_keyword_and_negative_result_failures() -> None:
    cases, _ = make_complete_eval_input()
    predictions = [
        make_prediction(
            result=make_result(path="src/other.py", excerpt="alpha"),
            answer_text="alpha",
        ),
        make_prediction(
            case_id="negative",
            result=make_result(query="unknown", excerpt="unexpected"),
            answer_text="unexpected",
        ),
    ]

    metrics = evaluate_rag_predictions(cases, predictions)

    assert metrics.evidence_hit_rate == 0
    assert metrics.answer_keyword_hit_rate == 0.5
    assert metrics.empty_result_accuracy == 0
    assert metrics.missed_evidence_case_ids == ["positive"]
    assert metrics.missing_answer_keywords == ["positive:beta"]
    assert metrics.incorrect_non_empty_case_ids == ["negative"]


def test_metrics_expose_tool_failure_without_stopping_other_cases() -> None:
    cases, predictions = make_complete_eval_input()
    predictions[0] = make_prediction(success=False)

    metrics = evaluate_rag_predictions(cases, predictions)

    assert metrics.tool_hit_rate == 0.5
    assert metrics.evidence_hit_rate == 0
    assert metrics.failed_tool_case_ids == ["positive"]


def test_metrics_use_nearest_rank_percentiles() -> None:
    cases = [make_case(case_id=f"positive-{index}") for index in range(1, 19)] + [
        make_case(case_id="negative-19", expect_empty=True),
        make_case(case_id="negative-20", expect_empty=True),
    ]
    predictions = [
        make_prediction(case_id=case.case_id, latency_ms=index)
        if not case.expect_empty
        else make_prediction(
            case_id=case.case_id,
            result=make_result(empty=True),
            answer_text="",
            latency_ms=index,
        )
        for index, case in enumerate(cases, start=1)
    ]

    metrics = evaluate_rag_predictions(cases, predictions)

    assert metrics.average_latency_ms == 10.5
    assert metrics.p50_latency_ms == 10
    assert metrics.p95_latency_ms == 19


def test_metrics_reject_missing_unknown_and_duplicate_predictions() -> None:
    cases, predictions = make_complete_eval_input()

    with pytest.raises(RAGEvalConfigurationError, match="缺少"):
        evaluate_rag_predictions(cases, predictions[:1])
    with pytest.raises(RAGEvalConfigurationError, match="未知"):
        evaluate_rag_predictions(
            cases,
            predictions + [make_prediction(case_id="unknown")],
        )
    with pytest.raises(RAGEvalConfigurationError, match="不能重复"):
        evaluate_rag_predictions(cases, [predictions[0], predictions[0]])


def test_location_completeness_detects_untrusted_constructed_evidence() -> None:
    cases, predictions = make_complete_eval_input()
    incomplete_item = EvidenceSnippet.model_construct(
        chunk_id="chunk-1",
        document_id="document-1",
        source="",
        path="src/app.py",
        line_range=LineRange(start=1, end=1),
        excerpt="alpha beta",
        score=1,
        rank=1,
        metadata={},
    )
    incomplete_result = RetrievalResult.model_construct(
        query="alpha",
        top_k=5,
        total_candidates=1,
        items=[incomplete_item],
        retrieval_ms=1,
        truncated=False,
    )
    predictions[0] = make_prediction(result=incomplete_result)

    metrics = evaluate_rag_predictions(cases, predictions)

    assert metrics.evidence_location_completeness == 0


def test_run_model_rejects_metrics_prediction_count_mismatch() -> None:
    cases, predictions = make_complete_eval_input()
    metrics = evaluate_rag_predictions(cases, predictions)

    with pytest.raises(ValidationError, match="case_count"):
        RAGEvalRun(metrics=metrics, predictions=predictions[:1])


def test_runner_executes_real_registry_and_preserves_case_order(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("alpha beta implementation", encoding="utf-8")
    cases = [
        make_case(expected_paths=["app.py"]),
        make_case(
            case_id="negative",
            expect_empty=True,
            query="totally_absent_vocabulary",
        ),
    ]

    run = run_rag_eval(cases, workspace=tmp_path)

    assert [item.case_id for item in run.predictions] == ["positive", "negative"]
    assert all(item.tool_success for item in run.predictions)
    assert run.predictions[0].retrieval_result is not None
    assert run.predictions[0].answer_text == "alpha beta implementation"
    assert all(item.latency_ms >= 0 for item in run.predictions)


def test_runner_records_missing_tool_as_predictions(tmp_path: Path) -> None:
    cases, _ = make_complete_eval_input()

    run = run_rag_eval(cases, workspace=tmp_path, registry=ToolRegistry())

    assert len(run.predictions) == 2
    assert all(not item.tool_success for item in run.predictions)
    assert all(item.error_code == "TOOL_NOT_FOUND" for item in run.predictions)
    assert run.metrics.failed_tool_case_ids == ["positive", "negative"]


class MalformedArgs(BaseModel):
    query: str
    workspace: str
    top_k: int


class MalformedKnowledgeTool(BaseTool[MalformedArgs]):
    name = "knowledge_retrieve"
    description = "返回损坏内容的测试工具"
    args_model = MalformedArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: MalformedArgs) -> ToolResult:
        return ToolResult.ok("not-json")


def test_runner_converts_invalid_success_content_to_failed_prediction(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    registry.register(MalformedKnowledgeTool())
    cases, _ = make_complete_eval_input()

    run = run_rag_eval(cases, workspace=tmp_path, registry=registry)

    assert all(not item.tool_success for item in run.predictions)
    assert all(item.error_code == "INVALID_TOOL_CONTENT" for item in run.predictions)


def test_fixed_baseline_meets_day54_quality_targets() -> None:
    cases = load_rag_eval_cases(RAG_CASE_DIR)

    run = run_rag_eval(cases, workspace=RAG_WORKSPACE)

    assert run.metrics.case_count == 20
    assert run.metrics.positive_case_count == 18
    assert run.metrics.negative_case_count == 2
    assert run.metrics.tool_hit_rate == 1
    assert run.metrics.evidence_hit_rate >= 0.8
    assert run.metrics.answer_keyword_hit_rate >= 0.8
    assert run.metrics.empty_result_accuracy == 1
    assert run.metrics.evidence_location_completeness == 1
    assert run.metrics.failed_tool_case_ids == []


def test_fixed_baseline_has_repeatable_semantic_results() -> None:
    cases = load_rag_eval_cases(RAG_CASE_DIR)

    first = run_rag_eval(cases, workspace=RAG_WORKSPACE)
    second = run_rag_eval(cases, workspace=RAG_WORKSPACE)

    def semantic_result(run: object) -> list[tuple[object, ...]]:
        predictions = getattr(run, "predictions")
        return [
            (
                item.case_id,
                item.predicted_tool_name,
                item.tool_success,
                [
                    (evidence.path, evidence.rank, evidence.excerpt)
                    for evidence in item.retrieval_result.items
                ]
                if item.retrieval_result is not None
                else [],
                item.answer_text,
            )
            for item in predictions
        ]

    assert semantic_result(first) == semantic_result(second)
    assert first.metrics.tool_hit_rate == second.metrics.tool_hit_rate
    assert first.metrics.evidence_hit_rate == second.metrics.evidence_hit_rate
    assert (
        first.metrics.answer_keyword_hit_rate == second.metrics.answer_keyword_hit_rate
    )
