from fastapi import APIRouter, HTTPException, status

from devagent.api.schemas import (
    AgentTaskCreateRequest,
    AgentTaskCreateResponse,
    AgentTaskListResponse,
    AgentTaskResponse,
)
from devagent.task.models import AgentTask, InvalidTaskTransitionError, TaskStatus
from devagent.task.repository import InMemoryTaskRepository, TaskNotFoundError

router = APIRouter(prefix="/api/v1/agent/tasks", tags=["agent-tasks"])

repository = InMemoryTaskRepository()


@router.get("/list", response_model=AgentTaskListResponse)
def get_agent_task_list() -> AgentTaskListResponse:
    tasks = repository.list()
    return AgentTaskListResponse(tasks=[_task_to_response(task) for task in tasks])


@router.get("/{task_id}", response_model=AgentTaskResponse)
def get_agent_task(task_id: str) -> AgentTaskResponse:
    task = _get_task_or_404(task_id)
    return _task_to_response(task)


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


@router.post("/{task_id}/cancel", response_model=AgentTaskResponse)
def cancel_agent_task(task_id: str) -> AgentTaskResponse:
    try:
        task = repository.update_status(task_id, TaskStatus.CANCELLED)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _task_to_response(task)


def _get_task_or_404(task_id: str) -> AgentTask:
    try:
        return repository.get(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _task_to_response(task: AgentTask) -> AgentTaskResponse:
    return AgentTaskResponse(**task.model_dump())
