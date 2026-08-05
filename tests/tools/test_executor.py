from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from devagent.event import EventType, InMemoryEventBus, InMemorySequenceAllocator
from devagent.llm import ToolCall
from devagent.permission import (
    InMemoryPermissionManager,
    InMemoryPermissionPolicyStore,
    PermissionDecision,
    RiskLevel,
)
from devagent.security import CommandGuard
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import AgentTask, SQLiteTaskRepository
from devagent.tools import (
    BaseTool,
    ErrorCode,
    SQLiteToolCallStore,
    ToolExecutionContext,
    ToolExecutionStatus,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
)
from devagent.tools.builtin import RunShellArgs
from devagent.tools.executor import PermissionResumeError


class EchoArgs(BaseModel):
    text: str


class EchoTool(BaseTool[EchoArgs]):
    name = "echo"
    description = "返回输入文本。"
    args_model = EchoArgs
    risk_level = RiskLevel.LOW

    def execute(self, args: EchoArgs) -> ToolResult:
        return ToolResult.ok(args.text)


class SpyShellTool(BaseTool[RunShellArgs]):
    name = "run_shell"
    description = "测试 shell 工具。"
    args_model = RunShellArgs
    risk_level = RiskLevel.HIGH

    def __init__(self) -> None:
        self.call_count = 0
        self.last_args: RunShellArgs | None = None

    def execute(self, args: RunShellArgs) -> ToolResult:
        self.call_count += 1
        self.last_args = args
        return ToolResult.ok("shell executed", metadata={"command": args.command})


class RecordingCommandGuard(CommandGuard):
    def __init__(self) -> None:
        self.calls: list[tuple[list[Any], str | None]] = []

    def validate(self, command: list[Any], workspace: str | Path | None = None):
        self.calls.append((command, None if workspace is None else str(workspace)))
        return super().validate(command, workspace)


def create_executor(
    *,
    shell_tool: SpyShellTool | None = None,
    command_guard: CommandGuard | None = None,
) -> tuple[
    ToolExecutor,
    InMemoryPermissionManager,
    InMemoryPermissionPolicyStore,
    SpyShellTool,
]:
    shell_tool = shell_tool or SpyShellTool()
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(shell_tool)
    permission_manager = InMemoryPermissionManager()
    policy_store = InMemoryPermissionPolicyStore()
    executor = ToolExecutor(
        registry=registry,
        permission_manager=permission_manager,
        policy_store=policy_store,
        command_guard=command_guard or CommandGuard(),
    )
    return executor, permission_manager, policy_store, shell_tool


def shell_call(arguments: dict[str, Any] | None = None) -> ToolCall:
    return ToolCall(
        id="call_shell_1",
        name="run_shell",
        arguments=arguments or {"command": ["pytest", "-q"], "cwd": "."},
    )


def event_context(
    *,
    bus: InMemoryEventBus | None = None,
    allocator: InMemorySequenceAllocator | None = None,
    tool_call_id: str | None = "tool_call_1",
) -> ToolExecutionContext:
    return ToolExecutionContext(
        task_id="task_1",
        session_id="session_1",
        tool_call_id=tool_call_id,
        workspace="/workspace",
        event_bus=bus or InMemoryEventBus(),
        sequence_allocator=allocator or InMemorySequenceAllocator(),
    )


def list_task_events(context: ToolExecutionContext):
    assert context.event_bus is not None
    return context.event_bus.list_events("task_1")


def test_low_risk_tool_executes_directly():
    executor, _permission_manager, _policy_store, shell_tool = create_executor()
    tool_call = ToolCall(id="call_echo_1", name="echo", arguments={"text": "hello"})

    result = executor.execute(tool_call)

    assert result.status == ToolExecutionStatus.EXECUTED
    assert result.tool_result is not None
    assert result.tool_result.success is True
    assert result.tool_result.content == "hello"
    assert shell_tool.call_count == 0


def test_executor_persists_complete_tool_call_lifecycle(tmp_path: Path):
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "executor.db"))
    database.initialize()
    SQLiteTaskRepository(database).create(
        AgentTask(task_id="task_1", question="persist tool call")
    )
    store = SQLiteToolCallStore(database)
    registry = ToolRegistry()
    registry.register(EchoTool())
    executor = ToolExecutor(registry=registry, tool_call_store=store)

    result = executor.execute(
        ToolCall(id="call-1", name="echo", arguments={"text": "hello"}),
        ToolExecutionContext(task_id="task_1"),
    )

    record = store.get("task_1", "call-1")
    assert result.tool_result == ToolResult.ok("hello")
    assert record.status == ToolExecutionStatus.EXECUTED.value
    assert record.result == ToolResult.ok("hello")
    assert record.finished_at is not None


