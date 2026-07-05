from datetime import timezone

import pytest
from pydantic import ValidationError

from devagent.event import (
    AgentError,
    AgentFinished,
    AgentStarted,
    BaseEvent,
    EventType,
    InMemorySequenceAllocator,
    LLMCallFinished,
    LLMCallStarted,
    PermissionRequested,
    PermissionResolved,
    REDACTED_VALUE,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
    redact_sensitive_values,
)


def test_base_event_defaults_and_json_serialization():
    event = BaseEvent(
        task_id="task_1",
        event_type=EventType.AGENT_STARTED,
        sequence_id=1,
        message="Agent started",
    )

    dumped = event.model_dump(mode="json")

    assert event.event_id
    assert event.timestamp.tzinfo == timezone.utc
    assert dumped["event_type"] == "agent_started"
    assert isinstance(dumped["timestamp"], str)
    assert dumped["sequence_id"] == 1


def test_event_type_values_are_stable():
    assert EventType.TOOL_CALL_STARTED.value == "tool_call_started"
    assert EventType.PERMISSION_RESOLVED.value == "permission_resolved"


def test_agent_events_fix_event_type_and_fields():
    started = AgentStarted(
        task_id="task_1",
        sequence_id=1,
        message="Agent started",
        user_input="请分析项目",
    )
    finished = AgentFinished(
        task_id="task_1",
        sequence_id=2,
        message="Agent finished",
        status="success",
        final_answer="done",
    )
    failed = AgentError(
        task_id="task_1",
        sequence_id=3,
        message="Agent failed",
        error_message="LLM error",
    )

    assert started.event_type == EventType.AGENT_STARTED
    assert started.user_input == "请分析项目"
    assert finished.event_type == EventType.AGENT_FINISHED
    assert finished.status == "success"
    assert finished.final_answer == "done"
    assert failed.event_type == EventType.AGENT_ERROR
    assert failed.error_message == "LLM error"


def test_llm_events_fix_event_type_and_fields():
    started = LLMCallStarted(
        task_id="task_1",
        sequence_id=1,
        message="LLM started",
        step=1,
        message_count=2,
    )
    finished = LLMCallFinished(
        task_id="task_1",
        sequence_id=2,
        message="LLM finished",
        step=1,
        response_type="tool_calls",
        tool_call_count=1,
    )

    assert started.event_type == EventType.LLM_CALL_STARTED
    assert started.step == 1
    assert started.message_count == 2
    assert finished.event_type == EventType.LLM_CALL_FINISHED
    assert finished.response_type == "tool_calls"
    assert finished.tool_call_count == 1


def test_tool_events_fix_event_type_and_fields():
    started = ToolCallStarted(
        task_id="task_1",
        sequence_id=1,
        message="Tool started",
        tool_call_id="tool_call_1",
        tool_name="run_shell",
        arguments={"command": ["pytest", "-q"]},
    )
    finished = ToolCallFinished(
        task_id="task_1",
        sequence_id=2,
        message="Tool finished",
        tool_call_id="tool_call_1",
        tool_name="run_shell",
        success=True,
        duration_ms=12.5,
    )
    failed = ToolCallFailed(
        task_id="task_1",
        sequence_id=3,
        message="Tool failed",
        tool_call_id="tool_call_1",
        tool_name="run_shell",
        error_code="PERMISSION_DENIED",
        error_message="blocked",
    )

    assert started.event_type == EventType.TOOL_CALL_STARTED
    assert started.tool_call_id == "tool_call_1"
    assert started.tool_name == "run_shell"
    assert started.arguments == {"command": ["pytest", "-q"]}
    assert finished.event_type == EventType.TOOL_CALL_FINISHED
    assert finished.success is True
    assert finished.duration_ms == 12.5
    assert failed.event_type == EventType.TOOL_CALL_FAILED
    assert failed.error_code == "PERMISSION_DENIED"


def test_permission_events_fix_event_type_and_fields():
    requested = PermissionRequested(
        task_id="task_1",
        sequence_id=1,
        message="Permission requested",
        request_id="request_1",
        tool_name="run_shell",
        risk_level="HIGH",
    )
    resolved = PermissionResolved(
        task_id="task_1",
        sequence_id=2,
        message="Permission resolved",
        request_id="request_1",
        decision="ALLOW",
        status="APPROVED",
    )

    assert requested.event_type == EventType.PERMISSION_REQUESTED
    assert requested.request_id == "request_1"
    assert requested.tool_name == "run_shell"
    assert requested.risk_level == "HIGH"
    assert resolved.event_type == EventType.PERMISSION_RESOLVED
    assert resolved.decision == "ALLOW"
    assert resolved.status == "APPROVED"


def test_sequence_allocator_is_monotonic_per_task():
    allocator = InMemorySequenceAllocator()

    assert allocator.next("task_1") == 1
    assert allocator.next("task_1") == 2
    assert allocator.next("task_1") == 3


def test_sequence_allocator_is_independent_between_tasks():
    allocator = InMemorySequenceAllocator()

    assert allocator.next("task_1") == 1
    assert allocator.next("task_2") == 1
    assert allocator.next("task_1") == 2
    assert allocator.next("task_2") == 2


def test_sequence_id_less_than_one_is_rejected():
    with pytest.raises(ValidationError):
        BaseEvent(
            task_id="task_1",
            event_type=EventType.AGENT_STARTED,
            sequence_id=0,
            message="bad sequence",
        )


def test_redact_sensitive_values_recursively_redacts_known_sensitive_keys():
    payload = {
        "headers": {"Authorization": "Bearer xxx"},
        "api_key": "sk-test",
        "password": "pw",
        "token": "tok",
        "secret": "sec",
        "items": [{"apiKey": "nested-key"}],
        "query": "ToolExecutor",
    }

    redacted = redact_sensitive_values(payload)

    assert redacted["headers"]["Authorization"] == REDACTED_VALUE
    assert redacted["api_key"] == REDACTED_VALUE
    assert redacted["password"] == REDACTED_VALUE
    assert redacted["token"] == REDACTED_VALUE
    assert redacted["secret"] == REDACTED_VALUE
    assert redacted["items"][0]["apiKey"] == REDACTED_VALUE
    assert redacted["query"] == "ToolExecutor"


def test_base_event_payload_is_redacted_on_creation():
    event = BaseEvent(
        task_id="task_1",
        event_type=EventType.AGENT_STARTED,
        sequence_id=1,
        message="Agent started",
        payload={"api_key": "sk-test", "query": "hello"},
    )

    assert event.payload == {"api_key": REDACTED_VALUE, "query": "hello"}


def test_tool_call_started_arguments_are_redacted_on_creation():
    event = ToolCallStarted(
        task_id="task_1",
        sequence_id=1,
        message="Tool started",
        tool_call_id="tool_call_1",
        tool_name="external_tool",
        arguments={"token": "secret-token", "query": "hello"},
    )

    assert event.arguments == {"token": REDACTED_VALUE, "query": "hello"}
