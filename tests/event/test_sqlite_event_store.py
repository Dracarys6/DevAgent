import json
from pathlib import Path

import pytest

from devagent.event import (
    AgentStarted,
    EventPersistenceError,
    SQLiteEventStore,
    ToolCallStarted,
)
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import AgentTask, SQLiteTaskRepository


def make_store(tmp_path: Path) -> tuple[SQLiteDatabase, SQLiteEventStore]:
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "events.db"))
    database.initialize()
    SQLiteTaskRepository(database).create(
        AgentTask(task_id="task-1", question="sqlite events")
    )
    return database, SQLiteEventStore(database)


def test_sqlite_event_store_survives_new_database_instance(tmp_path: Path) -> None:
    database, store = make_store(tmp_path)
    event = AgentStarted(
        task_id="task-1",
        sequence_id=1,
        message="started",
        user_input="hello",
    )
    store.append(event)

    reopened_database = SQLiteDatabase(SQLiteSettings(path=database.settings.path))
    reopened_database.initialize()
    restored = SQLiteEventStore(reopened_database).list("task-1")

    assert restored == [event]
    assert isinstance(restored[0], AgentStarted)


def test_sqlite_event_store_rejects_event_for_missing_task(tmp_path: Path) -> None:
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "events.db"))
    database.initialize()

    with pytest.raises(EventPersistenceError, match="保存事件失败"):
        SQLiteEventStore(database).append(
            AgentStarted(task_id="missing", sequence_id=1, message="started")
        )


def test_sqlite_event_store_rejects_unknown_event_model(tmp_path: Path) -> None:
    database, store = make_store(tmp_path)
    store.append(AgentStarted(task_id="task-1", sequence_id=1, message="started"))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE agent_events SET event_model = 'UnknownEvent' WHERE task_id = ?",
            ("task-1",),
        )

    with pytest.raises(EventPersistenceError, match="未知事件模型"):
        store.list("task-1")


def test_sqlite_event_store_rejects_invalid_event_json(tmp_path: Path) -> None:
    database, store = make_store(tmp_path)
    store.append(AgentStarted(task_id="task-1", sequence_id=1, message="started"))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE agent_events SET event_json = '{broken' WHERE task_id = ?",
            ("task-1",),
        )

    with pytest.raises(EventPersistenceError, match="事件数据无效"):
        store.list("task-1")


def test_sqlite_event_store_persists_redacted_tool_arguments(tmp_path: Path) -> None:
    database, store = make_store(tmp_path)
    store.append(
        ToolCallStarted(
            task_id="task-1",
            sequence_id=1,
            message="tool",
            tool_call_id="call-1",
            tool_name="request",
            arguments={"authorization": "Bearer secret", "path": "README.md"},
        )
    )

    connection = database.connect()
    try:
        event_json = connection.execute(
            "SELECT event_json FROM agent_events WHERE task_id = ?",
            ("task-1",),
        ).fetchone()["event_json"]
    finally:
        connection.close()

    arguments = json.loads(event_json)["arguments"]
    assert arguments == {"authorization": "[REDACTED]", "path": "README.md"}
    assert "Bearer secret" not in event_json
