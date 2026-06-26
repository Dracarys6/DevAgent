from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_PERMISSION,
        TaskStatus.FAILED,
        TaskStatus.DONE,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_PERMISSION: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.DONE: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


class InvalidTaskTransitionError(ValueError):
    pass


class AgentTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    workspace: str = "."
    provider: str = "mock"
    model: str | None = None
    base_url: str | None = None
    max_steps: int = 10
    max_tool_calls: int = 20
    status: TaskStatus = TaskStatus.PENDING
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def transition_to(
        self,
        new_status: TaskStatus,
        error_message: str | None = None,
    ) -> None:
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTaskTransitionError(
                f"非法任务状态转移: {self.status.value} -> {new_status.value}"
            )
        self.status = new_status
        self.error_message = error_message
        self.updated_at = datetime.now(timezone.utc)
