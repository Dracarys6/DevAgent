from dataclasses import dataclass
from pathlib import Path

from devagent.event import SequenceAllocator
from devagent.event.bus import InMemoryEventBus
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.tools.call_store import SQLiteToolCallStore, ToolCallStore

from .manager import InMemoryPermissionManager
from .policy_store import InMemoryPermissionPolicyStore
from .sqlite_stores import SQLitePermissionPolicyStore, SQLitePermissionRequestStore


@dataclass(frozen=True)
class PermissionRuntimeComponents:
    manager: InMemoryPermissionManager
    policy_store: InMemoryPermissionPolicyStore | SQLitePermissionPolicyStore
    tool_call_store: ToolCallStore | None


def create_permission_runtime(
    database_path: str | Path | None,
    *,
    event_bus: InMemoryEventBus,
    sequence_allocator: SequenceAllocator,
) -> PermissionRuntimeComponents:
    if database_path is None:
        return PermissionRuntimeComponents(
            manager=InMemoryPermissionManager(
                event_bus=event_bus,
                sequence_allocator=sequence_allocator,
            ),
            policy_store=InMemoryPermissionPolicyStore(),
            tool_call_store=None,
        )
    database = SQLiteDatabase(SQLiteSettings(path=Path(database_path)))
    database.initialize()
    return PermissionRuntimeComponents(
        manager=InMemoryPermissionManager(
            event_bus=event_bus,
            sequence_allocator=sequence_allocator,
            request_store=SQLitePermissionRequestStore(database),
        ),
        policy_store=SQLitePermissionPolicyStore(database),
        tool_call_store=SQLiteToolCallStore(database),
    )
