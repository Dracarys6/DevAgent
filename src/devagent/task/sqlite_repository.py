from __future__ import annotations

import sqlite3

from pydantic import ValidationError

from devagent.storage import SQLiteDatabase

from .models import AgentTask, TaskStatus
from .repository import (
    TaskAlreadyExistsError,
    TaskNotFoundError,
    TaskPersistenceError,
)

_TASK_COLUMNS = """
    task_id,
    question,
    workspace,
    provider,
    model,
    base_url,
    max_steps,
    max_tool_calls,
    status,
    error_message,
    created_at,
    updated_at
"""


class SQLiteTaskRepository:
    """使用 SQLite 持久化 AgentTask，并保留领域状态机语义。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def create(self, task: AgentTask) -> AgentTask:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    f"""
                    INSERT INTO agent_tasks ({_TASK_COLUMNS})
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _task_values(task),
                )
        except sqlite3.IntegrityError as exc:
            if _is_duplicate_task_error(exc):
                raise TaskAlreadyExistsError(f"任务已存在: {task.task_id}") from exc
            raise TaskPersistenceError("创建任务失败") from exc
        except sqlite3.Error as exc:
            raise TaskPersistenceError("创建任务失败") from exc
        return task.model_copy(deep=True)

    def get(self, task_id: str) -> AgentTask:
        try:
            connection = self._database.connect()
            try:
                row = _select_task(connection, task_id)
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise TaskPersistenceError("读取任务失败") from exc
        if row is None:
            raise TaskNotFoundError(f"任务不存在: {task_id}")
        return _task_from_row(row)

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        error_message: str | None = None,
    ) -> AgentTask:
        try:
            # * 状态读取、领域校验与写回必须由同一个 writer 事务保护。
            with self._database.transaction(immediate=True) as connection:
                row = _select_task(connection, task_id)
                if row is None:
                    raise TaskNotFoundError(f"任务不存在: {task_id}")
                task = _task_from_row(row)
                task.transition_to(status, error_message=error_message)
                cursor = connection.execute(
                    """
                    UPDATE agent_tasks
                    SET status = ?, error_message = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        task.status.value,
                        task.error_message,
                        task.updated_at.isoformat(),
                        task.task_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise TaskPersistenceError("更新任务状态时记录数量异常")
        except (TaskNotFoundError, TaskPersistenceError):
            raise
        except sqlite3.Error as exc:
            raise TaskPersistenceError("更新任务状态失败") from exc
        return task.model_copy(deep=True)

    def list(self) -> list[AgentTask]:
        try:
            connection = self._database.connect()
            try:
                rows = connection.execute(
                    f"""
                    SELECT {_TASK_COLUMNS}
                    FROM agent_tasks
                    ORDER BY created_at ASC, rowid ASC
                    """
                ).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise TaskPersistenceError("列出任务失败") from exc
        return [_task_from_row(row) for row in rows]


def _select_task(
    connection: sqlite3.Connection,
    task_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        f"SELECT {_TASK_COLUMNS} FROM agent_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()


def _task_values(task: AgentTask) -> tuple[object, ...]:
    return (
        task.task_id,
        task.question,
        task.workspace,
        task.provider,
        task.model,
        task.base_url,
        task.max_steps,
        task.max_tool_calls,
        task.status.value,
        task.error_message,
        task.created_at.isoformat(),
        task.updated_at.isoformat(),
    )


def _task_from_row(row: sqlite3.Row) -> AgentTask:
    try:
        return AgentTask.model_validate(dict(row))
    except ValidationError as exc:
        raise TaskPersistenceError("数据库中的任务数据无效") from exc


def _is_duplicate_task_error(error: sqlite3.IntegrityError) -> bool:
    error_name = getattr(error, "sqlite_errorname", "")
    if error_name in {"SQLITE_CONSTRAINT_PRIMARYKEY", "SQLITE_CONSTRAINT_UNIQUE"}:
        return True
    return "UNIQUE constraint failed: agent_tasks.task_id" in str(error)
