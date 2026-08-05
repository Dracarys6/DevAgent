from __future__ import annotations

import sqlite3

from devagent.storage import SQLiteDatabase

from .sequence import SequencePersistenceError, SequenceTaskNotFoundError


class SQLiteSequenceAllocator:
    """通过持久化 reservation 行原子分配 task 内事件序号。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def next(self, task_id: str) -> int:
        try:
            with self._database.transaction(immediate=True) as connection:
                row = connection.execute(
                    """
                    SELECT next_sequence_id
                    FROM event_sequences
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                if row is None:
                    next_value = self._initial_sequence(connection, task_id)
                    connection.execute(
                        """
                        INSERT INTO event_sequences(task_id, next_sequence_id)
                        VALUES (?, ?)
                        """,
                        (task_id, next_value + 1),
                    )
                else:
                    next_value = int(row["next_sequence_id"])
                    connection.execute(
                        """
                        UPDATE event_sequences
                        SET next_sequence_id = ?
                        WHERE task_id = ?
                        """,
                        (next_value + 1, task_id),
                    )
        except sqlite3.IntegrityError as exc:
            if getattr(exc, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_FOREIGNKEY":
                raise SequenceTaskNotFoundError(f"任务不存在: {task_id}") from exc
            raise SequencePersistenceError("分配事件序号失败") from exc
        except sqlite3.Error as exc:
            raise SequencePersistenceError("分配事件序号失败") from exc
        return next_value

    @staticmethod
    def _initial_sequence(connection: sqlite3.Connection, task_id: str) -> int:
        task = connection.execute(
            "SELECT 1 FROM agent_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            raise SequenceTaskNotFoundError(f"任务不存在: {task_id}")
        row = connection.execute(
            """
            SELECT COALESCE(MAX(sequence_id), 0) + 1 AS next_sequence_id
            FROM agent_events
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        return int(row["next_sequence_id"])
