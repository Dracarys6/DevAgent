from datetime import UTC, datetime
from pathlib import Path

import pytest

from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import (
    AgentTask,
    InMemoryTaskRepository,
    InvalidTaskTransitionError,
    SQLiteTaskRepository,
    TaskAlreadyExistsError,
    TaskNotFoundError,
    TaskRepository,
    TaskStatus,
)


@pytest.fixture(params=("memory", "sqlite"))
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> TaskRepository:
    if request.param == "memory":
        return InMemoryTaskRepository()
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "tasks.db"))
    database.initialize()
    return SQLiteTaskRepository(database)


def test_repository_round_trips_all_task_fields(repository: TaskRepository) -> None:
    task = AgentTask(
        task_id="task-all-fields",
        question="diagnose CI failure",
        workspace="/workspace",
        provider="real",
        model="test-model",
        base_url="https://example.test/v1",
        max_steps=7,
        max_tool_calls=13,
        created_at=datetime(2026, 8, 5, 1, 2, 3, tzinfo=UTC),
        updated_at=datetime(2026, 8, 5, 1, 2, 4, tzinfo=UTC),
    )

    created = repository.create(task)

    assert created == task
    assert repository.get(task.task_id) == task


def test_repository_rejects_duplicate_task_id(repository: TaskRepository) -> None:
    task = AgentTask(task_id="duplicate", question="first")
    repository.create(task)

    with pytest.raises(TaskAlreadyExistsError, match="任务已存在"):
        repository.create(task.model_copy(update={"question": "second"}))

    assert repository.get(task.task_id).question == "first"


def test_repository_get_missing_raises_not_found(repository: TaskRepository) -> None:
    with pytest.raises(TaskNotFoundError, match="任务不存在"):
        repository.get("missing")


def test_repository_updates_status_and_error(repository: TaskRepository) -> None:
    task = repository.create(AgentTask(question="run task"))

    running = repository.update_status(task.task_id, TaskStatus.RUNNING)
    failed = repository.update_status(
        task.task_id,
        TaskStatus.FAILED,
        error_message="provider unavailable",
    )

    assert running.status is TaskStatus.RUNNING
    assert running.updated_at > task.updated_at
    assert failed.status is TaskStatus.FAILED
    assert failed.error_message == "provider unavailable"
    assert repository.get(task.task_id) == failed


def test_repository_clears_previous_error_on_next_transition(
    repository: TaskRepository,
) -> None:
    task = repository.create(AgentTask(question="permission task"))
    repository.update_status(
        task.task_id,
        TaskStatus.RUNNING,
        error_message="transient",
    )

    waiting = repository.update_status(
        task.task_id,
        TaskStatus.WAITING_PERMISSION,
    )

    assert waiting.error_message is None


def test_repository_preserves_domain_transition_rules(
    repository: TaskRepository,
) -> None:
    task = repository.create(AgentTask(question="invalid transition"))

    with pytest.raises(InvalidTaskTransitionError, match="PENDING -> DONE"):
        repository.update_status(task.task_id, TaskStatus.DONE)

    assert repository.get(task.task_id).status is TaskStatus.PENDING


def test_repository_update_missing_raises_not_found(
    repository: TaskRepository,
) -> None:
    with pytest.raises(TaskNotFoundError, match="任务不存在"):
        repository.update_status("missing", TaskStatus.RUNNING)


def test_repository_lists_tasks_in_creation_order(repository: TaskRepository) -> None:
    created_at = datetime(2026, 8, 5, tzinfo=UTC)
    first = repository.create(
        AgentTask(task_id="z-first", question="first", created_at=created_at)
    )
    second = repository.create(
        AgentTask(task_id="a-second", question="second", created_at=created_at)
    )

    assert [task.task_id for task in repository.list()] == [
        first.task_id,
        second.task_id,
    ]


def test_repository_returns_detached_models(repository: TaskRepository) -> None:
    original = AgentTask(question="detached")
    created = repository.create(original)
    created.status = TaskStatus.DONE

    fetched = repository.get(original.task_id)
    fetched.status = TaskStatus.DONE
    listed = repository.list()
    listed[0].status = TaskStatus.DONE

    assert repository.get(original.task_id).status is TaskStatus.PENDING
