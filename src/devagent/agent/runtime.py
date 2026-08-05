import json
from collections.abc import Generator
from copy import deepcopy
from typing import Any

from devagent.event import (
    AgentError,
    AgentFinished,
    AgentStarted,
    BaseEvent,
    EventBusDeliveryError,
    InMemoryEventBus,
    InMemorySequenceAllocator,
    LLMCallFinished,
    LLMCallStarted,
    SequenceAllocator,
)
from devagent.llm.base import LLMClient
from devagent.llm.models import LLMResponse, LLMResponseType, ToolCall
from devagent.tools.executor import (
    ToolExecutionContext,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolExecutor,
)
from devagent.tools.models import ToolResult
from devagent.tools.registry import ToolRegistry

from .context_manager import (
    ContextCompressionError,
    ContextCompressionResult,
    ContextManager,
)
from .models import (
    AgentEvent,
    AgentEventType,
    AgentRunResult,
    AgentRunStatus,
)


class AgentRuntime:
    """
    Agent 主运行时。

    职责:
    1. 维护 messages
    2. 调用 llm_client.chat
    3. 执行 tool_call
    4. 把工具结果写回 messages
    5. 返回 final answer
    6. 保存每轮完整 messages，方便测试和调试
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        system_prompt: str = "你是一个可以调用工具的代码助手",
        max_steps: int = 10,
        max_tool_calls: int = 20,
        stop_on_repeated_tool_call: bool = True,
        event_bus: InMemoryEventBus | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        context_manager: ContextManager | None = None,
        tool_executor: ToolExecutor | None = None,
        sequence_allocator: SequenceAllocator | None = None,
        workspace: str | None = None,
    ) -> None:
        if tool_executor is not None and tool_executor.registry is not tool_registry:
            raise ValueError("ToolExecutor 必须使用 AgentRuntime 的 ToolRegistry")
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor or ToolExecutor(registry=tool_registry)
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.stop_on_repeated_tool_call = stop_on_repeated_tool_call
        # * 最近一次 run 的完整消息，用于调试与检查。
        self.messages: list[dict[str, Any]] = []
        # * 每次 run 的消息快照，用于多轮测试。
        self.message_history: list[list[dict[str, Any]]] = []
        self.event_bus = event_bus
        self.task_id = task_id or "runtime"
        self.session_id = session_id
        self.sequence_allocator = sequence_allocator or InMemorySequenceAllocator()
        self.workspace = workspace
        self.context_manager = context_manager
        # * 保留每轮模型实际上下文的压缩指标，不覆盖完整消息历史。
        self.context_history: list[ContextCompressionResult] = []
        self._workflow: Generator[AgentRunResult, str, AgentRunResult] | None = None
        self._reported_event_count = 0
        self.pending_permission_request_id: str | None = None

    def run(self, user_input: str) -> AgentRunResult:
        """开始一次新的 Agent 工作流，必要时暂停等待权限审批。"""
        if self._workflow is not None:
            raise RuntimeError("AgentRuntime 已有等待恢复的工作流")
        self._reported_event_count = 0
        self.pending_permission_request_id = None
        self._workflow = self._run_workflow(user_input)
        return self._advance_workflow()

    def resume(self, permission_request_id: str) -> AgentRunResult:
        """使用已处理的权限请求恢复当前 Agent 工作流。"""
        if self._workflow is None or self.pending_permission_request_id is None:
            raise RuntimeError("AgentRuntime 没有等待权限审批的工作流")
        if permission_request_id != self.pending_permission_request_id:
            raise ValueError("权限请求与当前待恢复工具调用不匹配")
        return self._advance_workflow(permission_request_id)

    def _advance_workflow(
        self,
        permission_request_id: str | None = None,
    ) -> AgentRunResult:
        if self._workflow is None:
            raise RuntimeError("AgentRuntime 工作流不存在")
        try:
            if permission_request_id is None:
                raw_result = next(self._workflow)
            else:
                raw_result = self._workflow.send(permission_request_id)
        except StopIteration as completed:
            raw_result = completed.value
            self._workflow = None
        except Exception:
            self._workflow = None
            self.pending_permission_request_id = None
            raise

        # * EventStore 只追加本次 run/resume 新产生的兼容事件，避免恢复时重复落库。
        new_events = raw_result.events[self._reported_event_count :]
        self._reported_event_count = len(raw_result.events)
        result = raw_result.model_copy(update={"events": deepcopy(new_events)})
        self.pending_permission_request_id = (
            result.permission_request_id
            if result.status == AgentRunStatus.WAITING_PERMISSION
            else None
        )
        return result

    def _run_workflow(
        self,
        user_input: str,
    ) -> Generator[AgentRunResult, str, AgentRunResult]:
        """
        运行一次 Agent。
        返回：
            AgentRunResult 结构化结果。
        """
        events: list[AgentEvent] = []
        self._add_event(
            events,
            AgentEventType.RUN_START,
            "Agent 运行开始",
            metadata={"user_input": user_input},
        )
        self._publish_runtime_event(
            AgentStarted(
                task_id=self.task_id,
                session_id=self.session_id,
                message="Agent 运行开始",
                sequence_id=self._next_sequence_id(),
                user_input=user_input,
            )
        )

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self.system_prompt,
            },
            {"role": "user", "content": user_input},
        ]

        tool_call_count = 0
        last_tool_signature: tuple[str, str] | None = None

        for step in range(1, self.max_steps + 1):
            try:
                request_messages = self._prepare_request_messages(messages)
                self._add_event(
                    events,
                    AgentEventType.LLM_START,
                    "开始调用 LLM",
                    step=step,
                    metadata={"message_count": len(request_messages)},
                )
                self._publish_runtime_event(
                    LLMCallStarted(
                        task_id=self.task_id,
                        session_id=self.session_id,
                        sequence_id=self._next_sequence_id(),
                        message="LLM 调用开始",
                        step=step,
                        message_count=len(request_messages),
                    )
                )
                response: LLMResponse = self.llm_client.chat(request_messages)
            # ! Provider 与上下文构造错误必须在运行时边界转换成稳定的 Agent 状态。
            except Exception as exc:  # noqa: BLE001
                error_prefix = (
                    "构造 LLM 上下文失败"
                    if isinstance(exc, ContextCompressionError)
                    else "LLM 调用失败"
                )
                error_message = f"{error_prefix}: {exc}"
                self._publish_runtime_event(
                    AgentError(
                        task_id=self.task_id,
                        session_id=self.session_id,
                        sequence_id=self._next_sequence_id(),
                        message=error_prefix,
                        error_message=error_message,
                        payload={"status": AgentRunStatus.LLM_ERROR.value},
                    )
                )
                self._publish_runtime_event(
                    AgentFinished(
                        task_id=self.task_id,
                        session_id=self.session_id,
                        sequence_id=self._next_sequence_id(),
                        message="Agent 运行失败结束",
                        status=AgentRunStatus.LLM_ERROR.value,
                        final_answer="",
                    )
                )
                return self._finish_with_error(
                    messages=messages,
                    events=events,
                    status=AgentRunStatus.LLM_ERROR,
                    steps=step,
                    tool_call_count=tool_call_count,
                    error_message=error_message,
                )

            self._add_event(
                events,
                AgentEventType.LLM_END,
                "LLM 返回响应",
                step=step,
                metadata={
                    "response_type": response.response_type.value,
                    "tool_call_count": len(response.tool_calls),
                },
            )
            self._publish_runtime_event(
                LLMCallFinished(
                    task_id=self.task_id,
                    session_id=self.session_id,
                    sequence_id=self._next_sequence_id(),
                    message="LLM 调用结束",
                    step=step,
                    response_type=response.response_type.value,
                    tool_call_count=len(response.tool_calls),
                )
            )

            if response.response_type == LLMResponseType.TOOL_CALLS:
                self._append_assistant_tool_calls(messages, response)

                for tool_call in response.tool_calls:
                    if tool_call_count >= self.max_tool_calls:
                        self._publish_runtime_event(
                            AgentError(
                                task_id=self.task_id,
                                session_id=self.session_id,
                                sequence_id=self._next_sequence_id(),
                                message=f"Agent 超过最大工具调用次数限制: {self.max_tool_calls}",
                                error_message=(
                                    f"Agent 超过最大工具调用次数限制: {self.max_tool_calls}"
                                ),
                                payload={
                                    "status": AgentRunStatus.MAX_TOOL_CALLS_EXCEEDED.value
                                },
                            )
                        )

                        self._publish_runtime_event(
                            AgentFinished(
                                task_id=self.task_id,
                                session_id=self.session_id,
                                sequence_id=self._next_sequence_id(),
                                message="Agent 运行失败结束",
                                status=AgentRunStatus.MAX_TOOL_CALLS_EXCEEDED.value,
                                final_answer="",
                            )
                        )

                        return self._finish_with_error(
                            messages=messages,
                            events=events,
                            status=AgentRunStatus.MAX_TOOL_CALLS_EXCEEDED,
                            steps=step,
                            tool_call_count=tool_call_count,
                            error_message=(
                                f"Agent 超过最大工具调用次数限制: {self.max_tool_calls}"
                            ),
                        )
                    signature = self._tool_signature(tool_call)
                    if (
                        self.stop_on_repeated_tool_call
                        and signature == last_tool_signature
                    ):
                        self._publish_runtime_event(
                            AgentError(
                                task_id=self.task_id,
                                session_id=self.session_id,
                                sequence_id=self._next_sequence_id(),
                                message=f"检测到重复工具调用: {tool_call.name}",
                                error_message=f"检测到重复工具调用: {tool_call.name}",
                                payload={
                                    "status": AgentRunStatus.REPEATED_TOOL_CALL.value
                                },
                            )
                        )

                        self._publish_runtime_event(
                            AgentFinished(
                                task_id=self.task_id,
                                session_id=self.session_id,
                                sequence_id=self._next_sequence_id(),
                                message="Agent 运行失败结束",
                                status=AgentRunStatus.REPEATED_TOOL_CALL.value,
                                final_answer="",
                            )
                        )

                        return self._finish_with_error(
                            messages=messages,
                            events=events,
                            status=AgentRunStatus.REPEATED_TOOL_CALL,
                            steps=step,
                            tool_call_count=tool_call_count,
                            error_message=f"检测到重复工具调用: {tool_call.name}",
                        )

                    last_tool_signature = signature

                    self._add_event(
                        events,
                        AgentEventType.TOOL_START,
                        f"开始执行工具: {tool_call.name}",
                        step=step,
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        metadata={
                            "arguments": tool_call.arguments,
                        },
                    )

                    execution_result = self._execute_tool_call(tool_call)
                    if (
                        execution_result.status
                        == ToolExecutionStatus.WAITING_PERMISSION
                    ):
                        permission_request = execution_result.permission_request
                        if permission_request is None:
                            raise RuntimeError("ToolExecutor 未返回权限请求")
                        self._save_messages(messages)
                        resolved_request_id = yield AgentRunResult(
                            success=False,
                            status=AgentRunStatus.WAITING_PERMISSION,
                            final_answer="",
                            steps=step,
                            tool_call_count=tool_call_count,
                            error_message=None,
                            permission_request_id=permission_request.request_id,
                            messages=deepcopy(messages),
                            events=deepcopy(events),
                        )
                        execution_result = self._resume_tool_call(
                            resolved_request_id,
                            tool_call,
                        )

                    tool_result = execution_result.tool_result
                    if tool_result is None:
                        raise RuntimeError("ToolExecutor 未返回 ToolResult")
                    self._append_tool_result(messages, tool_call, tool_result)
                    tool_call_count += 1
                    self._add_event(
                        events,
                        AgentEventType.TOOL_END,
                        f"工具执行结束: {tool_call.name}",
                        step=step,
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        metadata={
                            "success": tool_result.success,
                            "error_code": tool_result.error_code,
                            "execution_status": execution_result.status.value,
                        },
                    )

            elif response.response_type == LLMResponseType.FINAL_ANSWER:
                final_answer = response.content or ""

                messages.append({"role": "assistant", "content": final_answer})

                self._add_event(
                    events,
                    AgentEventType.RUN_END,
                    "Agent 运行成功结束",
                    step=step,
                    metadata={
                        "status": AgentRunStatus.SUCCESS.value,
                        "tool_call_count": tool_call_count,
                    },
                )

                self._publish_runtime_event(
                    AgentFinished(
                        task_id=self.task_id,
                        session_id=self.session_id,
                        sequence_id=self._next_sequence_id(),
                        message="Agent 运行成功结束",
                        status=AgentRunStatus.SUCCESS.value,
                        final_answer=final_answer,
                        payload={
                            "status": AgentRunStatus.SUCCESS.value,
                            "tool_call_count": tool_call_count,
                        },
                    )
                )

                self._save_messages(messages)
                return AgentRunResult(
                    success=True,
                    status=AgentRunStatus.SUCCESS,
                    final_answer=final_answer,
                    steps=step,
                    tool_call_count=tool_call_count,
                    error_message=None,
                    messages=deepcopy(messages),
                    events=deepcopy(events),
                )

        self._publish_runtime_event(
            AgentError(
                task_id=self.task_id,
                session_id=self.session_id,
                sequence_id=self._next_sequence_id(),
                message=f"Agent 超过最大步数限制: {self.max_steps}",
                error_message=f"Agent 超过最大步数限制: {self.max_steps}",
                payload={
                    "status": AgentRunStatus.MAX_STEPS_EXCEEDED.value,
                    "tool_call_count": tool_call_count,
                },
            )
        )

        self._publish_runtime_event(
            AgentFinished(
                task_id=self.task_id,
                session_id=self.session_id,
                sequence_id=self._next_sequence_id(),
                message="Agent 运行失败结束",
                status=AgentRunStatus.MAX_STEPS_EXCEEDED.value,
                final_answer="",
            )
        )

        return self._finish_with_error(
            messages=messages,
            events=events,
            status=AgentRunStatus.MAX_STEPS_EXCEEDED,
            steps=self.max_steps,
            tool_call_count=tool_call_count,
            error_message=f"Agent 超过最大步数限制: {self.max_steps}",
        )

    def _tool_signature(self, tool_call: ToolCall) -> tuple[str, str]:
        return (
            tool_call.name,
            json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False),
        )

    def _append_assistant_tool_calls(
        self, messages: list[dict[str, Any]], response: LLMResponse
    ) -> None:
        """
        把 assistant 的 tool_calls 加入 messages。
        """
        messages.append(
            {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                    }
                    for tool_call in response.tool_calls
                ],
                "metadata": response.metadata,
            }
        )

    def _execute_tool_call(self, tool_call: ToolCall) -> ToolExecutionResult:
        """
        执行单个工具调用。
        """
        return self.tool_executor.execute(
            tool_call,
            self._tool_execution_context(tool_call),
        )

    def _resume_tool_call(
        self,
        permission_request_id: str,
        tool_call: ToolCall,
    ) -> ToolExecutionResult:
        return self.tool_executor.resume(
            permission_request_id,
            self._tool_execution_context(tool_call),
        )

    def _tool_execution_context(self, tool_call: ToolCall) -> ToolExecutionContext:
        return ToolExecutionContext(
            task_id=self.task_id,
            session_id=self.session_id,
            tool_call_id=tool_call.id,
            workspace=self.workspace,
            event_bus=self.event_bus,
            sequence_allocator=self.sequence_allocator,
        )

    def _append_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call: ToolCall,
        tool_result: ToolResult,
    ) -> None:
        """
        把工具执行结果加入 messages
        """
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": tool_result.model_dump_json(),
            }
        )

    def _save_messages(self, messages: list[dict[str, Any]]) -> None:
        """
        保存 messages，便于测试和调试。
        """
        snapshot = deepcopy(messages)
        self.messages = snapshot
        self.message_history.append(deepcopy(snapshot))

    def _prepare_request_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.context_manager is None:
            return messages
        result = self.context_manager.compress(messages)
        self.context_history.append(result.model_copy(deep=True))
        return result.messages

    def _finish_with_error(
        self,
        messages: list[dict[str, Any]],
        events: list[AgentEvent],
        status: AgentRunStatus,
        steps: int,
        tool_call_count: int,
        error_message: str,
    ) -> AgentRunResult:

        self._add_event(
            events,
            AgentEventType.ERROR,
            error_message,
            step=steps,
            metadata={"status": status.value},
        )
        self._add_event(
            events,
            AgentEventType.RUN_END,
            "Agent 运行失败结束",
            step=steps,
            metadata={"status": status.value, "tool_call_count": tool_call_count},
        )

        messages.append({"role": "assistant", "content": error_message})
        self._save_messages(messages)
        return AgentRunResult(
            success=False,
            status=status,
            final_answer="",
            steps=steps,
            tool_call_count=tool_call_count,
            error_message=error_message,
            messages=deepcopy(messages),
            events=deepcopy(events),
        )

    def _add_event(
        self,
        events: list[AgentEvent],
        event_type: AgentEventType,
        message: str,
        step: int = 0,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        events.append(
            AgentEvent(
                type=event_type,
                message=message,
                step=step,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                metadata=metadata or {},
            )
        )

    def _publish_runtime_event(self, event: BaseEvent) -> None:
        """
        发布运行时事件到事件总线。
        """
        if self.event_bus is None:
            return
        try:
            self.event_bus.publish(event)
        except EventBusDeliveryError:
            return

    def _next_sequence_id(self) -> int:
        """
        获取下一个 sequence_id。
        """
        return self.sequence_allocator.next(self.task_id)
