import pytest

from devagent.event import EventType, InMemoryEventBus, InMemorySequenceAllocator
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


def list_permission_events(bus: InMemoryEventBus):
    return bus.list_events("task_1")


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


def test_request_permission_publishes_permission_requested_event():
    bus = InMemoryEventBus()
    manager = InMemoryPermissionManager(
        event_bus=bus,
        sequence_allocator=InMemorySequenceAllocator(),
        session_id="session_1",
    )

    request = create_permission(manager)

    events = list_permission_events(bus)
    assert [event.event_type for event in events] == [EventType.PERMISSION_REQUESTED]
    assert events[0].request_id == request.request_id
    assert events[0].session_id == "session_1"
    assert events[0].tool_name == "run_shell"
    assert events[0].risk_level == RiskLevel.HIGH.value
    assert events[0].payload == {
        "tool_call_id": "tool_call_1",
        "reason": "run_shell 是高风险工具，需要审批",
        "tool_arguments": {"command": ["pytest", "-q"]},
    }


def test_resolve_publishes_permission_resolved_event():
    bus = InMemoryEventBus()
    manager = InMemoryPermissionManager(
        event_bus=bus,
        sequence_allocator=InMemorySequenceAllocator(),
        session_id="session_1",
    )
    request = create_permission(manager)

    resolved = manager.resolve(
        request.request_id,
        PermissionDecision.ALLOW,
        decision_reason="确认安全",
    )

    events = list_permission_events(bus)
    assert resolved.status == PermissionStatus.APPROVED
    assert [event.event_type for event in events] == [
        EventType.PERMISSION_REQUESTED,
        EventType.PERMISSION_RESOLVED,
    ]
    assert [event.sequence_id for event in events] == [1, 2]
    assert events[1].request_id == request.request_id
    assert events[1].decision == PermissionDecision.ALLOW.value
    assert events[1].status == PermissionStatus.APPROVED.value
    assert events[1].payload == {
        "tool_name": "run_shell",
        "tool_call_id": "tool_call_1",
        "decision_reason": "确认安全",
    }


def test_permission_event_payload_redacts_sensitive_arguments():
    bus = InMemoryEventBus()
    manager = InMemoryPermissionManager(event_bus=bus)

    manager.request_permission(
        tool_name="run_shell",
        risk_level=RiskLevel.HIGH,
        reason="需要审批",
        tool_arguments={
            "command": ["echo", "ok"],
            "api_key": "sk-test",
            "nested": {"token": "secret-token"},
        },
        task_id="task_1",
        tool_call_id="tool_call_1",
    )

    events = list_permission_events(bus)
    arguments = events[0].payload["tool_arguments"]
    assert arguments["api_key"] == "[REDACTED]"
    assert arguments["nested"]["token"] == "[REDACTED]"


def test_permission_event_bus_subscriber_error_does_not_fail_resolve():
    bus = InMemoryEventBus()
    manager = InMemoryPermissionManager(event_bus=bus)
    bus.subscribe("task_1", lambda event: 1 / 0)

    request = create_permission(manager)
    resolved = manager.resolve(request.request_id, PermissionDecision.DENY)

    events = list_permission_events(bus)
    assert request.status == PermissionStatus.PENDING
    assert resolved.status == PermissionStatus.DENIED
    assert [event.event_type for event in events] == [
        EventType.PERMISSION_REQUESTED,
        EventType.PERMISSION_RESOLVED,
    ]
