from copy import deepcopy

import pytest
from pydantic import BaseModel, ValidationError

from devagent.agent import (
    AgentRunStatus,
    AgentRuntime,
    ContextCompressionError,
    ContextCompressionResult,
    ContextManager,
    ContextPolicy,
    count_message_chars,
)
from devagent.llm.mock_client import MockLLMClient
from devagent.llm.models import LLMResponse, ToolCall
from devagent.memory import EvidenceSnippet, LineRange, RetrievalResult
from devagent.tools import (
    BaseTool,
    ErrorCode,
    RiskLevel,
    ToolRegistry,
    ToolResult,
)


def anchors(
    *,
    system: str = "You are a coding agent.",
    user: str = "Diagnose the upload timeout.",
) -> list[dict[str, object]]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def assistant_tool_call(
    call_id: str,
    name: str,
) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": {"query": call_id}},
            }
        ],
    }


def assistant_multiple_tool_calls(
    calls: list[tuple[str, str]],
) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": {}},
            }
            for call_id, name in calls
        ],
    }


def tool_message(
    call_id: str,
    name: str,
    result: ToolResult | None = None,
) -> dict[str, object]:
    actual_result = result or ToolResult.ok(f"result for {call_id}")
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": actual_result.model_dump_json(),
    }


def knowledge_tool_message(
    call_id: str = "knowledge-1",
    *,
    item_count: int = 2,
    excerpt_chars: int = 100,
) -> dict[str, object]:
    items = [
        EvidenceSnippet(
            chunk_id=f"chunk-{index}",
            document_id=f"document-{index}",
            source="workspace",
            path=f"src/module_{index}.py",
            line_range=LineRange(start=index, end=index + 1),
            excerpt=f"evidence-{index} " + "x" * excerpt_chars,
            score=2 - index / 10,
            rank=index,
        )
        for index in range(1, item_count + 1)
    ]
    retrieval = RetrievalResult(
        query="upload timeout",
        top_k=5,
        total_candidates=item_count,
        items=items,
        retrieval_ms=1,
    )
    return tool_message(
        call_id,
        "knowledge_retrieve",
        ToolResult.ok(retrieval.model_dump_json()),
    )


def tool_exchange(
    call_id: str,
    name: str,
    result: ToolResult | None = None,
) -> list[dict[str, object]]:
    return [
        assistant_tool_call(call_id, name),
        tool_message(call_id, name, result),
    ]


def test_context_policy_has_strict_bounded_fields() -> None:
    assert ContextPolicy().max_chars == 12_000

    for payload in (
        {"max_chars": 499},
        {"max_chars": True},
        {"recent_blocks": 0},
        {"recent_blocks": True},
        {"max_tool_result_chars": 499},
        {"unexpected": 1},
    ):
        with pytest.raises(ValidationError):
            ContextPolicy.model_validate(payload)


def test_compression_result_rejects_inconsistent_counts() -> None:
    messages = anchors()
    with pytest.raises(ValidationError, match="compressed_message_count"):
        ContextCompressionResult(
            messages=messages,
            original_chars=100,
            compressed_chars=50,
            reduction_rate=0.5,
            original_message_count=2,
            compressed_message_count=3,
            dropped_message_count=0,
            preserved_evidence_count=0,
            truncated_tool_result_count=0,
            compressed=True,
        )


def test_compression_result_rejects_inconsistent_reduction_rate() -> None:
    with pytest.raises(ValidationError, match="reduction_rate"):
        ContextCompressionResult(
            messages=anchors(),
            original_chars=100,
            compressed_chars=50,
            reduction_rate=0.2,
            original_message_count=2,
            compressed_message_count=2,
            dropped_message_count=0,
            preserved_evidence_count=0,
            truncated_tool_result_count=0,
            compressed=True,
        )


def test_count_message_chars_is_stable_complete_and_non_mutating() -> None:
    messages = anchors()
    messages.append(assistant_tool_call("call-1", "search_code"))
    original = deepcopy(messages)
    reordered = [
        {
            "content": message.get("content"),
            "role": message["role"],
            **{
                key: value
                for key, value in message.items()
                if key not in {"content", "role"}
            },
        }
        for message in messages
    ]

    assert count_message_chars(messages) == count_message_chars(reordered)
    assert count_message_chars(messages) > sum(
        len(str(message.get("content", ""))) for message in messages
    )
    assert messages == original


