import json
from copy import deepcopy
from typing import Any

from .models import (
    AgentRunResult,
    AgentRunStatus,
    AgentEvent,
    AgentEventType,
)
from devagent.llm.base import LLMClient
from devagent.llm.models import LLMResponse, LLMResponseType, ToolCall
from devagent.tools.models import ToolResult
from devagent.tools.registry import ToolRegistry


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
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.stop_on_repeated_tool_call = stop_on_repeated_tool_call
        # 保存最近一次 run 的完整 messages
        self.messages: list[dict[str, Any]] = []
        # 保存每次 run 的 messages 快照，方便多轮测试
        self.message_history: list[list[dict[str, Any]]] = []

    def run(self, user_input: str) -> AgentRunResult:
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
                self._add_event(
                    events,
                    AgentEventType.LLM_START,
                    "开始调用 LLM",
                    step=step,
                    metadata={"message_count": len(messages)},
                )
                response: LLMResponse = self.llm_client.chat(messages)
            except Exception as exc:
                return self._finish_with_error(
                    messages=messages,
                    events=events,
                    status=AgentRunStatus.LLM_ERROR,
                    steps=step,
                    tool_call_count=tool_call_count,
                    error_message=f"LLM 调用失败: {exc}",
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

            if response.response_type == LLMResponseType.TOOL_CALLS:
                self._append_assistant_tool_calls(messages, response)

                for tool_call in response.tool_calls:
                    if tool_call_count >= self.max_tool_calls:
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

                    tool_result = self._execute_tool_call(tool_call)
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

    def _execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        """
        执行单个工具调用。
        """
        return self.tool_registry.execute(tool_call.name, tool_call.arguments)

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
