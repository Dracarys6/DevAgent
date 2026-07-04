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


class ToolExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"
    WAITING_PERMISSION = "WAITING_PERMISSION"


class ToolExecutionContext(BaseModel):
    task_id: str | None = None
    tool_call_id: str | None = None
    workspace: str | None = None


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
            return ToolExecutionResult(
                status=ToolExecutionStatus.EXECUTED,
                tool_result=tool_result,
                reason="工具不存在",
                metadata=tool_result.metadata,
            )

        if tool.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
            return self._execute_registered_tool(tool_call, reason="低风险工具直接执行")

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
                return ToolExecutionResult(
                    status=ToolExecutionStatus.BLOCKED,
                    tool_result=tool_result,
                    reason=policy.reason or "命中拒绝策略",
                    metadata=metadata,
                )

            if policy.decision == PermissionDecision.ALLOW:
                return self._execute_registered_tool(
                    tool_call,
                    reason="命中允许策略，执行高风险工具",
                    metadata={
                        "tool_name": tool.name,
                        "risk_level": tool.risk_level.value,
                        "policy_id": policy.policy_id,
                        "policy_decision": policy.decision.value,
                    },
                )

        permission_request = self.permission_manager.request_permission(
            tool_name=tool.name,
            risk_level=tool.risk_level,
            reason=f"高风险工具 {tool.name} 需要用户审批",
            tool_arguments=tool_call.arguments,
            task_id=context.task_id,
            tool_call_id=context.tool_call_id or tool_call.id,
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