def test_count_message_chars_rejects_non_json_value() -> None:
    messages = anchors()
    messages[1]["metadata"] = {"bad": {1, 2}}

    with pytest.raises(ContextCompressionError, match="JSON"):
        count_message_chars(messages)


@pytest.mark.parametrize(
    ("messages", "error"),
    [
        ([], "不能为空"),
        ([{"role": "user", "content": "task"}], "system"),
        ([{"role": "system", "content": "system"}], "user"),
        (
            anchors() + [{"role": "developer", "content": "hidden"}],
            "role",
        ),
        (
            anchors()
            + [
                {
                    "role": "tool",
                    "tool_call_id": "orphan",
                    "name": "read_file",
                    "content": "{}",
                }
            ],
            "缺少对应",
        ),
    ],
)
def test_manager_rejects_invalid_message_envelopes(
    messages: list[dict[str, object]],
    error: str,
) -> None:
    with pytest.raises(ContextCompressionError, match=error):
        ContextManager().compress(messages)


def test_manager_rejects_missing_mismatched_and_duplicate_tool_results() -> None:
    missing = anchors() + [assistant_tool_call("call-1", "read_file")]
    with pytest.raises(ContextCompressionError, match="缺少结果"):
        ContextManager().compress(missing)

    mismatched = (
        anchors()
        + [assistant_tool_call("call-1", "read_file")]
        + [tool_message("call-2", "read_file")]
    )
    with pytest.raises(ContextCompressionError, match="不匹配"):
        ContextManager().compress(mismatched)

    duplicate_result = (
        anchors()
        + [assistant_tool_call("call-1", "read_file")]
        + [
            tool_message("call-1", "read_file"),
            tool_message("call-1", "read_file"),
        ]
    )
    with pytest.raises(ContextCompressionError, match="重复"):
        ContextManager().compress(duplicate_result)


def test_manager_rejects_duplicate_tool_call_ids_across_blocks() -> None:
    messages = (
        anchors()
        + tool_exchange("call-1", "read_file")
        + tool_exchange("call-1", "search_code")
    )

    with pytest.raises(ContextCompressionError, match="重复"):
        ContextManager().compress(messages)


def test_budget_sufficient_returns_equal_deep_copy() -> None:
    messages = anchors() + tool_exchange("call-1", "read_file")
    original = deepcopy(messages)

    result = ContextManager().compress(messages)

    assert result.messages == messages
    assert result.messages is not messages
    assert result.compressed is False
    assert result.reduction_rate == 0
    assert messages == original


def test_multiple_tool_results_remain_one_atomic_block() -> None:
    assistant = assistant_multiple_tool_calls(
        [("call-a", "read_file"), ("call-b", "search_code")]
    )
    messages = (
        anchors()
        + [{"role": "assistant", "content": "old" * 500}]
        + [
            assistant,
            tool_message("call-b", "search_code"),
            tool_message("call-a", "read_file"),
        ]
    )
    latest_block = [assistant, messages[-2], messages[-1]]
    max_chars = count_message_chars(anchors() + latest_block) + 20
    manager = ContextManager(
        ContextPolicy(
            max_chars=max(500, max_chars),
            recent_blocks=1,
            max_tool_result_chars=1_000,
        )
    )

    result = manager.compress(messages)

    assert [message["role"] for message in result.messages[-3:]] == [
        "assistant",
        "tool",
        "tool",
    ]
    assert {
        message["tool_call_id"]
        for message in result.messages
        if message["role"] == "tool"
    } == {"call-a", "call-b"}


def test_compression_keeps_anchors_latest_and_respects_budget() -> None:
    messages = (
        anchors()
        + [{"role": "assistant", "content": "old-noise-" * 300}]
        + [{"role": "assistant", "content": "middle-noise-" * 300}]
        + [{"role": "assistant", "content": "latest observation"}]
    )
    max_chars = count_message_chars(anchors() + [messages[-1]]) + 50
    budget = max(500, max_chars)

    result = ContextManager(
        ContextPolicy(
            max_chars=budget,
            recent_blocks=1,
            max_tool_result_chars=500,
        )
    ).compress(messages)

    assert result.messages[:2] == anchors()
    assert result.messages[-1]["content"] == "latest observation"
    assert result.compressed_chars <= budget
    assert "old-noise" not in str(result.messages)
    assert result.dropped_message_count == 2


