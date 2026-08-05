from __future__ import annotations

import os
from pathlib import Path

from devagent.storage import SQLiteDatabase, SQLiteSettings

from .repository import InMemoryTaskRepository, TaskRepository
from .sqlite_repository import SQLiteTaskRepository

TASK_DATABASE_PATH_ENV = "DEVAGENT_DATABASE_PATH"


def create_task_repository(
    database_path: str | Path | None = None,
) -> TaskRepository:
    """根据显式数据库路径创建内存或 SQLite Task Repository。"""
    if database_path is None:
        return InMemoryTaskRepository()
    if isinstance(database_path, str) and database_path != database_path.strip():
        raise ValueError("database_path 不能包含首尾空白")
    database = SQLiteDatabase(SQLiteSettings(path=Path(database_path)))
    database.initialize()
    return SQLiteTaskRepository(database)


def create_configured_task_repository() -> TaskRepository:
    value = os.getenv(TASK_DATABASE_PATH_ENV)
    if value is None or not value.strip():
        return InMemoryTaskRepository()
    return create_task_repository(value)
