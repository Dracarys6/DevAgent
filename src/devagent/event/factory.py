from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from devagent.storage import SQLiteDatabase, SQLiteSettings

from .bus import InMemoryEventBus
from .models import InMemorySequenceAllocator
from .sequence import SequenceAllocator
from .sqlite_sequence import SQLiteSequenceAllocator
from .sqlite_store import SQLiteEventStore
from .store import InMemoryStructuredEventStore

EVENT_DATABASE_PATH_ENV = "DEVAGENT_DATABASE_PATH"


@dataclass(frozen=True)
class EventRuntimeComponents:
    event_bus: InMemoryEventBus
    sequence_allocator: SequenceAllocator


def create_event_runtime(
    database_path: str | Path | None = None,
) -> EventRuntimeComponents:
    if database_path is None:
        return EventRuntimeComponents(
            event_bus=InMemoryEventBus(InMemoryStructuredEventStore()),
            sequence_allocator=InMemorySequenceAllocator(),
        )
    if isinstance(database_path, str) and database_path != database_path.strip():
        raise ValueError("database_path 不能包含首尾空白")
    database = SQLiteDatabase(SQLiteSettings(path=Path(database_path)))
    database.initialize()
    return EventRuntimeComponents(
        event_bus=InMemoryEventBus(SQLiteEventStore(database)),
        sequence_allocator=SQLiteSequenceAllocator(database),
    )


def create_configured_event_runtime() -> EventRuntimeComponents:
    value = os.getenv(EVENT_DATABASE_PATH_ENV)
    if value is None or not value.strip():
        return create_event_runtime()
    return create_event_runtime(value)
