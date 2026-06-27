from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from devagent.task.models import TaskStatus


class LLMProvider(str, Enum):
    MOCK = "mock"
    REAL = "real"


class AgentTaskCreateRequest(BaseModel):
    question: str = Field(min_length=1, description="用户问题。")
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
