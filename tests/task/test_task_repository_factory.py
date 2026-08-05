from pathlib import Path

import pytest

from devagent.task import (
    AgentTask,
    InMemoryTaskRepository,
    SQLiteTaskRepository,
    create_configured_task_repository,
    create_task_repository,
)


def test_factory_defaults_to_in_memory_repository() -> None:
    repository = create_task_repository()

    assert isinstance(repository, InMemoryTaskRepository)


def test_configured_factory_defaults_to_memory_when_env_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVAGENT_DATABASE_PATH", raising=False)

    repository = create_configured_task_repository()

    assert isinstance(repository, InMemoryTaskRepository)


def test_factory_reopens_same_sqlite_database(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    first = create_task_repository(path)
    assert isinstance(first, SQLiteTaskRepository)
    task = first.create(AgentTask(question="factory persistence"))

    second = create_task_repository(path)

    assert isinstance(second, SQLiteTaskRepository)
    assert second.get(task.task_id) == task


def test_configured_factory_uses_database_path_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVAGENT_DATABASE_PATH", str(tmp_path / "configured.db"))

    repository = create_configured_task_repository()

    assert isinstance(repository, SQLiteTaskRepository)


def test_factory_rejects_path_with_surrounding_whitespace(tmp_path: Path) -> None:
    path = f" {tmp_path / 'tasks.db'} "

    with pytest.raises(ValueError, match="首尾空白"):
        create_task_repository(path)
