from fastapi.testclient import TestClient
import pytest
from pydantic import BaseModel

from devagent.agent import AgentRuntime
from devagent.api.app import app
from devagent.api.routes.permissions import permission_manager, task_manager
from devagent.event import EventType
from devagent.llm import LLMResponse, MockLLMClient, ToolCall
from devagent.permission import PermissionRequest, RiskLevel
from devagent.task import AgentTask, TaskStatus
from devagent.tools import BaseTool, ToolExecutor, ToolRegistry, ToolResult

client = TestClient(app)


class APIApprovalArgs(BaseModel):
    value: str


class APIApprovalTool(BaseTool[APIApprovalArgs]):
    name = "api_approval"
    description = "测试 Permission API 恢复 Agent。"
    args_model = APIApprovalArgs
    risk_level = RiskLevel.HIGH

    def __init__(self) -> None:
        self.call_count = 0

    def execute(self, args: APIApprovalArgs) -> ToolResult:
        self.call_count += 1
        return ToolResult.ok(f"api:{args.value}")


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


@pytest.mark.parametrize(
    ("decision", "expected_tool_event", "expected_call_count"),
    [
        ("ALLOW", EventType.TOOL_CALL_FINISHED, 1),
        ("DENY", EventType.TOOL_CALL_FAILED, 0),
    ],
)
def test_resolve_runtime_permission_resumes_agent_and_completes_trace(
    monkeypatch,
    decision: str,
    expected_tool_event: EventType,
    expected_call_count: int,
):
    registry = ToolRegistry()
    tool = APIApprovalTool()
    registry.register(tool)
    executor = ToolExecutor(
        registry=registry,
        permission_manager=permission_manager,
        policy_store=task_manager.policy_store,
    )
    client_instance = MockLLMClient(
        responses=[
            LLMResponse.tool_calls_response(
                [
                    ToolCall(
                        id="api-approval-call",
                        name=tool.name,
                        arguments={"value": "safe"},
                    )
                ]
            ),
            LLMResponse.final_answer("API 审批恢复完成"),
        ]
    )

    def create_runtime(task: AgentTask) -> AgentRuntime:
        return AgentRuntime(
            llm_client=client_instance,
            tool_registry=registry,
            tool_executor=executor,
            event_bus=task_manager.event_bus,
            sequence_allocator=task_manager.sequence_allocator,
            task_id=task.task_id,
            workspace=task.workspace,
        )

    monkeypatch.setattr(task_manager, "_runtime_factory", create_runtime)

    created = client.post(
        "/api/v1/agent/tasks",
        json={"question": "执行需要审批的工具", "provider": "mock"},
    )
    task_id = created.json()["task_id"]
    waiting_task = client.get(f"/api/v1/agent/tasks/{task_id}")
    pending = [
        request
        for request in permission_manager.list_pending()
        if request.task_id == task_id
    ]

    assert waiting_task.json()["status"] == TaskStatus.WAITING_PERMISSION.value
    assert len(pending) == 1
    assert tool.call_count == 0

    resolved = client.post(
        f"/api/v1/permissions/{pending[0].request_id}/resolve",
        json={"decision": decision, "decision_reason": "审批结论已确认"},
    )
    completed_task = client.get(f"/api/v1/agent/tasks/{task_id}")
    trace = client.get(f"/api/v1/agent/tasks/{task_id}/trace").json()

    assert resolved.status_code == 200
    assert completed_task.json()["status"] == TaskStatus.DONE.value
    assert tool.call_count == expected_call_count
    assert [step["event_type"] for step in trace["steps"]] == [
        EventType.AGENT_STARTED.value,
        EventType.LLM_CALL_STARTED.value,
        EventType.LLM_CALL_FINISHED.value,
        EventType.TOOL_CALL_STARTED.value,
        EventType.PERMISSION_REQUESTED.value,
        EventType.PERMISSION_RESOLVED.value,
        expected_tool_event.value,
        EventType.LLM_CALL_STARTED.value,
        EventType.LLM_CALL_FINISHED.value,
        EventType.AGENT_FINISHED.value,
    ]