def test_unknown_tool_returns_tool_not_found_result():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()

    result = executor.execute(ToolCall(id="call_missing", name="missing", arguments={}))

    assert result.status == ToolExecutionStatus.EXECUTED
    assert result.tool_result is not None
    assert result.tool_result.success is False
    assert result.tool_result.error_code == ErrorCode.TOOL_NOT_FOUND
    assert result.tool_result.metadata["available_tools"] == ["echo", "run_shell"]


def test_run_shell_guard_block_does_not_create_permission_or_execute_tool():
    executor, permission_manager, _policy_store, shell_tool = create_executor()

    result = executor.execute(shell_call({"command": ["rm", "-rf", "/"], "cwd": "."}))

    assert result.status == ToolExecutionStatus.BLOCKED
    assert result.tool_result is not None
    assert result.tool_result.error_code == ErrorCode.PERMISSION_DENIED
    assert result.tool_result.metadata["matched_rule"] == "rm_root"
    assert permission_manager.list_all() == []
    assert shell_tool.call_count == 0


def test_run_shell_always_deny_policy_blocks_without_permission_or_execution():
    executor, permission_manager, policy_store, shell_tool = create_executor()
    policy = policy_store.create_policy(
        name="Deny pytest",
        decision=PermissionDecision.DENY,
        tool_name="run_shell",
        risk_levels=[RiskLevel.HIGH],
        tool_arguments={"command": ["pytest", "-q"], "cwd": "."},
        reason="测试策略拒绝",
    )

    result = executor.execute(shell_call())

    assert result.status == ToolExecutionStatus.BLOCKED
    assert result.tool_result is not None
    assert result.tool_result.error_code == ErrorCode.PERMISSION_DENIED
    assert result.tool_result.metadata["policy_id"] == policy.policy_id
    assert permission_manager.list_all() == []
    assert shell_tool.call_count == 0


def test_run_shell_always_allow_policy_executes_tool():
    executor, _permission_manager, policy_store, shell_tool = create_executor()
    policy = policy_store.create_policy(
        name="Allow pytest",
        decision=PermissionDecision.ALLOW,
        tool_name="run_shell",
        risk_levels=[RiskLevel.HIGH],
        tool_arguments={"command": ["pytest", "-q"], "cwd": "."},
        reason="允许测试命令",
    )

    result = executor.execute(shell_call())

    assert result.status == ToolExecutionStatus.EXECUTED
    assert result.tool_result is not None
    assert result.tool_result.success is True
    assert result.tool_result.content == "shell executed"
    assert result.metadata["policy_id"] == policy.policy_id
    assert shell_tool.call_count == 1


def test_run_shell_without_policy_returns_waiting_permission_and_does_not_execute():
    executor, permission_manager, _policy_store, shell_tool = create_executor()
    context = ToolExecutionContext(
        task_id="task_1",
        tool_call_id="tool_call_1",
        workspace="/workspace",
    )

    result = executor.execute(shell_call(), context)

    assert result.status == ToolExecutionStatus.WAITING_PERMISSION
    assert result.tool_result is None
    assert result.permission_request is not None
    assert result.permission_request.task_id == "task_1"
    assert result.permission_request.tool_call_id == "tool_call_1"
    assert result.permission_request.tool_name == "run_shell"
    assert result.permission_request.tool_arguments == {
        "command": ["pytest", "-q"],
        "cwd": ".",
    }
    assert result.permission_request.risk_level == RiskLevel.HIGH
    assert (
        result.metadata["permission_request_id"] == result.permission_request.request_id
    )
    assert [request.request_id for request in permission_manager.list_pending()] == [
        result.permission_request.request_id
    ]
    assert shell_tool.call_count == 0


