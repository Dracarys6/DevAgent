from copy import deepcopy
from typing import Any

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
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        # 保存最近一次 run 的完整 messages
        self.messages: list[dict[str, Any]] = []
        # 保存每次 run 的 messages 快照，方便多轮测试
        self.message_history: list[list[dict[str, Any]]] = []

    def run(self, user_input: str) -> str:
        """ "
        运行一次 Agent。
        返回：
            final_answer 字符串
        """
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self.system_prompt,
            },
            {"role": "user", "content": user_input},
        ]

        for _step in range(1, self.max_steps + 1):
            response: LLMResponse = self.llm_client.chat(messages)

            if response.response_type == LLMResponseType.TOOL_CALLS:
                self._append_assistant_tool_calls(messages, response)

                for tool_call in response.tool_calls:
                    tool_result = self._execute_tool_call(tool_call)
                    self._append_tool_result(messages, tool_call, tool_result)

                continue

            if response.response_type == LLMResponseType.FINAL_ANSWER:
                final_answer = response.content or ""

                messages.append({"role": "assistant", "content": final_answer})

                self._save_messages(messages)
                return final_answer

        timeout_message = f"Agent 超过最大步数限制: {self.max_steps}"

        messages.append(
            {
                "role": "assistant",
                "content": timeout_message,
            }
        )

        self._save_messages(messages)
        return timeout_message

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
