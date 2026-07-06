from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from devagent.llm.models import ToolCall
from devagent.permission.manager import InMemoryPermissionManager
from devagent.permission.models import PermissionDecision, PermissionRequest
from devagent.permission.policy_store import InMemoryPermissionPolicyStore
from devagent.security import CommandGuard
from devagent.tools.models import ErrorCode, RiskLevel, ToolResult
from devagent.tools.registry import ToolRegistry
from devagent.event import (
    BaseEvent,
    InMemoryEventBus,
    InMemorySequenceAllocator,
    ToolCallStarted,
    ToolCallFinished,
    ToolCallFailed,
    EventBusDeliveryError,
)


class ToolExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"
    WAITING_PERMISSION = "WAITING_PERMISSION"


class ToolExecutionContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    task_id: str | None = None
    session_id: str | None = None
    tool_call_id: str | None = None
    workspace: str | None = None
    event_bus: InMemoryEventBus | None = None
    sequence_allocator: InMemorySequenceAllocator | None = None


class ToolExecutionResult(BaseModel):
    status: ToolExecutionStatus
    tool_result: ToolResult | None = None
    permission_request: PermissionRequest | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        permission_manager: InMemoryPermissionManager | None = None,
        policy_store: InMemoryPermissionPolicyStore | None = None,
        command_guard: CommandGuard | None = None,
    ) -> None:
        self.registry = registry
        self.permission_manager = permission_manager or InMemoryPermissionManager()
        self.policy_store = policy_store or InMemoryPermissionPolicyStore()
        self.command_guard = command_guard or CommandGuard()

    def execute(
        self,
        tool_call: ToolCall,
        context: ToolExecutionContext | None = None,
    ) -> ToolExecutionResult:
        context = context or ToolExecutionContext()
        sequence_allocator = context.sequence_allocator or InMemorySequenceAllocator()
        tool_call_id = context.tool_call_id or tool_call.id

        self._publish_tool_started(
            tool_call=tool_call,
            context=context,
            sequence_allocator=sequence_allocator,
            tool_call_id=tool_call_id,
        )

        tool = self.registry.get(tool_call.name)
        if tool is None:
            tool_result = ToolResult.fail(
                ErrorCode.TOOL_NOT_FOUND,
                error_message=f"未知工具: {tool_call.name}",
                metadata={
                    "tool_name": tool_call.name,
                    "available_tools": [tool.name for tool in self.registry.list()],
                },
            )

            self._publish_tool_failed(
                tool_call=tool_call,
                context=context,
                sequence_allocator=sequence_allocator,
                tool_call_id=tool_call_id,
                error_code=ErrorCode.TOOL_NOT_FOUND,
                error_message=f"工具不存在: {tool_call.name}",
                status=ToolExecutionStatus.EXECUTED,
                reason="工具不存在",
            )

            return ToolExecutionResult(
                status=ToolExecutionStatus.EXECUTED,
                tool_result=tool_result,
                reason="工具不存在",
                metadata=tool_result.metadata,
            )

        if tool.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
            result = self._execute_registered_tool(
                tool_call,
                reason="低风险工具直接执行",
            )
            self._publish_tool_execution_result(
                result=result,
                tool_call=tool_call,
                context=context,
                sequence_allocator=sequence_allocator,
                tool_call_id=tool_call_id,
                status=ToolExecutionStatus.EXECUTED,
            )
            return result

        if tool.name == "run_shell":
            guard_result = self.command_guard.validate(
                tool_call.arguments.get("command", []),
                self._workspace_for_guard(tool_call, context),
            )
            if not guard_result.allowed:
                metadata = {
                    "tool_name": tool.name,
                    "risk_level": tool.risk_level.value,
                    "guard_decision": guard_result.decision.value,
                    "matched_rule": guard_result.matched_rule,
                }
                tool_result = ToolResult.fail(
                    ErrorCode.PERMISSION_DENIED,
                    error_message=f"命令被安全规则拦截: {guard_result.reason}",
                    metadata=metadata,
                )
                self._publish_tool_failed(
                    tool_call=tool_call,
                    context=context,
                    sequence_allocator=sequence_allocator,
                    tool_call_id=tool_call_id,
                    error_code=ErrorCode.PERMISSION_DENIED,
                    error_message=f"命令被安全规则拦截: {guard_result.reason}",
                    status=ToolExecutionStatus.BLOCKED,
                    reason=guard_result.reason,
                )
                return ToolExecutionResult(
                    status=ToolExecutionStatus.BLOCKED,
                    tool_result=tool_result,
                    reason=guard_result.reason,
                    metadata=metadata,
                )

        policy = self.policy_store.match_policy(
            tool_name=tool.name,
            risk_level=tool.risk_level,
            tool_arguments=tool_call.arguments,
        )
        if policy is not None:
            if policy.decision == PermissionDecision.DENY:
                metadata = {
                    "tool_name": tool.name,
                    "risk_level": tool.risk_level.value,
                    "policy_id": policy.policy_id,
                    "policy_decision": policy.decision.value,
                }
                tool_result = ToolResult.fail(
                    ErrorCode.PERMISSION_DENIED,
                    error_message=f"工具调用被权限策略拒绝: {policy.reason or tool.name}",
                    metadata=metadata,
                )
                self._publish_tool_failed(
                    tool_call=tool_call,
                    context=context,
                    sequence_allocator=sequence_allocator,
                    tool_call_id=tool_call_id,
                    error_code=ErrorCode.PERMISSION_DENIED,
                    error_message=(
                        f"工具调用被权限策略拒绝: {policy.reason or tool.name}"
                    ),
                    status=ToolExecutionStatus.BLOCKED,
                    reason=policy.reason or "命中拒绝策略",
                )
                return ToolExecutionResult(
                    status=ToolExecutionStatus.BLOCKED,
                    tool_result=tool_result,
                    reason=policy.reason or "命中拒绝策略",
                    metadata=metadata,
                )

            if policy.decision == PermissionDecision.ALLOW:
                result = self._execute_registered_tool(
                    tool_call,
                    reason="命中允许策略，执行高风险工具",
                    metadata={
                        "tool_name": tool.name,
                        "risk_level": tool.risk_level.value,
                        "policy_id": policy.policy_id,
                        "policy_decision": policy.decision.value,
                    },
                )
                self._publish_tool_execution_result(
                    result=result,
                    tool_call=tool_call,
                    context=context,
                    sequence_allocator=sequence_allocator,
                    tool_call_id=tool_call_id,
                    status=ToolExecutionStatus.EXECUTED,
                )
                return result

        permission_request = self.permission_manager.request_permission(
            tool_name=tool.name,
            risk_level=tool.risk_level,
            reason=f"高风险工具 {tool.name} 需要用户审批",
            tool_arguments=tool_call.arguments,
            task_id=context.task_id,
            tool_call_id=context.tool_call_id or tool_call.id,
            event_bus=context.event_bus,
            sequence_allocator=sequence_allocator,
            session_id=context.session_id,
        )
        metadata = {
            "tool_name": tool.name,
            "risk_level": tool.risk_level.value,
            "permission_request_id": permission_request.request_id,
        }

        return ToolExecutionResult(
            status=ToolExecutionStatus.WAITING_PERMISSION,
            permission_request=permission_request,
            reason="等待用户审批高风险工具执行",
            metadata=metadata,
        )

    def _execute_registered_tool(
        self,
        tool_call: ToolCall,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        tool_result = self.registry.execute(tool_call.name, tool_call.arguments)
        result_metadata = metadata or {
            "tool_name": tool_call.name,
            "success": tool_result.success,
        }
        return ToolExecutionResult(
            status=ToolExecutionStatus.EXECUTED,
            tool_result=tool_result,
            reason=reason,
            metadata=result_metadata,
        )

    def _workspace_for_guard(
        self,
        tool_call: ToolCall,
        context: ToolExecutionContext,
    ) -> str | None:
        workspace = tool_call.arguments.get("workspace")
        if isinstance(workspace, str):
            return workspace
        return context.workspace

    def _publish_tool_started(
        self,
        *,
        tool_call: ToolCall,
        context: ToolExecutionContext,
        sequence_allocator: InMemorySequenceAllocator,
        tool_call_id: str,
    ) -> None:
        if context.event_bus is None or context.task_id is None:
            return
        self._publish_event(
            ToolCallStarted(
                task_id=context.task_id,
                session_id=context.session_id,
                sequence_id=sequence_allocator.next(context.task_id),
                message=f"工具调用开始: {tool_call.name}",
                tool_call_id=tool_call_id,
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
            ),
            event_bus=context.event_bus,
        )

    def _publish_tool_execution_result(
        self,
        *,
        result: ToolExecutionResult,
        tool_call: ToolCall,
        context: ToolExecutionContext,
        sequence_allocator: InMemorySequenceAllocator,
        tool_call_id: str,
        status: ToolExecutionStatus,
    ) -> None:
        if result.tool_result is None:
            return
        if result.tool_result.success:
            self._publish_tool_finished(
                tool_call=tool_call,
                context=context,
                sequence_allocator=sequence_allocator,
                tool_call_id=tool_call_id,
                success=True,
                status=status,
            )
            return

        self._publish_tool_failed(
            tool_call=tool_call,
            context=context,
            sequence_allocator=sequence_allocator,
            tool_call_id=tool_call_id,
            error_code=result.tool_result.error_code,
            error_message=result.tool_result.error_message or "工具执行失败",
            status=status,
            reason=result.reason,
        )

    def _publish_tool_finished(
        self,
        *,
        tool_call: ToolCall,
        context: ToolExecutionContext,
        sequence_allocator: InMemorySequenceAllocator,
        tool_call_id: str,
        success: bool,
        status: ToolExecutionStatus,
    ) -> None:
        if context.event_bus is None or context.task_id is None:
            return
        self._publish_event(
            ToolCallFinished(
                task_id=context.task_id,
                session_id=context.session_id,
                sequence_id=sequence_allocator.next(context.task_id),
                message=f"工具调用结束: {tool_call.name}",
                tool_call_id=tool_call_id,
                tool_name=tool_call.name,
                success=success,
                payload={
                    "status": status.value,
                    "error_code": None,
                },
            ),
            event_bus=context.event_bus,
        )

    def _publish_tool_failed(
        self,
        *,
        tool_call: ToolCall,
        context: ToolExecutionContext,
        sequence_allocator: InMemorySequenceAllocator,
        tool_call_id: str,
        error_code: ErrorCode | str | None,
        error_message: str,
        status: ToolExecutionStatus,
        reason: str | None,
    ) -> None:
        if context.event_bus is None or context.task_id is None:
            return
        self._publish_event(
            ToolCallFailed(
                task_id=context.task_id,
                session_id=context.session_id,
                sequence_id=sequence_allocator.next(context.task_id),
                message=f"工具调用失败: {tool_call.name}",
                tool_call_id=tool_call_id,
                tool_name=tool_call.name,
                error_code=self._error_code_value(error_code),
                error_message=error_message,
                payload={
                    "status": status.value,
                    "reason": reason,
                    "arguments": tool_call.arguments,
                },
            ),
            event_bus=context.event_bus,
        )

    def _error_code_value(self, error_code: ErrorCode | str | None) -> str | None:
        if error_code is None:
            return None
        if isinstance(error_code, ErrorCode):
            return error_code.value
        return error_code

    def _publish_event(
        self,
        event: BaseEvent,
        event_bus: InMemoryEventBus | None,
    ) -> None:
        if event_bus is None:
            return
        try:
            event_bus.publish(event)
        except EventBusDeliveryError:
            return
