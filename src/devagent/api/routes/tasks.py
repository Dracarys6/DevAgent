from fastapi import APIRouter, status

from devagent.api.schemas import (
    AgentTaskCreateRequest,
    AgentTaskCreateResponse,
)
from devagent.task.models import AgentTask
from devagent.task.repository import InMemoryTaskRepository

router = APIRouter(prefix="/api/v1/agent/tasks", tags=["agent-tasks"])

repository = InMemoryTaskRepository()


@router.post(
    "",
    response_model=AgentTaskCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_task(
    request: AgentTaskCreateRequest,
) -> AgentTaskCreateResponse:
    task = repository.create(
        AgentTask(
            question=request.question,
            workspace=request.workspace,
            provider=request.provider.value,
            model=request.model,
            base_url=request.base_url,
            max_steps=request.max_steps,
            max_tool_calls=request.max_tool_calls,
        )
    )
    return AgentTaskCreateResponse(
        task_id=task.task_id,
        status=task.status,
    )