def test_approved_permission_resumes_original_tool_once():
    executor, permission_manager, _policy_store, shell_tool = create_executor()
    context = event_context()

    waiting = executor.execute(shell_call(), context)
    assert waiting.permission_request is not None
    permission_manager.resolve(
        waiting.permission_request.request_id,
        PermissionDecision.ALLOW,
    )

    resumed = executor.resume(waiting.permission_request.request_id, context)

    assert resumed.status == ToolExecutionStatus.EXECUTED
    assert resumed.tool_result is not None
    assert resumed.tool_result.success is True
    assert resumed.metadata["permission_decision"] == PermissionDecision.ALLOW.value
    assert shell_tool.call_count == 1
    assert [event.event_type for event in list_task_events(context)] == [
        EventType.TOOL_CALL_STARTED,
        EventType.PERMISSION_REQUESTED,
        EventType.PERMISSION_RESOLVED,
        EventType.TOOL_CALL_FINISHED,
    ]


def test_denied_permission_returns_tool_result_without_execution():
    executor, permission_manager, _policy_store, shell_tool = create_executor()
    context = event_context()

    waiting = executor.execute(shell_call(), context)
    assert waiting.permission_request is not None
    permission_manager.resolve(
        waiting.permission_request.request_id,
        PermissionDecision.DENY,
        decision_reason="测试拒绝",
    )

    resumed = executor.resume(waiting.permission_request.request_id, context)

    assert resumed.status == ToolExecutionStatus.BLOCKED
    assert resumed.tool_result is not None
    assert resumed.tool_result.error_code == ErrorCode.PERMISSION_DENIED
    assert resumed.tool_result.error_message == "测试拒绝"
    assert shell_tool.call_count == 0
    assert [event.event_type for event in list_task_events(context)][-1] == (
        EventType.TOOL_CALL_FAILED
    )


def test_resume_rejects_cross_task_permission_request():
    executor, permission_manager, _policy_store, shell_tool = create_executor()
    context = event_context()
    waiting = executor.execute(shell_call(), context)
    assert waiting.permission_request is not None
    permission_manager.resolve(
        waiting.permission_request.request_id,
        PermissionDecision.ALLOW,
    )

    with pytest.raises(PermissionResumeError, match="不属于当前任务"):
        executor.resume(
            waiting.permission_request.request_id,
            ToolExecutionContext(task_id="other-task"),
        )

    assert shell_tool.call_count == 0


def test_permission_request_cannot_resume_tool_twice():
    executor, permission_manager, _policy_store, shell_tool = create_executor()
    context = event_context()
    waiting = executor.execute(shell_call(), context)
    assert waiting.permission_request is not None
    permission_manager.resolve(
        waiting.permission_request.request_id,
        PermissionDecision.ALLOW,
    )

    executor.resume(waiting.permission_request.request_id, context)

    with pytest.raises(PermissionResumeError, match="已用于恢复"):
        executor.resume(waiting.permission_request.request_id, context)
    assert shell_tool.call_count == 1


def test_waiting_permission_uses_tool_call_id_when_context_omits_it():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()

    result = executor.execute(
        shell_call(),
        ToolExecutionContext(task_id="task_1"),
    )

    assert result.permission_request is not None
    assert result.permission_request.tool_call_id == "call_shell_1"


def test_command_guard_prefers_tool_arguments_workspace():
    guard = RecordingCommandGuard()
    executor, _permission_manager, policy_store, shell_tool = create_executor(
        command_guard=guard
    )
    policy_store.create_policy(
        name="Allow pytest",
        decision=PermissionDecision.ALLOW,
        tool_name="run_shell",
        risk_levels=[RiskLevel.HIGH],
        tool_arguments={
            "command": ["pytest", "-q"],
            "cwd": ".",
            "workspace": "/argument-workspace",
        },
    )

    result = executor.execute(
        shell_call(
            {
                "command": ["pytest", "-q"],
                "cwd": ".",
                "workspace": "/argument-workspace",
            }
        ),
        ToolExecutionContext(workspace="/context-workspace"),
    )

    assert result.status == ToolExecutionStatus.EXECUTED
    assert guard.calls == [(["pytest", "-q"], "/argument-workspace")]
    assert shell_tool.call_count == 1


def test_command_guard_uses_context_workspace_when_arguments_omit_workspace():
    guard = RecordingCommandGuard()
    executor, _permission_manager, _policy_store, _shell_tool = create_executor(
        command_guard=guard
    )

    result = executor.execute(
        shell_call(),
        ToolExecutionContext(workspace="/context-workspace"),
    )

    assert result.status == ToolExecutionStatus.WAITING_PERMISSION
    assert guard.calls == [(["pytest", "-q"], "/context-workspace")]