def test_old_evidence_is_prioritized_over_old_ordinary_message() -> None:
    evidence_exchange = [
        assistant_tool_call("knowledge-1", "knowledge_retrieve"),
        knowledge_tool_message(),
    ]
    latest = {"role": "assistant", "content": "latest"}
    candidate = anchors() + evidence_exchange + [latest]
    max_chars = count_message_chars(candidate) + 30
    messages = (
        anchors()
        + [{"role": "assistant", "content": "ordinary-" * 500}]
        + evidence_exchange
        + [{"role": "assistant", "content": "recent-noise-" * 500}]
        + [latest]
    )

    result = ContextManager(
        ContextPolicy(
            max_chars=max_chars,
            recent_blocks=1,
            max_tool_result_chars=4_000,
        )
    ).compress(messages)

    assert any(
        message.get("name") == "knowledge_retrieve" for message in result.messages
    )
    assert "ordinary-" not in str(result.messages)
    assert "recent-noise-" not in str(result.messages)
    assert result.preserved_evidence_count == 2


def test_old_failure_is_prioritized_over_old_success() -> None:
    failure = ToolResult.fail(
        error_code=ErrorCode.TOOL_EXECUTION_ERROR,
        error_message="permission denied",
    )
    failure_exchange = tool_exchange("failed", "run_shell", failure)
    latest = {"role": "assistant", "content": "latest"}
    max_chars = count_message_chars(anchors() + failure_exchange + [latest]) + 30
    messages = (
        anchors()
        + tool_exchange("success", "read_file")
        + failure_exchange
        + [{"role": "assistant", "content": "noise-" * 500}]
        + [latest]
    )

    result = ContextManager(
        ContextPolicy(
            max_chars=max_chars,
            recent_blocks=1,
            max_tool_result_chars=1_000,
        )
    ).compress(messages)

    assert any(message.get("tool_call_id") == "failed" for message in result.messages)
    assert not any(
        message.get("tool_call_id") == "success" for message in result.messages
    )


def test_long_generic_tool_result_is_truncated_as_valid_tool_result() -> None:
    long_result = ToolResult.ok("large-output-" * 1_000)
    messages = anchors() + tool_exchange("large", "read_file", long_result)
    manager = ContextManager(
        ContextPolicy(
            max_chars=1_500,
            recent_blocks=1,
            max_tool_result_chars=700,
        )
    )

    result = manager.compress(messages)
    compacted_message = result.messages[-1]
    compacted_result = ToolResult.model_validate_json(compacted_message["content"])

    assert result.truncated_tool_result_count == 1
    assert compacted_result.success is True
    assert compacted_result.metadata["context_truncated"] is True
    assert "[context truncated]" in compacted_result.content
    assert len(compacted_message["content"]) <= 700


def test_long_knowledge_result_remains_valid_and_located() -> None:
    knowledge_message = knowledge_tool_message(item_count=3, excerpt_chars=1_000)
    messages = anchors() + [
        assistant_tool_call("knowledge-1", "knowledge_retrieve"),
        knowledge_message,
    ]
    manager = ContextManager(
        ContextPolicy(
            max_chars=2_000,
            recent_blocks=1,
            max_tool_result_chars=1_300,
        )
    )

    result = manager.compress(messages)
    outer_result = ToolResult.model_validate_json(result.messages[-1]["content"])
    retrieval = RetrievalResult.model_validate_json(outer_result.content)

    assert result.truncated_tool_result_count == 1
    assert retrieval.items
    assert [item.rank for item in retrieval.items] == list(
        range(1, len(retrieval.items) + 1)
    )
    assert all(item.source and item.path for item in retrieval.items)
    assert all(item.line_range.start >= 1 for item in retrieval.items)


