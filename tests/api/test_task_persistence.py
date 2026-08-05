from pathlib import Path

from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes import tasks as tasks_route
from devagent.task import TaskManager, create_task_repository


def test_task_api_reads_task_after_repository_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "api-tasks.db"
    first_repository = create_task_repository(path)
    first_manager = TaskManager(first_repository)
    monkeypatch.setattr(tasks_route, "task_repository", first_repository)
    monkeypatch.setattr(tasks_route, "task_manager", first_manager)
    client = TestClient(app)

    created = client.post(
        "/api/v1/agent/tasks",
        json={"question": "persistent API task", "provider": "mock"},
    )
    task_id = created.json()["task_id"]

    second_repository = create_task_repository(path)
    second_manager = TaskManager(second_repository)
    monkeypatch.setattr(tasks_route, "task_repository", second_repository)
    monkeypatch.setattr(tasks_route, "task_manager", second_manager)

    restored = client.get(f"/api/v1/agent/tasks/{task_id}")

    assert created.status_code == 201
    assert restored.status_code == 200
    assert restored.json()["task_id"] == task_id
    assert restored.json()["question"] == "persistent API task"
    assert restored.json()["status"] == "DONE"
