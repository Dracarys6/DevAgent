from datetime import UTC, datetime

from devagent.event import (
    AgentError,
    AgentFinished,
    AgentStarted,
    InMemoryEventBus,
    LLMCallFinished,
    PermissionRequested,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
)
from devagent.trace import TaskTrace, TraceService


def test_trace_service_returns_steps_sorted_by_sequence_id():
    event_bus = InMemoryEventBus()
    trace_service = TraceService(event_bus=event_bus)
    event_bus.publish(
        AgentFinished(
            task_id="task1",
            sequence_id=2,
            message="Agent 运行结束",
            status="success",
            final_answer="完成",
        )
    )
    event_bus.publish(
        AgentStarted(
            task_id="task1",
            sequence_id=1,
            message="Agent 运行开始",
            user_input="请分析项目",
        )
    )

    task_trace = trace_service.get_trace("task1")

    assert isinstance(task_trace, TaskTrace)
    assert [step.sequence_id for step in task_trace.steps] == [1, 2]
    assert task_trace.summary.first_sequence_id == 1
    assert task_trace.summary.last_sequence_id == 2


def test_trace_summary_extracts_final_status_and_answer():
    event_bus = InMemoryEventBus()
    trace_service = TraceService(event_bus=event_bus)
    finished_at = datetime(2026, 7, 9, 8, 0, tzinfo=UTC)
    event_bus.publish(
        AgentStarted(
            task_id="task2",
            sequence_id=1,
            message="Agent 运行开始",
            user_input="请分析项目",
        )
    )
    event_bus.publish(
        AgentFinished(
            task_id="task2",
            sequence_id=2,
            message="Agent 运行结束",
            status="success",
            final_answer="已完成分析",
            timestamp=finished_at,
        )
    )

    task_trace = trace_service.get_trace("task2")

    assert task_trace.summary.final_status == "success"
    assert task_trace.summary.final_answer == "已完成分析"
    assert task_trace.summary.finished_at == finished_at


def test_trace_summary_counts_llm_tool_permission_and_error_events():
    event_bus = InMemoryEventBus()
    trace_service = TraceService(event_bus=event_bus)
    events = [
        AgentStarted(
            task_id="task3",
            sequence_id=1,
            message="Agent 运行开始",
            user_input="请分析项目",
        ),
        LLMCallFinished(
            task_id="task3",
            sequence_id=2,
            message="LLM 调用结束",
            step=1,
            response_type="tool_calls",
            tool_call_count=1,
        ),
        ToolCallFinished(
            task_id="task3",
            sequence_id=3,
            message="工具调用完成",
            tool_call_id="call_1",
            tool_name="read_file",
            success=True,
            duration_ms=12.5,
        ),
        ToolCallFailed(
            task_id="task3",
            sequence_id=4,
            message="工具调用失败",
            tool_call_id="call_2",
            tool_name="run_shell",
            error_code="PERMISSION_DENIED",
            error_message="权限不足",
        ),
        PermissionRequested(
            task_id="task3",
            sequence_id=5,
            message="请求权限",
            request_id="perm_1",
            tool_name="run_shell",
            risk_level="HIGH",
        ),
        AgentError(
            task_id="task3",
            sequence_id=6,
            message="Agent 运行失败",
            error_message="工具失败",
            payload={"status": "tool_error"},
        ),
    ]
    for event in events:
        event_bus.publish(event)

    task_trace = trace_service.get_trace("task3")

    assert task_trace.summary.event_count == 6
    assert task_trace.summary.final_status == "tool_error"
    assert task_trace.summary.llm_call_count == 1
    assert task_trace.summary.tool_call_count == 2
    assert task_trace.summary.permission_request_count == 1
    assert task_trace.summary.error_count == 2


def test_trace_step_details_include_event_specific_fields():
    event_bus = InMemoryEventBus()
    trace_service = TraceService(event_bus=event_bus)
    event_bus.publish(
        ToolCallStarted(
            task_id="task4",
            sequence_id=1,
            message="工具调用开始",
            tool_call_id="call_1",
            tool_name="read_file",
            arguments={
                "file_path": "README.md",
                "api_key": "secret",
            },
        )
    )

    task_trace = trace_service.get_trace("task4")

    assert task_trace.steps[0].payload == {}
    assert task_trace.steps[0].details == {
        "tool_call_id": "call_1",
        "tool_name": "read_file",
        "arguments": {
            "file_path": "README.md",
            "api_key": "[REDACTED]",
        },
    }


def test_trace_service_returns_empty_trace_for_task_without_events():
    event_bus = InMemoryEventBus()
    trace_service = TraceService(event_bus=event_bus)

    task_trace = trace_service.get_trace("empty-task")

    assert task_trace.task_id == "empty-task"
    assert task_trace.steps == []
    assert task_trace.summary.event_count == 0
    assert task_trace.summary.first_sequence_id is None
    assert task_trace.summary.last_sequence_id is None
    assert task_trace.summary.started_at is None
    assert task_trace.summary.finished_at is None