def test_malformed_tool_result_becomes_safe_failure_observation() -> None:
    malformed = {
        "role": "tool",
        "tool_call_id": "broken",
        "name": "read_file",
        "content": "not-json-" * 500,
    }
    messages = anchors() + [assistant_tool_call("broken", "read_file"), malformed]

    result = ContextManager(
        ContextPolicy(
            max_chars=1_500,
            recent_blocks=1,
            max_tool_result_chars=700,
        )
    ).compress(messages)
    compacted = ToolResult.model_validate_json(result.messages[-1]["content"])

    assert compacted.success is False
    assert compacted.metadata["malformed_original"] is True
    assert compacted.metadata["context_truncated"] is True


def test_compression_is_repeatable_and_does_not_mutate_input() -> None:
    messages = (
        anchors()
        + [{"role": "assistant", "content": "old-" * 1_000}]
        + tool_exchange("large", "read_file", ToolResult.ok("result-" * 1_000))
    )
    original = deepcopy(messages)
    manager = ContextManager(
        ContextPolicy(
            max_chars=1_500,
            recent_blocks=1,
            max_tool_result_chars=700,
        )
    )

    first = manager.compress(messages)
    second = manager.compress(messages)

    assert first == second
    assert messages == original


def test_fixed_long_history_reduces_context_by_at_least_40_percent() -> None:
    messages = anchors()
    for index in range(6):
        messages.extend(
            tool_exchange(
                f"read-{index}",
                "read_file",
                ToolResult.ok(f"file-{index}\n" + "content " * 500),
            )
        )
    messages.extend(
        [
            assistant_tool_call("knowledge-1", "knowledge_retrieve"),
            knowledge_tool_message(item_count=3, excerpt_chars=300),
        ]
    )
    messages.append({"role": "assistant", "content": "latest reasoning"})
    manager = ContextManager(
        ContextPolicy(
            max_chars=4_000,
            recent_blocks=2,
            max_tool_result_chars=1_500,
        )
    )

    result = manager.compress(messages)

    assert result.reduction_rate >= 0.4
    assert result.compressed_chars <= 4_000
    assert result.messages[:2] == anchors()
    assert result.messages[-1]["content"] == "latest reasoning"
    assert result.preserved_evidence_count >= 1


class LargeObservationArgs(BaseModel):
    query: str


class LargeObservationTool(BaseTool[LargeObservationArgs]):
    name = "large_observation"
    description = "返回超长测试观察"
    args_model = LargeObservationArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: LargeObservationArgs) -> ToolResult:
        return ToolResult.ok(f"{args.query}\n" + "observation " * 1_000)


def test_runtime_sends_compressed_view_but_keeps_canonical_history() -> None:
    client = MockLLMClient(
        responses=[
            LLMResponse.tool_calls_response(
                [
                    ToolCall(
                        id="large-1",
                        name="large_observation",
                        arguments={"query": "timeout"},
                    )
                ]
            ),
            LLMResponse.final_answer("done"),
        ]
    )
    registry = ToolRegistry()
    registry.register(LargeObservationTool())
    manager = ContextManager(
        ContextPolicy(
            max_chars=1_500,
            recent_blocks=1,
            max_tool_result_chars=700,
        )
    )
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=registry,
        context_manager=manager,
    )

    result = runtime.run("diagnose")

    canonical_tool = next(
        message for message in result.messages if message["role"] == "tool"
    )
    request_tool = next(
        message for message in client.requests[1] if message["role"] == "tool"
    )
    assert result.success is True
    assert len(canonical_tool["content"]) > len(request_tool["content"])
    assert count_message_chars(client.requests[1]) <= 1_500
    assert result.messages == runtime.messages
    assert len(runtime.context_history) == 2
    assert runtime.context_history[-1].compressed is True


def test_runtime_fails_closed_when_anchors_exceed_budget() -> None:
    client = MockLLMClient(responses=[LLMResponse.final_answer("unused")])
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=ToolRegistry(),
        context_manager=ContextManager(
            ContextPolicy(
                max_chars=500,
                recent_blocks=1,
                max_tool_result_chars=500,
            )
        ),
    )

    result = runtime.run("x" * 1_000)

    assert result.success is False
    assert result.status == AgentRunStatus.LLM_ERROR
    assert result.error_message is not None
    assert result.error_message.startswith("构造 LLM 上下文失败")
    assert client.call_count == 0
    assert runtime.context_history == []
