from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from devagent.eval import (
    RAGAgentAnswer,
    RAGEvalCase,
    evaluate_live_rag_predictions,
    render_live_rag_report,
    run_live_rag_agent_eval,
)
from devagent.llm import LLMResponse, MockLLMClient, ToolCall


def make_cases() -> list[RAGEvalCase]:
    return [
        RAGEvalCase(
            case_id="positive",
            description="找到 alpha 的实现",
            category="code",
            query="alpha implementation",
            expected_paths=["src/app.py"],
            expected_keywords=["alpha", "return"],
        ),
        RAGEvalCase(
            case_id="negative",
            description="拒绝不存在的账单问题",
            category="negative",
            query="payment billing invoice",
            expect_empty=True,
        ),
    ]


def write_workspace(root: Path) -> None:
    path = root / "src" / "app.py"
    path.parent.mkdir(parents=True)
    path.write_text("def alpha():\n    return 'alpha'\n", encoding="utf-8")


def make_client(
    *,
    query: str,
    workspace: Path,
    answer: RAGAgentAnswer | str,
) -> MockLLMClient:
    final_content = (
        answer.model_dump_json() if isinstance(answer, RAGAgentAnswer) else answer
    )
    return MockLLMClient(
        responses=[
            LLMResponse.tool_calls_response(
                [
                    ToolCall(
                        id=f"call-{query}",
                        name="knowledge_retrieve",
                        arguments={
                            "query": query,
                            "workspace": str(workspace),
                            "top_k": 5,
                        },
                    )
                ]
            ),
            LLMResponse.final_answer(final_content),
        ]
    )


def make_factory(
    clients: list[MockLLMClient],
) -> tuple[Iterator[MockLLMClient], object]:
    client_iterator = iter(clients)

    def factory(tools):
        assert tools[0]["function"]["name"] == "knowledge_retrieve"
        return next(client_iterator)

    return client_iterator, factory


def test_live_rag_runner_exercises_runtime_tool_and_answer_path(
    tmp_path: Path,
) -> None:
    write_workspace(tmp_path)
    cases = make_cases()
    _, factory = make_factory(
        [
            make_client(
                query=cases[0].query,
                workspace=tmp_path,
                answer=RAGAgentAnswer(
                    answer="alpha 函数会 return 字符串。",
                    cited_paths=["src/app.py"],
                    insufficient_evidence=False,
                ),
            ),
            make_client(
                query=cases[1].query,
                workspace=tmp_path,
                answer=RAGAgentAnswer(
                    answer="检索结果中没有支付或账单证据。",
                    cited_paths=[],
                    insufficient_evidence=True,
                ),
            ),
        ]
    )

    run = run_live_rag_agent_eval(
        cases,
        workspace=tmp_path,
        llm_client_factory=factory,
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
    )

    assert run.metrics.tool_hit_rate == 1
    assert run.metrics.tool_success_rate == 1
    assert run.metrics.evidence_hit_rate == 1
    assert run.metrics.answer_keyword_hit_rate == 1
    assert run.metrics.expected_path_citation_rate == 1
    assert run.metrics.grounded_citation_rate == 1
    assert run.metrics.abstention_accuracy == 1
    assert run.metrics.end_to_end_success_rate == 1
    assert run.predictions[0].retrieval_result is not None
    assert run.predictions[0].retrieval_result.items[0].path == "src/app.py"
    assert run.predictions[1].retrieval_result is not None
    assert run.predictions[1].retrieval_result.items == []


