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
