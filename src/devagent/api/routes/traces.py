from fastapi import APIRouter, HTTPException

from devagent.task import TaskNotFoundError
from devagent.trace import TraceService

from .tasks import event_bus, task_repository

router = APIRouter(prefix="/api/v1/agent/tasks", tags=["agent-traces"])

trace_service = TraceService(event_bus=event_bus)


@router.get("/{task_id}/trace", status_code=200)
def get_agent_task_trace(task_id: str):
    try:
        task_repository.get(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return trace_service.get_trace(task_id)
