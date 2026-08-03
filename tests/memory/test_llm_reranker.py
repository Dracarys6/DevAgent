import json
from typing import Any

import pytest

from devagent.llm import LLMResponse, ToolCall
from devagent.memory import (
    EvidenceSnippet,
    LineRange,
    RerankerError,
)
from devagent.memory.llm_reranker import LLMReranker, LLMRerankerConfig


class SequenceLLMClient:
    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_candidate(chunk_id: str, *, excerpt: str | None = None) -> EvidenceSnippet:
    return EvidenceSnippet(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source="workspace",
        path=f"src/{chunk_id}.py",
        line_range=LineRange(start=1, end=2),
        excerpt=excerpt or f"evidence {chunk_id}",
        score=0.1,
        rank=1 if chunk_id == "a" else 2,
    )


def make_reranker(
    responses: list[LLMResponse | Exception],
    **config: object,
) -> tuple[LLMReranker, SequenceLLMClient]:
    client = SequenceLLMClient(responses)
    reranker = LLMReranker(
        llm_client=client,
        config=LLMRerankerConfig(
            model_name="live-model",
            **config,  # type: ignore[arg-type]
        ),
    )
    return reranker, client


def test_llm_reranker_builds_bounded_prompt_and_restores_ids() -> None:
    reranker, client = make_reranker(
        [
            LLMResponse.final_answer(
                '{"scores":[{"chunk_id":"b","score":0.9},{"chunk_id":"a","score":0.2}]}'
            )
        ],
        max_excerpt_chars=5,
    )

    scores = reranker.score(
        "find evidence",
        [make_candidate("a", excerpt="abcdefgh"), make_candidate("b")],
    )

    assert [(item.chunk_id, item.score) for item in scores] == [
        ("b", 0.9),
        ("a", 0.2),
    ]
    payload = json.loads(client.calls[0][1]["content"])
    assert payload["query"] == "find evidence"
    assert payload["candidates"][0]["excerpt"] == "abcde"
    assert '"scores"' in client.calls[0][0]["content"]
    assert reranker.request_count == 1
    assert reranker.repair_count == 0
    assert reranker.last_attempt_count == 1
    assert reranker.reranker_name == "llm:live-model"
    assert reranker.scored_candidate_count == 2
    assert reranker.input_char_count > 0
    assert reranker.output_char_count > 0
    assert reranker.timeout_seconds is None
    assert reranker.transport_max_retries is None


def test_invalid_json_is_repaired_on_second_attempt() -> None:
    reranker, client = make_reranker(
        [
            LLMResponse.final_answer("not-json private output"),
            LLMResponse.final_answer(
                '{"scores":[{"chunk_id":"a","score":0.8},{"chunk_id":"b","score":0.3}]}'
            ),
        ]
    )

    scores = reranker.score("query", [make_candidate("a"), make_candidate("b")])

    assert len(scores) == 2
    assert reranker.request_count == 2
    assert reranker.repair_count == 1
    assert reranker.last_attempt_count == 2
    assert reranker.scored_candidate_count == 2
    assert reranker.input_char_count > len(str(client.calls[0]))
    assert len(client.calls[1]) == 3
    assert "not-json" not in str(client.calls[1])
    assert "契约" in client.calls[1][-1]["content"]


@pytest.mark.parametrize(
    ("content", "error_code"),
    [
        ("not-json", "invalid_json"),
        ('{"scores":[{"chunk_id":"a","score":2}]}', "schema_mismatch"),
        (
            '{"scores":[{"chunk_id":"unknown","score":0.5}]}',
            "candidate_id_mismatch",
        ),
    ],
)
def test_repeated_invalid_output_raises_sanitized_error(
    content: str,
    error_code: str,
) -> None:
    reranker, _ = make_reranker(
        [LLMResponse.final_answer(content), LLMResponse.final_answer(content)]
    )

    with pytest.raises(RerankerError) as captured:
        reranker.score("private query", [make_candidate("a")])

    assert captured.value.code == error_code
    assert "private query" not in str(captured.value)
    assert content not in str(captured.value)


def test_transport_error_is_not_retried() -> None:
    reranker, client = make_reranker([ConnectionError("secret provider body")])

    with pytest.raises(RerankerError) as captured:
        reranker.score("private query", [make_candidate("a")])

    assert captured.value.code == "llm_call_failed"
    assert len(client.calls) == 1
    assert reranker.repair_count == 0
    assert "secret" not in str(captured.value)


def test_tool_call_response_is_rejected_without_schema_retry() -> None:
    response = LLMResponse.tool_calls_response(
        [ToolCall(id="call-1", name="read_file", arguments={})]
    )
    reranker, client = make_reranker([response])

    with pytest.raises(RerankerError) as captured:
        reranker.score("query", [make_candidate("a")])

    assert captured.value.code == "unexpected_response"
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"model_name": ""}, "model_name"),
        ({"model_name": "model", "max_attempts": 0}, "max_attempts"),
        ({"model_name": "model", "max_candidates": 21}, "max_candidates"),
        ({"model_name": "model", "max_excerpt_chars": True}, "整数"),
    ],
)
def test_llm_reranker_config_validation(
    kwargs: dict[str, object],
    error: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=error):
        LLMRerankerConfig(**kwargs)  # type: ignore[arg-type]
