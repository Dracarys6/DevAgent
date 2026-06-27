from uuid import UUID

from fastapi.testclient import TestClient

from devagent.api.app import app

client = TestClient(app)


def test_create_agent_task_returns_pending():
    response = client.post(
        "/api/v1/agent/tasks",
        json={"question": "请分析项目"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PENDING"
    assert isinstance(data["task_id"], str)
    assert data["task_id"]


def test_create_agent_task_returns_uuid_task_id():
    response = client.post(
        "/api/v1/agent/tasks",
        json={"question": "请分析项目"},
    )

    data = response.json()

    UUID(data["task_id"])


def test_create_agent_task_returns_different_task_ids():
    first = client.post(
        "/api/v1/agent/tasks",
        json={"question": "请分析第一个任务"},
    )
    second = client.post(
        "/api/v1/agent/tasks",
        json={"question": "请分析第二个任务"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["task_id"] != second.json()["task_id"]


def test_create_agent_task_accepts_full_request_payload():
    response = client.post(
        "/api/v1/agent/tasks",
        json={
            "question": "请分析项目",
            "workspace": ".",
            "provider": "real",
            "model": "test-model",
            "base_url": "https://example.test/v1",
            "max_steps": 5,
            "max_tool_calls": 8,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"


def test_get_agent_task_returns_created_task_detail():
    created = client.post(
        "/api/v1/agent/tasks",
        json={
            "question": "请分析项目",
            "workspace": ".",
            "provider": "mock",
            "max_steps": 7,
            "max_tool_calls": 9,
        },
    )
    task_id = created.json()["task_id"]

    response = client.get(f"/api/v1/agent/tasks/{task_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == task_id
    assert data["question"] == "请分析项目"
    assert data["workspace"] == "."
    assert data["provider"] == "mock"
    assert data["max_steps"] == 7
    assert data["max_tool_calls"] == 9
    assert data["status"] == "PENDING"
    assert data["error_message"] is None
    assert data["created_at"]
    assert data["updated_at"]


def test_get_agent_task_returns_404_for_missing_task():
    response = client.get("/api/v1/agent/tasks/not-found")

    assert response.status_code == 404


def test_cancel_pending_task_then_get_cancelled_status():
    created = client.post(
        "/api/v1/agent/tasks",
        json={"question": "请分析项目"},
    )
    task_id = created.json()["task_id"]

    cancelled = client.post(f"/api/v1/agent/tasks/{task_id}/cancel")
    fetched = client.get(f"/api/v1/agent/tasks/{task_id}")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "CANCELLED"


def test_cancel_missing_task_returns_404():
    response = client.post("/api/v1/agent/tasks/not-found/cancel")

    assert response.status_code == 404


def test_cancel_terminal_task_returns_409():
    created = client.post(
        "/api/v1/agent/tasks",
        json={"question": "请分析项目"},
    )
    task_id = created.json()["task_id"]

    first_cancel = client.post(f"/api/v1/agent/tasks/{task_id}/cancel")
    second_cancel = client.post(f"/api/v1/agent/tasks/{task_id}/cancel")

    assert first_cancel.status_code == 200
    assert second_cancel.status_code == 409
    assert "CANCELLED -> CANCELLED" in second_cancel.json()["detail"]


def test_list_agent_tasks_contains_created_task():
    created = client.post(
        "/api/v1/agent/tasks",
        json={"question": "请分析列表接口"},
    )
    task_id = created.json()["task_id"]

    response = client.get("/api/v1/agent/tasks/list")

    assert response.status_code == 200
    task_ids = [task["task_id"] for task in response.json()["tasks"]]
    assert task_id in task_ids


def test_create_agent_task_rejects_empty_question():
    response = client.post(
        "/api/v1/agent/tasks",
        json={"question": ""},
    )

    assert response.status_code == 422


def test_create_agent_task_rejects_missing_question():
    response = client.post(
        "/api/v1/agent/tasks",
        json={},
    )

    assert response.status_code == 422


def test_create_agent_task_rejects_invalid_max_steps():
    response = client.post(
        "/api/v1/agent/tasks",
        json={"question": "x", "max_steps": 0},
    )

    assert response.status_code == 422


def test_create_agent_task_rejects_too_large_max_steps():
    response = client.post(
        "/api/v1/agent/tasks",
        json={"question": "x", "max_steps": 51},
    )

    assert response.status_code == 422


def test_create_agent_task_rejects_invalid_max_tool_calls():
    response = client.post(
        "/api/v1/agent/tasks",
        json={"question": "x", "max_tool_calls": 0},
    )

    assert response.status_code == 422


def test_create_agent_task_rejects_too_large_max_tool_calls():
    response = client.post(
        "/api/v1/agent/tasks",
        json={"question": "x", "max_tool_calls": 101},
    )

    assert response.status_code == 422


def test_create_agent_task_rejects_invalid_provider():
    response = client.post(
        "/api/v1/agent/tasks",
        json={"question": "x", "provider": "bad"},
    )

    assert response.status_code == 422


def test_openapi_schema_contains_create_task_path():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/agent/tasks" in response.json()["paths"]
    assert "/api/v1/agent/tasks/{task_id}" in response.json()["paths"]
    assert "/api/v1/agent/tasks/{task_id}/cancel" in response.json()["paths"]