def test_tool_execution_result_is_json_serializable():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()

    result = executor.execute(
        shell_call(),
        ToolExecutionContext(task_id="task_1", tool_call_id="tool_call_1"),
    )

    dumped = result.model_dump(mode="json")
    assert dumped["status"] == "WAITING_PERMISSION"
    assert dumped["permission_request"]["tool_name"] == "run_shell"
    assert dumped["permission_request"]["risk_level"] == "HIGH"


def test_low_risk_tool_publishes_started_and_finished_events():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()
    context = event_context()
    tool_call = ToolCall(id="call_echo_1", name="echo", arguments={"text": "hello"})

    result = executor.execute(tool_call, context)

    events = list_task_events(context)
    assert result.status == ToolExecutionStatus.EXECUTED
    assert [event.event_type for event in events] == [
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_FINISHED,
    ]
    assert events[0].tool_call_id == "tool_call_1"
    assert events[0].tool_name == "echo"
    assert events[0].arguments == {"text": "hello"}
    assert events[1].success is True
    assert events[1].payload == {
        "status": ToolExecutionStatus.EXECUTED.value,
        "error_code": None,
    }


def test_unknown_tool_publishes_failed_event():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()
    context = event_context(tool_call_id=None)

    result = executor.execute(
        ToolCall(id="call_missing", name="missing", arguments={}),
        context,
    )

    events = list_task_events(context)
    assert result.tool_result is not None
    assert result.tool_result.error_code == ErrorCode.TOOL_NOT_FOUND
    assert [event.event_type for event in events] == [
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert events[0].tool_call_id == "call_missing"
    assert events[1].tool_call_id == "call_missing"
    assert events[1].error_code == ErrorCode.TOOL_NOT_FOUND.value
    assert events[1].payload["status"] == ToolExecutionStatus.EXECUTED.value


def test_guard_block_publishes_failed_event():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()
    context = event_context()

    result = executor.execute(
        shell_call({"command": ["rm", "-rf", "/"], "cwd": "."}),
        context,
    )

    events = list_task_events(context)
    assert result.status == ToolExecutionStatus.BLOCKED
    assert [event.event_type for event in events] == [
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert events[1].error_code == ErrorCode.PERMISSION_DENIED.value
    assert events[1].payload["status"] == ToolExecutionStatus.BLOCKED.value
    assert events[1].payload["reason"] == result.reason


def test_waiting_permission_publishes_permission_requested_event():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()
    context = event_context()

    result = executor.execute(shell_call(), context)

    events = list_task_events(context)
    assert result.status == ToolExecutionStatus.WAITING_PERMISSION
    assert result.permission_request is not None
    assert [event.event_type for event in events] == [
        EventType.TOOL_CALL_STARTED,
        EventType.PERMISSION_REQUESTED,
    ]
    assert events[1].request_id == result.permission_request.request_id
    assert events[1].tool_name == "run_shell"
    assert events[1].risk_level == RiskLevel.HIGH.value
    assert events[1].payload["tool_call_id"] == "tool_call_1"


def test_tool_event_redacts_sensitive_arguments():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()
    context = event_context()

    executor.execute(
        ToolCall(
            id="call_echo_sensitive",
            name="echo",
            arguments={
                "text": "hello",
                "api_key": "sk-test",
                "nested": {"token": "secret-token"},
            },
        ),
        context,
    )

    events = list_task_events(context)
    assert events[0].arguments["api_key"] == "[REDACTED]"
    assert events[0].arguments["nested"]["token"] == "[REDACTED]"


def test_tool_event_bus_subscriber_error_does_not_fail_execution():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()
    context = event_context()
    assert context.event_bus is not None
    context.event_bus.subscribe("task_1", lambda event: 1 / 0)

    result = executor.execute(
        ToolCall(id="call_echo_1", name="echo", arguments={"text": "hello"}),
        context,
    )

    events = list_task_events(context)
    assert result.status == ToolExecutionStatus.EXECUTED
    assert [event.event_type for event in events] == [
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_FINISHED,
    ]


def test_tool_and_permission_events_share_sequence_allocator():
    executor, _permission_manager, _policy_store, _shell_tool = create_executor()
    context = event_context(allocator=InMemorySequenceAllocator())

    executor.execute(shell_call(), context)

    events = list_task_events(context)
    assert [event.event_type for event in events] == [
        EventType.TOOL_CALL_STARTED,
        EventType.PERMISSION_REQUESTED,
    ]
    assert [event.sequence_id for event in events] == [1, 2]
