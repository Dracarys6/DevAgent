import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from devagent.event import BaseEvent
from devagent.task import TaskNotFoundError

from .tasks import event_bus, task_repository

router = APIRouter(prefix="/api/v1/sessions", tags=["agent-websocket"])


def format_websocket_event(event: BaseEvent) -> dict:
    return {
        "type": "event",
        "event": event.model_dump(mode="json"),
    }


@router.websocket("/{session_id}/stream")
async def stream_session_events(
    websocket: WebSocket,
    session_id: str,
    task_id: str = Query(...),
    last_seen_sequence_id: int | None = Query(default=None, ge=0),
) -> None:
    try:
        task_repository.get(task_id)
    except TaskNotFoundError:
        await websocket.close(code=4404, reason="Task not found")
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "type": "connected",
            "session_id": session_id,
            "task_id": task_id,
        }
    )

    queue: asyncio.Queue[BaseEvent] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    subscription = None

    try:
        # * 先补发断线期间的历史事件。
        for event in event_bus.list_events(
            task_id, after_sequence_id=last_seen_sequence_id
        ):
            await websocket.send_json(format_websocket_event(event))

        # * 再订阅后续实时事件。
        subscription = event_bus.subscribe(
            task_id,
            lambda event: loop.call_soon_threadsafe(queue.put_nowait, event),
        )
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1)
            except TimeoutError:
                await websocket.send_json({"type": "keep_alive"})
                continue
            await websocket.send_json(format_websocket_event(event))

    except WebSocketDisconnect:
        return
    finally:
        if subscription is not None:
            event_bus.unsubscribe(subscription.subscription_id)


@router.get("/{session_id}/health")
async def get_session_health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "devagent-websocket",
    }
