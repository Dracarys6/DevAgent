from copy import deepcopy
from typing import Any

from .models import LLMResponse, ToolCall


def default_mock_responses() -> list[LLMResponse]:
    """返回用于最小 Agent Loop 的默认固定响应序列。"""
    return [
        LLMResponse.tool_calls_response(
            tool_calls=[
                ToolCall(
                    id="call_search_code_001",
                    name="search_code",
                    arguments={
                        "query": "ToolRegistry",
                        "workspace": ".",
                        "file_pattern": "*.py",
                    },
                )
            ],
            metadata={"description": "第 1 次模拟调用：返回 search_code tool call"},
        ),
        LLMResponse.tool_calls_response(
            tool_calls=[
                ToolCall(
                    id="call_read_file_001",
                    name="read_file",
                    arguments={
                        "file_path": "src/devagent/tools/models.py",
                        "workspace": ".",
                    },
                )
            ],
            metadata={"description": "第 2 次模拟调用：返回 read_file tool call"},
        ),
        LLMResponse.final_answer(
            content="已完成代码搜索和文件读取，这是最终回答。",
            metadata={"description": "第 3 次模拟调用：返回 final answer"},
        ),
    ]


class MockLLMClient:
    """按顺序返回预设响应，并记录每次收到的消息。"""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = default_mock_responses() if responses is None else responses
        if not self._responses:
            raise ValueError("MockLLMClient 至少需要一个响应")
        self.call_count = 0
        self.requests: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        self.requests.append(deepcopy(messages))
        self.call_count += 1

        response_index = min(self.call_count - 1, len(self._responses) - 1)
        response = self._responses[response_index].model_copy(deep=True)
        response.metadata["mock_call_index"] = self.call_count
        return response
