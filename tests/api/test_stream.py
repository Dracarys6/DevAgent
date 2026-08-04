import json

from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes import stream as stream_module
from devagent.api.routes.stream import format_sse_event, iter_existing_sse_events
from devagent.api.routes.tasks import task_manager
from devagent.event import (
    AgentStarted,
    BaseEvent,
    EventSubscription,
    EventType,
    InMemoryEventBus,
)

client = TestClient(app)


def test_format_sse_event_includes_id_event_and_json_data():
    event = BaseEvent(
        sequence_id=1,
        event_type=EventType.AGENT_STARTED,
        task_id="test_task",
        message="Test event message",
        payload={"key": "value"},
    )
    sse_event = format_sse_event(event)
    assert sse_event.startswith("id: 1\n")
    assert "event: agent_started\n" in sse_event
    assert "data: " in sse_event
    assert sse_event.endswith("\n\n")


def test_format_sse_event_data_is_valid_json():
    event = BaseEvent(
        sequence_id=1,
        event_type=EventType.AGENT_STARTED,
        task_id="test_task",
        message="Test event message",
        payload={"key": "value"},
    )

    sse_event = format_sse_event(event)
    data_line = next(
        line for line in sse_event.splitlines() if line.startswith("data: ")
    )
    payload = json.loads(data_line.removeprefix("data: "))

    assert payload["task_id"] == "test_task"
    assert payload["event_type"] == "agent_started"
    assert payload["payload"] == {"key": "value"}


def test_iter_existing_sse_events_yields_formatted_events(monkeypatch):
    task_id = "test_task"
    event1 = AgentStarted(
        sequence_id=1,
        task_id=task_id,
        message="Event 1",
        payload={},
    )
    event2 = AgentStarted(
        sequence_id=2,
        task_id=task_id,
        message="Event 2",
        payload={},
    )
    event_bus = InMemoryEventBus()
    monkeypatch.setattr(stream_module, "event_bus", event_bus)
    # Simulate adding events to the event bus
    event_bus.publish(event1)
    event_bus.publish(event2)

    # after_sequence_id=None -> 返回 2 个
    iterator = iter_existing_sse_events(task_id, after_sequence_id=None)
    events = list(iterator)
    assert len(events) == 2
    # after_sequence_id=1 -> 返回 sequence_id > 1 的事件
    iterator = iter_existing_sse_events(task_id, after_sequence_id=1)
    events = list(iterator)
    assert len(events) == 1
    assert "id: 2\n" in events[0]
    # after_sequence_id=2 -> 返回空列表
    iterator = iter_existing_sse_events(task_id, after_sequence_id=2)
    events = list(iterator)
    assert len(events) == 0


def test_stream_existing_events_filters_afer_sequence_id(monkeypatch):
    bus = InMemoryEventBus()
    monkeypatch.setattr(stream_module, "event_bus", bus)
    bus.publish(AgentStarted(task_id="task_1", sequence_id=1, message="start"))
    bus.publish(AgentStarted(task_id="task_1", sequence_id=2, message="start again"))
    chunks = list(stream_module.iter_existing_sse_events("task_1", after_sequence_id=1))
    assert len(chunks) == 1
    assert chunks[0].startswith("id: 2\n")


def test_stream_task_events_returns_404_for_missing_task():
    response = client.get("/api/v1/agent/tasks/not-found/stream")

    assert response.status_code == 404


def test_stream_route_uses_text_event_stream_content_type():
    task = task_manager.create_task(question="请分析流式接口")

    response = stream_module.stream_agent_task_events(task.task_id)

    assert response.media_type == "text/event-stream"


def test_stream_router_is_registered_in_openapi():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/agent/tasks/{task_id}/stream" in response.json()["paths"]


def test_stream_route_rejects_negative_after_sequence_id():
    task = task_manager.create_task(question="请分析流式接口参数")

    response = client.get(
        f"/api/v1/agent/tasks/{task.task_id}/stream?after_sequence_id=-1"
    )

    assert response.status_code == 422


def test_stream_task_events_unsubscribes_when_generator_closes(monkeypatch):
    class FakeEventBus:
        def __init__(self) -> None:
            self.unsubscribed: list[str] = []

        def list_events(self, task_id, after_sequence_id=None):
            return []

        def subscribe(self, task_id, handler):
            handler(
                AgentStarted(
                    task_id=task_id,
                    sequence_id=1,
                    message="start",
                )
            )
            return EventSubscription(
                subscription_id="subscription_1",
                task_id=task_id,
            )

        def unsubscribe(self, subscription_id):
            self.unsubscribed.append(subscription_id)
            return True

    fake_bus = FakeEventBus()
    monkeypatch.setattr(stream_module, "event_bus", fake_bus)
    generator = stream_module.stream_task_events("task_1")

    first_chunk = next(generator)
    generator.close()

    assert first_chunk.startswith("id: 1\n")
    assert fake_bus.unsubscribed == ["subscription_1"]
