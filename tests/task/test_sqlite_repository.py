import sqlite3
import threading
from pathlib import Path

import pytest

from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import (
    AgentTask,
    InvalidTaskTransitionError,
    SQLiteTaskRepository,
    TaskPersistenceError,
    TaskStatus,
)


def make_repository(tmp_path: Path) -> tuple[SQLiteDatabase, SQLiteTaskRepository]:
    database = SQLiteDatabase(
        SQLiteSettings(path=tmp_path / "tasks.db", busy_timeout_ms=5_000)
    )
    database.initialize()
    return database, SQLiteTaskRepository(database)


def test_sqlite_repository_survives_new_database_instance(tmp_path: Path) -> None:
    path = tmp_path / "restart.db"
    first_database = SQLiteDatabase(SQLiteSettings(path=path))
    first_database.initialize()
    first_repository = SQLiteTaskRepository(first_database)
    task = first_repository.create(AgentTask(question="persist me"))
    first_repository.update_status(task.task_id, TaskStatus.RUNNING)

    second_database = SQLiteDatabase(SQLiteSettings(path=path))
    second_database.initialize()
    restored = SQLiteTaskRepository(second_database).get(task.task_id)

    assert restored.status is TaskStatus.RUNNING
    assert restored.question == "persist me"


def test_sqlite_repository_rejects_corrupted_task_row(tmp_path: Path) -> None:
    database, repository = make_repository(tmp_path)
    task = repository.create(AgentTask(question="corrupt me"))
    with database.transaction() as connection:
        connection.execute(
            "UPDATE agent_tasks SET created_at = 'not-a-datetime' WHERE task_id = ?",
            (task.task_id,),
        )

    with pytest.raises(TaskPersistenceError, match="数据无效"):
        repository.get(task.task_id)


def test_sqlite_repository_wraps_database_errors(tmp_path: Path) -> None:
    database, repository = make_repository(tmp_path)
    with database.transaction() as connection:
        connection.execute("DROP TABLE agent_tasks")

    with pytest.raises(TaskPersistenceError, match="读取任务失败") as captured:
        repository.get("task")

    assert isinstance(captured.value.__cause__, sqlite3.Error)


def test_concurrent_status_updates_do_not_validate_same_stale_state(
    tmp_path: Path,
) -> None:
    _, repository = make_repository(tmp_path)
    task = repository.create(AgentTask(question="concurrent"))
    barrier = threading.Barrier(3)
    outcomes: list[TaskStatus | type[BaseException]] = []

    def update() -> None:
        barrier.wait()
        try:
            outcomes.append(
                repository.update_status(task.task_id, TaskStatus.RUNNING).status
            )
        except InvalidTaskTransitionError as exc:
            outcomes.append(type(exc))

    threads = [threading.Thread(target=update) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert outcomes.count(TaskStatus.RUNNING) == 1
    assert outcomes.count(InvalidTaskTransitionError) == 1
    assert repository.get(task.task_id).status is TaskStatus.RUNNING
