import threading
from pathlib import Path

import pytest

from devagent.event import (
    AgentStarted,
    SequenceTaskNotFoundError,
    SQLiteEventStore,
    SQLiteSequenceAllocator,
)
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import AgentTask, SQLiteTaskRepository


def make_allocator(
    tmp_path: Path,
) -> tuple[SQLiteDatabase, SQLiteSequenceAllocator]:
    database = SQLiteDatabase(
        SQLiteSettings(path=tmp_path / "sequences.db", busy_timeout_ms=5_000)
    )
    database.initialize()
    repository = SQLiteTaskRepository(database)
    repository.create(AgentTask(task_id="task-1", question="sequence"))
    repository.create(AgentTask(task_id="task-2", question="sequence 2"))
    return database, SQLiteSequenceAllocator(database)


def test_sqlite_sequence_is_monotonic_and_independent(tmp_path: Path) -> None:
    _, allocator = make_allocator(tmp_path)

    assert [allocator.next("task-1") for _ in range(3)] == [1, 2, 3]
    assert allocator.next("task-2") == 1


def test_sqlite_sequence_survives_new_allocator_instance(tmp_path: Path) -> None:
    database, allocator = make_allocator(tmp_path)
    assert allocator.next("task-1") == 1

    reopened = SQLiteSequenceAllocator(
        SQLiteDatabase(SQLiteSettings(path=database.settings.path))
    )

    assert reopened.next("task-1") == 2


def test_sqlite_sequence_initializes_after_existing_events(tmp_path: Path) -> None:
    database, allocator = make_allocator(tmp_path)
    SQLiteEventStore(database).append(
        AgentStarted(task_id="task-1", sequence_id=5, message="existing")
    )

    assert allocator.next("task-1") == 6


def test_sqlite_sequence_rejects_missing_task(tmp_path: Path) -> None:
    _, allocator = make_allocator(tmp_path)

    with pytest.raises(SequenceTaskNotFoundError, match="任务不存在"):
        allocator.next("missing")


def test_sqlite_sequence_concurrent_allocations_are_unique(tmp_path: Path) -> None:
    _, allocator = make_allocator(tmp_path)
    barrier = threading.Barrier(21)
    values: list[int] = []

    def allocate() -> None:
        barrier.wait()
        values.append(allocator.next("task-1"))

    threads = [threading.Thread(target=allocate) for _ in range(20)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(values) == list(range(1, 21))
