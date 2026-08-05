from pathlib import Path

import pytest

from devagent.permission import (
    InMemoryPermissionManager,
    InvalidPermissionTransitionError,
    PermissionDecision,
    PermissionRequest,
    PermissionStatus,
    RiskLevel,
    SQLitePermissionPolicyStore,
    SQLitePermissionRequestStore,
)
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import AgentTask, SQLiteTaskRepository


def make_database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "permissions.db"))
    database.initialize()
    SQLiteTaskRepository(database).create(
        AgentTask(task_id="task-1", question="permission persistence")
    )
    return database


def test_permission_request_survives_restart_and_resolves(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    manager = InMemoryPermissionManager(
        request_store=SQLitePermissionRequestStore(database)
    )
    request = manager.request_permission(
        task_id="task-1",
        tool_call_id="call-1",
        tool_name="run_shell",
        risk_level=RiskLevel.HIGH,
        reason="needs approval",
    )

    reopened = InMemoryPermissionManager(
        request_store=SQLitePermissionRequestStore(database)
    )
    assert reopened.list_pending() == [request]
    resolved = reopened.resolve(request.request_id, PermissionDecision.ALLOW)

    assert resolved.status == PermissionStatus.APPROVED
    assert reopened.list_pending() == []
    with pytest.raises(InvalidPermissionTransitionError):
        reopened.resolve(request.request_id, PermissionDecision.DENY)


def test_permission_request_redacts_sensitive_arguments(tmp_path: Path) -> None:
    store = SQLitePermissionRequestStore(make_database(tmp_path))
    created = store.create(
        PermissionRequest(
            task_id="task-1",
            tool_name="request",
            tool_arguments={"token": "secret", "path": "README.md"},
            risk_level=RiskLevel.HIGH,
            reason="network",
        )
    )

    assert store.get(created.request_id).tool_arguments == {
        "token": "[REDACTED]",
        "path": "README.md",
    }


def test_permission_policy_survives_restart_and_matches(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    store = SQLitePermissionPolicyStore(database)
    policy = store.create_policy(
        name="deny exact shell",
        decision=PermissionDecision.DENY,
        tool_name="run_shell",
        risk_levels=[RiskLevel.HIGH],
        tool_arguments={"command": ["rm", "artifact"]},
    )

    reopened = SQLitePermissionPolicyStore(database)
    matched = reopened.match_policy(
        tool_name="run_shell",
        risk_level=RiskLevel.HIGH,
        tool_arguments={"command": ["rm", "artifact"]},
    )

    assert matched == policy
    assert reopened.disable_policy(policy.policy_id).enabled is False
    assert (
        reopened.match_policy(
            tool_name="run_shell",
            risk_level=RiskLevel.HIGH,
            tool_arguments={"command": ["rm", "artifact"]},
        )
        is None
    )
