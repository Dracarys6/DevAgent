from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes.permissions import permission_manager
from devagent.permission import PermissionRequest, RiskLevel

client = TestClient(app)


def create_permission_request(
    *,
    tool_name: str = "run_shell",
    risk_level: RiskLevel = RiskLevel.HIGH,
    reason: str = "run_shell 需要审批",
    tool_arguments: dict | None = None,
    task_id: str = "task_1",
    tool_call_id: str = "tool_call_1",
) -> PermissionRequest:
    return permission_manager.request_permission(
        tool_name=tool_name,
        risk_level=risk_level,
        reason=reason,
        tool_arguments=tool_arguments or {"command": ["pytest", "-q"]},
        task_id=task_id,
        tool_call_id=tool_call_id,
    )


def test_get_pending_requests_returns_created_pending_request():
    created = create_permission_request(
        tool_name="run_shell",
        reason="测试 pending 列表",
    )

    response = client.get("/api/v1/permissions/pending")

    assert response.status_code == 200
    data = response.json()
    request_ids = [request["request_id"] for request in data["requests"]]
    assert created.request_id in request_ids


def test_get_permission_request_returns_detail():
    created = create_permission_request(
        tool_arguments={"command": ["pytest", "-q"], "cwd": "."},
        task_id="task_detail",
        tool_call_id="call_detail",
    )

    response = client.get(f"/api/v1/permissions/{created.request_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == created.request_id
    assert data["task_id"] == "task_detail"
    assert data["tool_call_id"] == "call_detail"
    assert data["tool_name"] == "run_shell"
    assert data["tool_arguments"] == {"command": ["pytest", "-q"], "cwd": "."}
    assert data["risk_level"] == "HIGH"
    assert data["status"] == "PENDING"
    assert data["decision"] is None
    assert data["created_at"]
    assert data["updated_at"]


def test_get_permission_request_returns_404_for_missing_request():
    response = client.get("/api/v1/permissions/not-found")

    assert response.status_code == 404


def test_resolve_permission_request_allow_returns_approved():
    created = create_permission_request(reason="允许测试")

    response = client.post(
        f"/api/v1/permissions/{created.request_id}/resolve",
        json={"decision": "ALLOW", "decision_reason": "确认安全"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == created.request_id
    assert data["status"] == "APPROVED"
    assert data["decision"] == "ALLOW"
    assert data["decision_reason"] == "确认安全"
    assert data["resolved_at"] is not None


def test_resolve_permission_request_deny_returns_denied():
    created = create_permission_request(reason="拒绝测试")

    response = client.post(
        f"/api/v1/permissions/{created.request_id}/resolve",
        json={"decision": "DENY", "decision_reason": "命令风险过高"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "DENIED"
    assert data["decision"] == "DENY"
    assert data["decision_reason"] == "命令风险过高"
    assert data["resolved_at"] is not None


def test_resolved_request_is_removed_from_pending_list():
    created = create_permission_request()

    resolve_response = client.post(
        f"/api/v1/permissions/{created.request_id}/resolve",
        json={"decision": "ALLOW"},
    )
    pending_response = client.get("/api/v1/permissions/pending")

    assert resolve_response.status_code == 200
    pending_ids = [
        request["request_id"] for request in pending_response.json()["requests"]
    ]
    assert created.request_id not in pending_ids


def test_resolve_same_request_twice_returns_409_and_preserves_first_decision():
    created = create_permission_request()

    first = client.post(
        f"/api/v1/permissions/{created.request_id}/resolve",
        json={"decision": "ALLOW", "decision_reason": "第一次审批"},
    )
    second = client.post(
        f"/api/v1/permissions/{created.request_id}/resolve",
        json={"decision": "DENY", "decision_reason": "第二次审批"},
    )
    fetched = client.get(f"/api/v1/permissions/{created.request_id}")

    assert first.status_code == 200
    assert second.status_code == 409
    assert fetched.json()["status"] == "APPROVED"
    assert fetched.json()["decision"] == "ALLOW"
    assert fetched.json()["decision_reason"] == "第一次审批"


def test_resolve_missing_request_returns_404():
    response = client.post(
        "/api/v1/permissions/not-found/resolve",
        json={"decision": "ALLOW"},
    )

    assert response.status_code == 404


def test_resolve_rejects_invalid_decision():
    created = create_permission_request()

    response = client.post(
        f"/api/v1/permissions/{created.request_id}/resolve",
        json={"decision": "BAD"},
    )

    assert response.status_code == 422


def test_permission_response_serializes_enum_fields_as_strings():
    created = create_permission_request(risk_level=RiskLevel.CRITICAL)

    response = client.get(f"/api/v1/permissions/{created.request_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["risk_level"] == "CRITICAL"
    assert data["status"] == "PENDING"


def test_openapi_schema_contains_permission_paths():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/permissions/pending" in paths
    assert "/api/v1/permissions/{request_id}" in paths
    assert "/api/v1/permissions/{request_id}/resolve" in paths
