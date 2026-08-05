from pathlib import Path

from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes import tasks as tasks_route
from devagent.api.routes import traces as traces_route
from devagent.event import create_event_runtime
from devagent.permission import InMemoryPermissionManager, InMemoryPermissionPolicyStore
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import SQLiteTaskRepository, TaskManager
from devagent.trace import TraceService


def configure_persistent_runtime(database_path: Path) -> None:
    database = SQLiteDatabase(SQLiteSettings(path=database_path))
    database.initialize()
    repository = SQLiteTaskRepository(database)
    event_runtime = create_event_runtime(database_path)
    manager = TaskManager(
        repository=repository,
        event_bus=event_runtime.event_bus,
        permission_manager=InMemoryPermissionManager(
            event_bus=event_runtime.event_bus,
            sequence_allocator=event_runtime.sequence_allocator,
        ),
        policy_store=InMemoryPermissionPolicyStore(),
        sequence_allocator=event_runtime.sequence_allocator,
    )

    tasks_route.task_repository = repository
    tasks_route.event_bus = event_runtime.event_bus
    tasks_route.sequence_allocator = event_runtime.sequence_allocator
    tasks_route.task_manager = manager
    traces_route.task_repository = repository
    traces_route.trace_service = TraceService(event_runtime.event_bus)


def test_trace_api_replays_events_after_runtime_reconstruction(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "trace-restart.db"
    client = TestClient(app)
    original_values = {
        "task_repository": tasks_route.task_repository,
        "event_bus": tasks_route.event_bus,
        "sequence_allocator": tasks_route.sequence_allocator,
        "task_manager": tasks_route.task_manager,
        "trace_repository": traces_route.task_repository,
        "trace_service": traces_route.trace_service,
    }
    try:
        configure_persistent_runtime(database_path)
        create_response = client.post(
            "/api/v1/agent/tasks",
            json={"question": "Day66 persistent trace", "provider": "mock"},
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["task_id"]

        before_restart = client.get(f"/api/v1/agent/tasks/{task_id}/trace")
        assert before_restart.status_code == 200
        assert before_restart.json()["summary"]["event_count"] >= 4

        configure_persistent_runtime(database_path)
        after_restart = client.get(f"/api/v1/agent/tasks/{task_id}/trace")

        assert after_restart.status_code == 200
        assert after_restart.json() == before_restart.json()
        sequence_ids = [step["sequence_id"] for step in after_restart.json()["steps"]]
        assert sequence_ids == sorted(sequence_ids)
        assert len(sequence_ids) == len(set(sequence_ids))
    finally:
        tasks_route.task_repository = original_values["task_repository"]
        tasks_route.event_bus = original_values["event_bus"]
        tasks_route.sequence_allocator = original_values["sequence_allocator"]
        tasks_route.task_manager = original_values["task_manager"]
        traces_route.task_repository = original_values["trace_repository"]
        traces_route.trace_service = original_values["trace_service"]
