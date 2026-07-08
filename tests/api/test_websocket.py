import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from devagent.api.app import app
from devagent.api.routes.tasks import event_bus, task_manager
from devagent.api.routes.websocket import format_websocket_event
from devagent.event import AgentFinished, AgentStarted, EventType


client = TestClient(app)


def create_task(question: str = "请分析 WebSocket 接口"):
    return task_manager.create_task(question=question)


def publish_started(task_id: str, sequence_id: int, message: str = "start"):
    event = AgentStarted(
        task_id=task_id,
        sequence_id=sequence_id,
        message=message,
    )
    event_bus.publish(event)
    return event


def publish_finished(task_id: str, sequence_id: int, message: str = "done"):
    event = AgentFinished(
        task_id=task_id,
        sequence_id=sequence_id,
        message=message,
        status="success",
        final_answer="done",
    )
    event_bus.publish(event)
    return event


def connect_path(
    session_id: str,
    task_id: str | None = None,
    last_seen_sequence_id: int | None = None,
) -> str:
    query: list[str] = []
    if task_id is not None:
        query.append(f"task_id={task_id}")
    if last_seen_sequence_id is not None:
        query.append(f"last_seen_sequence_id={last_seen_sequence_id}")
    suffix = f"?{'&'.join(query)}" if query else ""
    return f"/api/v1/sessions/{session_id}/stream{suffix}"


def receive_event_message(websocket, max_messages: int = 5):
    for _ in range(max_messages):
        message = websocket.receive_json()
        if message.get("type") == "event":
            return message
    raise AssertionError("未收到业务事件消息")


def test_format_websocket_event_returns_json_payload():
    event = AgentStarted(
        task_id="task_1",
        sequence_id=1,
        message="Agent started",
        user_input="hello",
    )

    payload = format_websocket_event(event)

    assert payload["type"] == "event"
    assert payload["event"]["task_id"] == "task_1"
    assert payload["event"]["sequence_id"] == 1
    assert payload["event"]["event_type"] == EventType.AGENT_STARTED.value
    assert payload["event"]["user_input"] == "hello"


def test_websocket_connects_with_typed_connected_message():
    task = create_task()

    with client.websocket_connect(
        connect_path("session_1", task.task_id)
    ) as websocket:
        message = websocket.receive_json()

    assert message == {
        "type": "connected",
        "session_id": "session_1",
        "task_id": task.task_id,
    }


def test_websocket_replays_existing_events_after_last_seen_sequence_id():
    task = create_task()
    publish_started(task.task_id, sequence_id=1, message="event 1")
    publish_started(task.task_id, sequence_id=2, message="event 2")
    publish_finished(task.task_id, sequence_id=3, message="event 3")

    with client.websocket_connect(
        connect_path("session_reconnect", task.task_id, last_seen_sequence_id=1)
    ) as websocket:
        connected = websocket.receive_json()
        first_replayed = websocket.receive_json()
        second_replayed = websocket.receive_json()

    assert connected["type"] == "connected"
    assert first_replayed["event"]["sequence_id"] == 2
    assert second_replayed["event"]["sequence_id"] == 3


def test_websocket_receives_new_event_after_connect():
    task = create_task()

    with client.websocket_connect(
        connect_path("session_live", task.task_id)
    ) as websocket:
        connected = websocket.receive_json()
        publish_started(task.task_id, sequence_id=1, message="live event")
        event_message = receive_event_message(websocket)

    assert connected["type"] == "connected"
    assert event_message["type"] == "event"
    assert event_message["event"]["sequence_id"] == 1
    assert event_message["event"]["message"] == "live event"


def test_websocket_missing_task_closes_connection():
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            connect_path("session_missing", "missing-task")
        ):
            pass

    assert exc_info.value.code == 4404


def test_websocket_requires_task_id():
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/sessions/session_missing_task/stream"):
            pass


def test_websocket_unsubscribes_on_disconnect():
    task = create_task()
    subscriber_count_before = len(event_bus._subscribers)

    with client.websocket_connect(
        connect_path("session_cleanup", task.task_id)
    ) as websocket:
        websocket.receive_json()
        publish_started(task.task_id, sequence_id=1, message="cleanup event")
        receive_event_message(websocket)
        assert len(event_bus._subscribers) == subscriber_count_before + 1

    assert len(event_bus._subscribers) == subscriber_count_before


def test_websocket_route_does_not_break_sse_openapi():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/agent/tasks/{task_id}/stream" in response.json()["paths"]
