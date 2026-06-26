from uuid import uuid4

from fastapi import APIRouter, status

from devagent.api.schemas import (
    AgentTaskCreateRequest,
    AgentTaskCreateResponse,
    TaskStatus,
)

router = APIRouter(prefix="/api/v1/agent/tasks", tags=["agent-tasks"])


@router.post(
    "",
    response_model=AgentTaskCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_task(
    _request: AgentTaskCreateRequest,
) -> AgentTaskCreateResponse:
    return AgentTaskCreateResponse(
        task_id=str(uuid4()),
        status=TaskStatus.PENDING,
    )
