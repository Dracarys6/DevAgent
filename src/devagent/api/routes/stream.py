from collections.abc import Iterator
from queue import Empty, Queue

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from devagent.event import BaseEvent
from devagent.task import TaskNotFoundError

from .tasks import event_bus, repository

router = APIRouter(prefix="/api/v1/agent/tasks", tags=["agent-stream"])


def format_sse_event(event: BaseEvent) -> str:
    payload = event.model_dump_json()
    return (
        f"id: {event.sequence_id}\n"
        f"event: {event.event_type.value}\n"
        f"data: {payload}\n\n"
    )


# * 历史补发
def iter_existing_sse_events(
    task_id: str, after_sequence_id: int | None = None
) -> Iterator[str]:
    events = event_bus.list_events(task_id, after_sequence_id=after_sequence_id)
    for event in events:
        yield format_sse_event(event)


# * 实时订阅
def stream_task_events(
    task_id: str, after_sequence_id: int | None = None
) -> Iterator[str]:
    queue: Queue[BaseEvent] = Queue()

    try:
        for event in event_bus.list_events(
            task_id, after_sequence_id=after_sequence_id
        ):
            yield format_sse_event(event)
        subscription = event_bus.subscribe(task_id, queue.put)
        while True:
            try:
                event = queue.get(timeout=15)  # * 15 秒超时
            except Empty:
                yield ": keep-alive\n\n"  # 心跳
                continue
            yield format_sse_event(event)
    # finally 逻辑一定会走到，用于流式传输清理
    finally:
        if "subscription" in locals():
            event_bus.unsubscribe(subscription.subscription_id)


@router.get("/{task_id}/stream", status_code=status.HTTP_200_OK)
def stream_agent_task_events(
    task_id: str, after_sequence_id: int | None = Query(default=None, ge=0)
) -> StreamingResponse:
    try:
        repository.get(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return StreamingResponse(
        stream_task_events(task_id, after_sequence_id=after_sequence_id),
        media_type="text/event-stream",
    )
