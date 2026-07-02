import pytest

from devagent.permission import (
    InMemoryPermissionManager,
    InvalidPermissionTransitionError,
    PermissionDecision,
    PermissionRequestNotFoundError,
    PermissionStatus,
    RiskLevel,
)


def create_permission(manager: InMemoryPermissionManager):
    return manager.request_permission(
        tool_name="run_shell",
        risk_level=RiskLevel.HIGH,
        reason="run_shell 是高风险工具，需要审批",
        tool_arguments={"command": ["pytest", "-q"]},
        task_id="task_1",
        tool_call_id="tool_call_1",
    )


def test_request_permission_creates_pending_request():
    manager = InMemoryPermissionManager()

    request = create_permission(manager)

    assert request.request_id
    assert request.status == PermissionStatus.PENDING
    assert request.tool_name == "run_shell"
    assert request.tool_arguments == {"command": ["pytest", "-q"]}
    assert request.risk_level == RiskLevel.HIGH
    assert request.reason == "run_shell 是高风险工具，需要审批"


def test_get_request_returns_created_request():
    manager = InMemoryPermissionManager()
    created = create_permission(manager)

    fetched = manager.get_request(created.request_id)

    assert fetched.request_id == created.request_id
    assert fetched.status == PermissionStatus.PENDING


def test_get_missing_request_raises_not_found():
    manager = InMemoryPermissionManager()

    with pytest.raises(PermissionRequestNotFoundError, match="权限请求不存在"):
        manager.get_request("missing-request")


def test_resolve_can_approve_request():
    manager = InMemoryPermissionManager()
    created = create_permission(manager)

    resolved = manager.resolve(
        created.request_id,
        PermissionDecision.ALLOW,
        decision_reason="确认安全",
    )

    assert resolved.status == PermissionStatus.APPROVED
    assert resolved.decision == PermissionDecision.ALLOW
    assert resolved.decision_reason == "确认安全"
    assert resolved.resolved_at is not None
    assert manager.check_request_status(created.request_id) == PermissionStatus.APPROVED


def test_resolve_can_deny_request():
    manager = InMemoryPermissionManager()
    created = create_permission(manager)

    resolved = manager.resolve(
        created.request_id,
        PermissionDecision.DENY,
        decision_reason="命令太危险",
    )

    assert resolved.status == PermissionStatus.DENIED
    assert resolved.decision == PermissionDecision.DENY
    assert resolved.decision_reason == "命令太危险"


def test_resolve_missing_request_raises_not_found():
    manager = InMemoryPermissionManager()

    with pytest.raises(PermissionRequestNotFoundError, match="权限请求不存在"):
        manager.resolve("missing-request", PermissionDecision.ALLOW)


def test_resolve_same_request_twice_raises_transition_error():
    manager = InMemoryPermissionManager()
    created = create_permission(manager)
    manager.resolve(created.request_id, PermissionDecision.ALLOW)

    with pytest.raises(InvalidPermissionTransitionError, match="不能重复审批"):
        manager.resolve(created.request_id, PermissionDecision.DENY)


def test_list_pending_only_returns_pending_requests():
    manager = InMemoryPermissionManager()
    first = create_permission(manager)
    second = create_permission(manager)
    manager.resolve(first.request_id, PermissionDecision.ALLOW)

    pending = manager.list_pending()

    assert [request.request_id for request in pending] == [second.request_id]


def test_list_all_returns_all_requests():
    manager = InMemoryPermissionManager()
    first = create_permission(manager)
    second = create_permission(manager)

    requests = manager.list_all()

    assert [request.request_id for request in requests] == [
        first.request_id,
        second.request_id,
    ]


def test_request_permission_returns_copy_to_protect_internal_state():
    manager = InMemoryPermissionManager()
    created = create_permission(manager)

    created.status = PermissionStatus.APPROVED

    assert manager.get_request(created.request_id).status == PermissionStatus.PENDING


def test_get_request_returns_copy_to_protect_internal_state():
    manager = InMemoryPermissionManager()
    created = create_permission(manager)

    fetched = manager.get_request(created.request_id)
    fetched.status = PermissionStatus.APPROVED

    assert manager.get_request(created.request_id).status == PermissionStatus.PENDING


def test_list_pending_returns_copies_to_protect_internal_state():
    manager = InMemoryPermissionManager()
    created = create_permission(manager)

    pending = manager.list_pending()
    pending[0].status = PermissionStatus.APPROVED

    assert manager.get_request(created.request_id).status == PermissionStatus.PENDING


def test_check_request_status_returns_current_status():
    manager = InMemoryPermissionManager()
    created = create_permission(manager)

    assert manager.check_request_status(created.request_id) == PermissionStatus.PENDING

    manager.resolve(created.request_id, PermissionDecision.ALLOW)

    assert manager.check_request_status(created.request_id) == PermissionStatus.APPROVED
