from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from devagent.agent import AgentEventType
from devagent.task.models import TaskStatus
from devagent.permission import PermissionDecision, PermissionStatus
from devagent.tools.models import RiskLevel


class LLMProvider(str, Enum):
    MOCK = "mock"
    REAL = "real"


class AgentTaskCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "question": "请分析项目结构",
                    "workspace": ".",
                    "provider": "mock",
                    "model": None,
                    "base_url": None,
                    "max_steps": 10,
                    "max_tool_calls": 20,
                }
            ]
        }
    )

    question: str = Field(min_length=1, description="用户问题")
    workspace: str = Field(default=".", description="工作区路径")
    provider: LLMProvider = Field(default=LLMProvider.MOCK)
    model: str | None = None
    base_url: str | None = None
    max_steps: int = Field(default=10, ge=1, le=50)
    max_tool_calls: int = Field(default=20, ge=1, le=100)


class AgentTaskCreateResponse(BaseModel):
    task_id: str
    status: TaskStatus


class AgentTaskResponse(BaseModel):
    task_id: str
    question: str
    workspace: str
    provider: str
    model: str | None
    base_url: str | None
    max_steps: int
    max_tool_calls: int
    status: TaskStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class AgentTaskListResponse(BaseModel):
    tasks: list[AgentTaskResponse]


class AgentEventResponse(BaseModel):
    type: AgentEventType
    message: str
    step: int
    tool_call_id: str | None
    tool_name: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class AgentTaskEventsResponse(BaseModel):
    task_id: str
    events: list[AgentEventResponse] = Field(default_factory=list)


class PermissionRequestResponse(BaseModel):
    request_id: str
    task_id: str | None
    tool_call_id: str | None
    tool_name: str
    tool_arguments: dict[str, Any]
    risk_level: RiskLevel
    reason: str
    status: PermissionStatus
    decision: PermissionDecision | None
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class PermissionRequestListResponse(BaseModel):
    requests: list[PermissionRequestResponse]


class PermissionResolveRequest(BaseModel):
    decision: PermissionDecision
    decision_reason: str | None = None


class PermissionResolveResponse(BaseModel):
    request: PermissionRequestResponse


class CIDiagnosisRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "commit_id": "abc123",
                    "workspace": "examples/sample_repo",
                }
            ]
        }
    )

    commit_id: str = Field(
        min_length=6,
        max_length=64,
        pattern=r"^[0-9a-fA-F]+$",
    )
    workspace: str = Field(default=".", min_length=1)


class CodeReviewRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "base_ref": "main",
                    "head_ref": "feature/payment",
                    "workspace": "examples/sample_repo",
                }
            ]
        },
    )
    base_ref: str = Field(min_length=1, max_length=255)
    head_ref: str = Field(min_length=1, max_length=255)
    workspace: str = Field(default=".", min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_refs(self) -> "CodeReviewRequest":
        if (
            self.base_ref != self.base_ref.strip()
            or self.head_ref != self.head_ref.strip()
        ):
            raise ValueError("base_ref 和 head_ref 不能包含首尾空白")
        if self.base_ref == self.head_ref:
            raise ValueError("base_ref 和 head_ref 不能相同")
        return self
