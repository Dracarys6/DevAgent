from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentRunStatus(str, Enum):
    SUCCESS = "success"  # 模型返回 final_answer
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"  # 达到最大 LLM 调用轮数
    MAX_TOOL_CALLS_EXCEEDED = "max_tool_calls_exceeded"  # 工具调用次数超过预算
    REPEATED_TOOL_CALL = "repeated_tool_call"  # 检测到重复工具调用
    LLM_ERROR = "llm_error"  # llm_client.chat 抛异常
    TOOL_ERROR = "tool_error"  # 工具执行失败并且你选择直接终止


class AgentRunResult(BaseModel):
    success: bool
    status: AgentRunStatus
    final_answer: str = ""
    steps: int = 0
    tool_call_count: int = 0
    error_message: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
