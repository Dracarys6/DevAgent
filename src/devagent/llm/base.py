from typing import Any, Protocol, runtime_checkable

from .models import LLMResponse


@runtime_checkable
class LLMClient(Protocol):
    """AgentRuntime 所依赖的统一大模型客户端协议。"""

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        """根据消息上下文返回统一 LLMResponse。"""
        ...