def test_live_rag_runner_retries_invalid_final_json(tmp_path: Path) -> None:
    write_workspace(tmp_path)
    cases = make_cases()
    _, factory = make_factory(
        [
            make_client(
                query=cases[0].query,
                workspace=tmp_path,
                answer="not-json",
            ),
            make_client(
                query=cases[0].query,
                workspace=tmp_path,
                answer=RAGAgentAnswer(
                    answer="alpha 会 return 结果。",
                    cited_paths=["src/app.py"],
                    insufficient_evidence=False,
                ),
            ),
            make_client(
                query=cases[1].query,
                workspace=tmp_path,
                answer=RAGAgentAnswer(
                    answer="没有相关证据。",
                    cited_paths=[],
                    insufficient_evidence=True,
                ),
            ),
        ]
    )

    run = run_live_rag_agent_eval(
        cases,
        workspace=tmp_path,
        llm_client_factory=factory,
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
        max_attempts=2,
    )

    assert run.predictions[0].attempt_count == 2
    assert run.predictions[0].attempt_errors == ["INVALID_FINAL_ANSWER"]
    assert run.metrics.end_to_end_success_rate == 1


def test_live_metrics_penalize_hallucinated_citation_and_missing_keyword(
    tmp_path: Path,
) -> None:
    write_workspace(tmp_path)
    cases = make_cases()
    _, factory = make_factory(
        [
            make_client(
                query=cases[0].query,
                workspace=tmp_path,
                answer=RAGAgentAnswer(
                    answer="alpha 存在。",
                    cited_paths=["src/missing.py"],
                    insufficient_evidence=False,
                ),
            ),
            make_client(
                query=cases[1].query,
                workspace=tmp_path,
                answer=RAGAgentAnswer(
                    answer="没有相关证据。",
                    cited_paths=[],
                    insufficient_evidence=True,
                ),
            ),
        ]
    )
    run = run_live_rag_agent_eval(
        cases,
        workspace=tmp_path,
        llm_client_factory=factory,
        provider="fixed-test",
        model="fixed-model",
        api_mode="test",
    )

    metrics = evaluate_live_rag_predictions(cases, run.predictions)

    assert metrics.evidence_hit_rate == 1
    assert metrics.answer_keyword_hit_rate == 0.5
    assert metrics.expected_path_citation_rate == 0
    assert metrics.grounded_citation_rate == 0
    assert metrics.end_to_end_success_rate == 0.5
    assert metrics.failed_case_ids == ["positive"]


def test_live_answer_rejects_unsafe_or_duplicate_citation_paths() -> None:
    with pytest.raises(ValidationError, match="POSIX"):
        RAGAgentAnswer(
            answer="bad",
            cited_paths=["../secret.txt"],
            insufficient_evidence=False,
        )

    with pytest.raises(ValidationError, match="重复"):
        RAGAgentAnswer(
            answer="duplicate",
            cited_paths=["src/app.py", "src/app.py"],
            insufficient_evidence=False,
        )


def test_live_report_records_provider_metrics_cases_and_boundary(
    tmp_path: Path,
) -> None:
    write_workspace(tmp_path)
    cases = make_cases()
    _, factory = make_factory(
        [
            make_client(
                query=cases[0].query,
                workspace=tmp_path,
                answer=RAGAgentAnswer(
                    answer="alpha 会 return 结果。",
                    cited_paths=["src/app.py"],
                    insufficient_evidence=False,
                ),
            ),
            make_client(
                query=cases[1].query,
                workspace=tmp_path,
                answer=RAGAgentAnswer(
                    answer="没有证据。",
                    cited_paths=[],
                    insufficient_evidence=True,
                ),
            ),
        ]
    )
    run = run_live_rag_agent_eval(
        cases,
        workspace=tmp_path,
        llm_client_factory=factory,
        provider="openai-compatible-live",
        model="real-model",
        api_mode="responses",
    )

    report = render_live_rag_report(
        run,
        generated_at="2026-07-30T00:00:00Z",
        commit_id="abc123",
    )

    assert "openai-compatible-live" in report
    assert "real-model" in report
    assert "knowledge_retrieve Tool Call Rate" in report
    assert "End-to-End Success Rate" in report
    assert "### positive" in report
    assert "`src/app.py`" in report
    assert "live LLM provider through AgentRuntime" in report
