from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator
from datetime import datetime, timezone


class AgentEventType(str, Enum):
    RUN_START = "run_start"  # 一次 Agent 运行开始
    RUN_END = "run_end"  # 一次 Agent 运行结束
    LLM_START = "llm_start"  # 准备调用 LLM
    LLM_END = "llm_end"  # LLM 返回响应
    TOOL_START = "tool_start"  # 准备执行工具
    TOOL_END = "tool_end"  # 工具执行结束
    ERROR = "error"  # 运行过程中出现错误或被防失控逻辑终止


class AgentEvent(BaseModel):
    type: AgentEventType
    message: str
    step: int = 0
    tool_call_id: str | None = None
    tool_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRunStatus(str, Enum):
    SUCCESS = "success"  # 模型返回 final_answer
    WAITING_PERMISSION = "waiting_permission"  # 高风险工具等待用户审批
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
    permission_request_id: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_permission_checkpoint(self) -> "AgentRunResult":
        if self.status == AgentRunStatus.WAITING_PERMISSION:
            if self.success or self.permission_request_id is None:
                raise ValueError(
                    "等待权限的运行结果必须失败暂停并包含 permission_request_id"
                )
        elif self.permission_request_id is not None:
            raise ValueError("非等待权限结果不能包含 permission_request_id")
        return self
