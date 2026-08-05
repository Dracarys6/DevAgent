from __future__ import annotations

import sqlite3

from pydantic import ValidationError

from devagent.storage import SQLiteDatabase

from .models import (
    AgentError,
    AgentFinished,
    AgentStarted,
    BaseEvent,
    LLMCallFinished,
    LLMCallStarted,
    PermissionRequested,
    PermissionResolved,
    ToolCallFailed,
    ToolCallFinished,
    ToolCallStarted,
)
from .store import EventAlreadyExistsError, EventPersistenceError

_EVENT_MODELS: dict[str, type[BaseEvent]] = {
    model.__name__: model
    for model in (
        BaseEvent,
        AgentStarted,
        AgentFinished,
        AgentError,
        LLMCallStarted,
        LLMCallFinished,
        ToolCallStarted,
        ToolCallFinished,
        ToolCallFailed,
        PermissionRequested,
        PermissionResolved,
    )
}


class SQLiteEventStore:
    """持久化结构化 BaseEvent，供 Trace 和断线重放使用。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def append(self, event: BaseEvent) -> None:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO agent_events(
                        event_id, task_id, session_id, sequence_id,
                        event_type, message, event_model, event_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.task_id,
                        event.session_id,
                        event.sequence_id,
                        event.event_type.value,
                        event.message,
                        type(event).__name__,
                        event.model_dump_json(),
                        event.timestamp.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if getattr(exc, "sqlite_errorname", "") in {
                "SQLITE_CONSTRAINT_PRIMARYKEY",
                "SQLITE_CONSTRAINT_UNIQUE",
            }:
                raise EventAlreadyExistsError(
                    f"事件已存在: {event.task_id}/{event.sequence_id}"
                ) from exc
            raise EventPersistenceError("保存事件失败") from exc
        except sqlite3.Error as exc:
            raise EventPersistenceError("保存事件失败") from exc

    def list(
        self,
        task_id: str,
        *,
        after_sequence_id: int | None = None,
    ) -> list[BaseEvent]:
        try:
            connection = self._database.connect()
            try:
                if after_sequence_id is None:
                    rows = connection.execute(
                        """
                        SELECT event_model, event_json
                        FROM agent_events
                        WHERE task_id = ?
                        ORDER BY sequence_id ASC
                        """,
                        (task_id,),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT event_model, event_json
                        FROM agent_events
                        WHERE task_id = ? AND sequence_id > ?
                        ORDER BY sequence_id ASC
                        """,
                        (task_id, after_sequence_id),
                    ).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise EventPersistenceError("读取事件失败") from exc
        return [_event_from_row(row) for row in rows]

    def clear(self, task_id: str) -> None:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "DELETE FROM agent_events WHERE task_id = ?",
                    (task_id,),
                )
        except sqlite3.Error as exc:
            raise EventPersistenceError("清理事件失败") from exc


def _event_from_row(row: sqlite3.Row) -> BaseEvent:
    model_name = str(row["event_model"])
    model = _EVENT_MODELS.get(model_name)
    if model is None:
        raise EventPersistenceError(f"未知事件模型: {model_name}")
    try:
        return model.model_validate_json(row["event_json"])
    except (ValidationError, ValueError, TypeError) as exc:
        raise EventPersistenceError("数据库中的事件数据无效") from exc
