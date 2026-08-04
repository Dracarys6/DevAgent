from datetime import UTC

import pytest

from devagent.permission import RiskLevel as PermissionRiskLevel
from devagent.permission.models import (
    InvalidPermissionTransitionError,
    PermissionDecision,
    PermissionPolicy,
    PermissionRequest,
    PermissionStatus,
)
from devagent.tools.models import RiskLevel as ToolRiskLevel


def create_permission_request() -> PermissionRequest:
    return PermissionRequest(
        task_id="task_1",
        tool_call_id="tool_call_1",
        tool_name="run_shell",
        tool_arguments={"command": ["pytest", "-q"]},
        risk_level=PermissionRiskLevel.HIGH,
        reason="run_shell 是高风险工具，需要用户审批",
    )


def test_permission_risk_level_reuses_tool_risk_level():
    assert PermissionRiskLevel is ToolRiskLevel


def test_permission_request_defaults():
    request = create_permission_request()

    assert request.request_id
    assert request.status == PermissionStatus.PENDING
    assert request.decision is None
    assert request.created_at.tzinfo == UTC
    assert request.updated_at.tzinfo == UTC
    assert request.resolved_at is None


def test_permission_request_can_approve():
    request = create_permission_request()

    request.resolve(PermissionDecision.ALLOW, "确认安全")

    assert request.status == PermissionStatus.APPROVED
    assert request.decision == PermissionDecision.ALLOW
    assert request.decision_reason == "确认安全"
    assert request.resolved_at is not None
    assert request.updated_at >= request.created_at


def test_permission_request_can_deny():
    request = create_permission_request()

    request.resolve(PermissionDecision.DENY, "命令太危险")

    assert request.status == PermissionStatus.DENIED
    assert request.decision == PermissionDecision.DENY
    assert request.decision_reason == "命令太危险"
    assert request.resolved_at is not None


def test_permission_request_cannot_be_resolved_twice():
    request = create_permission_request()
    request.resolve(PermissionDecision.ALLOW, "确认安全")

    with pytest.raises(InvalidPermissionTransitionError, match="不能重复审批"):
        request.resolve(PermissionDecision.DENY, "重复决策")


def test_permission_request_rejects_invalid_decision_value():
    request = create_permission_request()

    with pytest.raises(ValueError, match="BAD"):
        request.resolve("BAD")  # type: ignore[arg-type]


def test_permission_request_json_serialization():
    request = create_permission_request()

    json_data = request.model_dump(mode="json")

    assert json_data["status"] == "PENDING"
    assert json_data["risk_level"] == "HIGH"
    assert json_data["tool_arguments"] == {"command": ["pytest", "-q"]}
    assert isinstance(json_data["created_at"], str)


def test_permission_policy_defaults_and_json_serialization():
    policy = PermissionPolicy(
        name="允许低风险工具",
        decision=PermissionDecision.ALLOW,
        risk_levels=[PermissionRiskLevel.LOW],
        arguments_fingerprint="fingerprint-1",
        reason="低风险只读操作",
    )

    json_data = policy.model_dump(mode="json")

    assert policy.policy_id
    assert policy.enabled is True
    assert policy.tool_name is None
    assert policy.arguments_fingerprint == "fingerprint-1"
    assert policy.reason == "低风险只读操作"
    assert json_data["risk_levels"] == ["LOW"]
    assert json_data["decision"] == "ALLOW"
    assert json_data["arguments_fingerprint"] == "fingerprint-1"
    assert json_data["reason"] == "低风险只读操作"
    assert isinstance(json_data["created_at"], str)
