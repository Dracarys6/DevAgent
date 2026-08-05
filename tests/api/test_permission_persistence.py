from pathlib import Path

from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes import permissions as permissions_route
from devagent.event import create_event_runtime
from devagent.permission import PermissionDecision, RiskLevel, create_permission_runtime
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import AgentTask, SQLiteTaskRepository, TaskManager


def configure_runtime(database_path: Path):
    database = SQLiteDatabase(SQLiteSettings(path=database_path))
    database.initialize()
    repository = SQLiteTaskRepository(database)
    events = create_event_runtime(database_path)
    permissions = create_permission_runtime(
        database_path,
        event_bus=events.event_bus,
        sequence_allocator=events.sequence_allocator,
    )
    manager = TaskManager(
        repository=repository,
        event_bus=events.event_bus,
        sequence_allocator=events.sequence_allocator,
        permission_manager=permissions.manager,
        policy_store=permissions.policy_store,
        tool_call_store=permissions.tool_call_store,
    )
    permissions_route.permission_manager = permissions.manager
    permissions_route.task_manager = manager
    return repository, permissions.manager


def test_permission_api_reads_and_resolves_request_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "permission-api.db"
    client = TestClient(app)
    original_manager = permissions_route.permission_manager
    original_task_manager = permissions_route.task_manager
    try:
        repository, manager = configure_runtime(database_path)
        repository.create(AgentTask(task_id="task-1", question="approve after restart"))
        request = manager.request_permission(
            task_id="task-1",
            tool_call_id="call-1",
            tool_name="run_shell",
            risk_level=RiskLevel.HIGH,
            reason="approval",
        )

        configure_runtime(database_path)
        get_response = client.get(f"/api/v1/permissions/{request.request_id}")
        resolve_response = client.post(
            f"/api/v1/permissions/{request.request_id}/resolve",
            json={"decision": PermissionDecision.DENY.value, "decision_reason": "no"},
        )

        assert get_response.status_code == 200
        assert get_response.json()["status"] == "PENDING"
        assert resolve_response.status_code == 200
        assert resolve_response.json()["status"] == "DENIED"
    finally:
        permissions_route.permission_manager = original_manager
        permissions_route.task_manager = original_task_manager
