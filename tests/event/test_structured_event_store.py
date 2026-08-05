from pathlib import Path

import pytest

from devagent.event import (
    AgentError,
    AgentFinished,
    AgentStarted,
    BaseEvent,
    EventAlreadyExistsError,
    EventStore,
    InMemoryStructuredEventStore,
    LLMCallFinished,
    LLMCallStarted,
    PermissionRequested,
    PermissionResolved,
    SQLiteEventStore,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
)
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import AgentTask, SQLiteTaskRepository


@pytest.fixture(params=("memory", "sqlite"))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> EventStore:
    if request.param == "memory":
        return InMemoryStructuredEventStore()
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "events.db"))
    database.initialize()
    SQLiteTaskRepository(database).create(
        AgentTask(task_id="task-1", question="event contract")
    )
    SQLiteTaskRepository(database).create(
        AgentTask(task_id="task-2", question="event contract 2")
    )
    return SQLiteEventStore(database)


def make_events() -> list[BaseEvent]:
    common = {"task_id": "task-1", "message": "event"}
    return [
        AgentStarted(sequence_id=1, user_input="hello", **common),
        LLMCallStarted(sequence_id=2, step=1, message_count=2, **common),
        LLMCallFinished(
            sequence_id=3,
            step=1,
            response_type="tool_calls",
            tool_call_count=1,
            **common,
        ),
        ToolCallStarted(
            sequence_id=4,
            tool_call_id="call-1",
            tool_name="read_file",
            arguments={"path": "README.md"},
            **common,
        ),
        ToolCallFinished(
            sequence_id=5,
            tool_call_id="call-1",
            tool_name="read_file",
            success=True,
            duration_ms=12.5,
            **common,
        ),
        ToolCallFailed(
            sequence_id=6,
            tool_call_id="call-2",
            tool_name="run_shell",
            error_code="permission_denied",
            error_message="denied",
            **common,
        ),
        PermissionRequested(
            sequence_id=7,
            request_id="request-1",
            tool_name="run_shell",
            risk_level="HIGH",
            **common,
        ),
        PermissionResolved(
            sequence_id=8,
            request_id="request-1",
            decision="ALLOW",
            status="APPROVED",
            **common,
        ),
        AgentError(sequence_id=9, error_message="failed", **common),
        AgentFinished(
            sequence_id=10,
            status="success",
            final_answer="done",
            **common,
        ),
    ]


def test_event_store_round_trips_concrete_event_models(store: EventStore) -> None:
    events = make_events()
    for event in reversed(events):
        store.append(event)

    restored = store.list("task-1")

    assert restored == events
    assert [type(event) for event in restored] == [type(event) for event in events]


def test_event_store_filters_after_sequence_id(store: EventStore) -> None:
    for event in make_events()[:3]:
        store.append(event)

    assert [
        event.sequence_id for event in store.list("task-1", after_sequence_id=1)
    ] == [
        2,
        3,
    ]


def test_event_store_rejects_duplicate_event_id(store: EventStore) -> None:
    event = AgentStarted(task_id="task-1", sequence_id=1, message="first")
    store.append(event)

    with pytest.raises(EventAlreadyExistsError, match="事件已存在"):
        store.append(
            AgentStarted(
                event_id=event.event_id,
                task_id="task-2",
                sequence_id=1,
                message="duplicate id",
            )
        )


def test_event_store_rejects_duplicate_task_sequence(store: EventStore) -> None:
    store.append(AgentStarted(task_id="task-1", sequence_id=1, message="first"))

    with pytest.raises(EventAlreadyExistsError, match="事件已存在"):
        store.append(AgentStarted(task_id="task-1", sequence_id=1, message="duplicate"))


def test_event_store_allows_same_sequence_for_different_tasks(
    store: EventStore,
) -> None:
    store.append(AgentStarted(task_id="task-1", sequence_id=1, message="first"))
    store.append(AgentStarted(task_id="task-2", sequence_id=1, message="second"))

    assert store.list("task-1")[0].message == "first"
    assert store.list("task-2")[0].message == "second"


def test_event_store_returns_detached_events(store: EventStore) -> None:
    event = AgentStarted(task_id="task-1", sequence_id=1, message="stored")
    store.append(event)
    event.message = "changed outside"

    restored = store.list("task-1")
    restored[0].message = "changed result"

    assert store.list("task-1")[0].message == "stored"


def test_event_store_clear_only_removes_target_task(store: EventStore) -> None:
    store.append(AgentStarted(task_id="task-1", sequence_id=1, message="first"))
    store.append(AgentStarted(task_id="task-2", sequence_id=1, message="second"))

    store.clear("task-1")

    assert store.list("task-1") == []
    assert len(store.list("task-2")) == 1
