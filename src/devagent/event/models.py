from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


REDACTED_VALUE = "[REDACTED]"
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
}


class EventType(str, Enum):
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    AGENT_ERROR = "agent_error"
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_FINISHED = "llm_call_finished"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"
    TOOL_CALL_FAILED = "tool_call_failed"
    PERMISSION_REQUESTED = "permission_requested"
    PERMISSION_RESOLVED = "permission_resolved"


class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    session_id: str | None = None
    event_type: EventType
    sequence_id: int = Field(ge=1)
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def redact_payload(self) -> "BaseEvent":
        self.payload = redact_sensitive_values(self.payload)
        return self


class AgentStarted(BaseEvent):
    event_type: EventType = EventType.AGENT_STARTED
    user_input: str | None = None


class AgentFinished(BaseEvent):
    event_type: EventType = EventType.AGENT_FINISHED
    status: str
    final_answer: str = ""


class AgentError(BaseEvent):
    event_type: EventType = EventType.AGENT_ERROR
    error_message: str


class LLMCallStarted(BaseEvent):
    event_type: EventType = EventType.LLM_CALL_STARTED
    step: int = Field(ge=1)
    message_count: int = Field(ge=0)


class LLMCallFinished(BaseEvent):
    event_type: EventType = EventType.LLM_CALL_FINISHED
    step: int = Field(ge=1)
    response_type: str
    tool_call_count: int = Field(ge=0)


class ToolCallStarted(BaseEvent):
    event_type: EventType = EventType.TOOL_CALL_STARTED
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def redact_arguments(self) -> "ToolCallStarted":
        self.arguments = redact_sensitive_values(self.arguments)
        return self


class ToolCallFinished(BaseEvent):
    event_type: EventType = EventType.TOOL_CALL_FINISHED
    tool_call_id: str
    tool_name: str
    success: bool
    duration_ms: float | None = Field(default=None, ge=0)


class ToolCallFailed(BaseEvent):
    event_type: EventType = EventType.TOOL_CALL_FAILED
    tool_call_id: str
    tool_name: str
    error_code: str | None = None
    error_message: str


class PermissionRequested(BaseEvent):
    event_type: EventType = EventType.PERMISSION_REQUESTED
    request_id: str
    tool_name: str
    risk_level: str


class PermissionResolved(BaseEvent):
    event_type: EventType = EventType.PERMISSION_RESOLVED
    request_id: str
    decision: str
    status: str


class InMemorySequenceAllocator:
    def __init__(self) -> None:
        self._next_by_task_id: dict[str, int] = {}

    def next(self, task_id: str) -> int:
        next_value = self._next_by_task_id.get(task_id, 1)
        self._next_by_task_id[task_id] = next_value + 1
        return next_value


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                REDACTED_VALUE
                if _is_sensitive_key(key)
                else redact_sensitive_values(nested_value)
            )
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    return deepcopy(value)


def _is_sensitive_key(key: Any) -> bool:
    return isinstance(key, str) and key.lower() in SENSITIVE_KEYS
