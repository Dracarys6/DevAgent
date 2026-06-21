from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class LLMResponseType(str, Enum):
    TOOL_CALLS = "tool_calls"
    FINAL_ANSWER = "final_answer"


class ToolCall(BaseModel):
    id: str = Field(
        min_length=1,
        description="工具调用 ID，用于和 tool result 通过 tool_call_id 对应。",
    )
    name: str = Field(min_length=1, description="工具名称。")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="工具调用参数。"
    )


class LLMResponse(BaseModel):
    response_type: LLMResponseType
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_response_shape(self) -> "LLMResponse":
        if self.response_type == LLMResponseType.TOOL_CALLS and not self.tool_calls:
            raise ValueError("tool_calls 类型响应必须至少包含一个工具调用")
        if self.response_type == LLMResponseType.FINAL_ANSWER:
            if self.content is None:
                raise ValueError("final_answer 类型响应必须包含 content")
            if self.tool_calls:
                raise ValueError("final_answer 类型响应不能包含工具调用")
        return self

    @classmethod
    def tool_calls_response(
        cls,
        tool_calls: list[ToolCall],
        metadata: dict[str, Any] | None = None,
    ) -> "LLMResponse":
        return cls(
            response_type=LLMResponseType.TOOL_CALLS,
            content=None,
            tool_calls=tool_calls,
            metadata=metadata or {},
        )

    @classmethod
    def final_answer(
        cls, content: str, metadata: dict[str, Any] | None = None
    ) -> "LLMResponse":
        return cls(
            response_type=LLMResponseType.FINAL_ANSWER,
            content=content,
            tool_calls=[],
            metadata=metadata or {},
        )
