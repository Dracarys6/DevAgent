import pytest

from devagent.permission.models import PermissionDecision
from devagent.permission.policy_store import (
    InMemoryPermissionPolicyStore,
    PermissionPolicyNotFoundError,
    fingerprint_arguments,
)
from devagent.tools.models import RiskLevel


def test_create_policy_creates_enabled_policy():
    store = InMemoryPermissionPolicyStore()
    policy = store.create_policy(
        name="Test Policy",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    assert policy.enabled is True
    assert policy.decision == PermissionDecision.ALLOW
    assert policy.tool_name == "test_tool"
    assert policy.risk_levels == [RiskLevel.LOW, RiskLevel.MEDIUM]
    assert policy.arguments_fingerprint is not None
    assert policy.reason == "Test reason"


def test_fingerprint_arguments_is_stable_for_different_key_order():
    first = fingerprint_arguments({"cwd": ".", "command": ["pytest", "-q"]})
    second = fingerprint_arguments({"command": ["pytest", "-q"], "cwd": "."})

    assert first == second


def test_same_arguments_create_same_fingerprint():
    store = InMemoryPermissionPolicyStore()
    policy1 = store.create_policy(
        name="Test Policy1",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )
    policy2 = store.create_policy(
        name="Test Policy2",
        decision=PermissionDecision.DENY,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    assert policy1.arguments_fingerprint == policy2.arguments_fingerprint


def test_match_policy_with_same_tool_name():
    store = InMemoryPermissionPolicyStore()
    policy = store.create_policy(
        name="Test Policy1",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    matched_policy = store.match_policy(
        tool_name="test_tool",
        risk_level=RiskLevel.LOW,
        tool_arguments={"arg1": "value1"},
    )
    assert matched_policy is not None
    assert matched_policy.policy_id == policy.policy_id


def test_match_policy_without_same_tool_name():
    store = InMemoryPermissionPolicyStore()
    store.create_policy(
        name="Test Policy1",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    matched_policy = store.match_policy(
        tool_name="other_tool",
        risk_level=RiskLevel.LOW,
        tool_arguments={"arg1": "value1"},
    )
    assert matched_policy is None


def test_match_policy_with_different_risk_levels():
    store = InMemoryPermissionPolicyStore()
    store.create_policy(
        name="Test Policy1",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    matched_policy = store.match_policy(
        tool_name="test_tool",
        risk_level=RiskLevel.HIGH,
        tool_arguments={"arg1": "value1"},
    )
    assert matched_policy is None


def test_match_policy_with_different_tool_arguments():
    store = InMemoryPermissionPolicyStore()
    store.create_policy(
        name="Test Policy1",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    matched_policy = store.match_policy(
        tool_name="test_tool",
        risk_level=RiskLevel.LOW,
        tool_arguments={"arg1": "value2"},
    )
    assert matched_policy is None


def test_match_policy_with_disabled_policy():
    store = InMemoryPermissionPolicyStore()
    policy = store.create_policy(
        name="Test Policy1",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    store.disable_policy(policy.policy_id)

    matched_policy = store.match_policy(
        tool_name="test_tool",
        risk_level=RiskLevel.LOW,
        tool_arguments={"arg1": "value1"},
    )
    assert matched_policy is None


def test_deepcopy_on_get_policy():
    store = InMemoryPermissionPolicyStore()
    policy = store.create_policy(
        name="Test Policy",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    retrieved_policy = store.get_policy(policy.policy_id)
    retrieved_policy.name = "Modified Policy"

    original_policy = store.get_policy(policy.policy_id)
    assert original_policy.name == "Test Policy"


def test_deepcopy_on_list_policies():
    store = InMemoryPermissionPolicyStore()
    store.create_policy(
        name="Test Policy1",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )
    store.create_policy(
        name="Test Policy2",
        decision=PermissionDecision.DENY,
        tool_name="test_tool",
        risk_levels=[RiskLevel.HIGH],
        tool_arguments={"arg1": "value2"},
        reason="Test reason",
    )

    policies = store.list_policies()
    policies[0].name = "Modified Policy"

    original_policies = store.list_policies()
    assert original_policies[0].name == "Test Policy1"


def test_disable_policy_returns_copy_to_protect_internal_state():
    store = InMemoryPermissionPolicyStore()
    policy = store.create_policy(
        name="Test Policy",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW],
        tool_arguments={"arg1": "value1"},
    )

    disabled = store.disable_policy(policy.policy_id)
    disabled.enabled = True

    assert store.get_policy(policy.policy_id).enabled is False


def test_match_policy_returns_copy_to_protect_internal_state():
    store = InMemoryPermissionPolicyStore()
    policy = store.create_policy(
        name="Test Policy",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW],
        tool_arguments={"arg1": "value1"},
    )

    matched_policy = store.match_policy(
        tool_name="test_tool",
        risk_level=RiskLevel.LOW,
        tool_arguments={"arg1": "value1"},
    )
    assert matched_policy is not None
    matched_policy.enabled = False

    assert store.get_policy(policy.policy_id).enabled is True


def test_run_shell_policy_does_not_match_different_command():
    store = InMemoryPermissionPolicyStore()
    store.create_policy(
        name="Allow pytest",
        decision=PermissionDecision.ALLOW,
        tool_name="run_shell",
        risk_levels=[RiskLevel.HIGH],
        tool_arguments={"command": ["pytest", "-q"], "cwd": "."},
        reason="允许当前测试命令",
    )

    matched_policy = store.match_policy(
        tool_name="run_shell",
        risk_level=RiskLevel.HIGH,
        tool_arguments={"command": ["rm", "-rf", "/"], "cwd": "."},
    )

    assert matched_policy is None


def test_list_policies_can_filter_enabled_only():
    store = InMemoryPermissionPolicyStore()
    enabled = store.create_policy(
        name="Enabled Policy",
        decision=PermissionDecision.ALLOW,
        risk_levels=[RiskLevel.LOW],
    )
    store.create_policy(
        name="Disabled Policy",
        decision=PermissionDecision.DENY,
        risk_levels=[RiskLevel.HIGH],
        enabled=False,
    )

    policies = store.list_policies(enabled_only=True)

    assert [policy.policy_id for policy in policies] == [enabled.policy_id]


def test_match_the_newest_policy():
    store = InMemoryPermissionPolicyStore()
    store.create_policy(
        name="Test Policy1",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )
    policy2 = store.create_policy(
        name="Test Policy2",
        decision=PermissionDecision.DENY,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    matched_policy = store.match_policy(
        tool_name="test_tool",
        risk_level=RiskLevel.LOW,
        tool_arguments={"arg1": "value1"},
    )
    assert matched_policy is not None
    assert matched_policy.policy_id == policy2.policy_id


def test_get_policy_not_found():
    store = InMemoryPermissionPolicyStore()

    with pytest.raises(PermissionPolicyNotFoundError, match="权限策略不存在"):
        store.get_policy("non_existent_policy_id")


def test_create_and_get_policy():
    store = InMemoryPermissionPolicyStore()
    policy = store.create_policy(
        name="Test Policy2",
        decision=PermissionDecision.ALLOW,
        tool_name="test_tool",
        risk_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        tool_arguments={"arg1": "value1"},
        reason="Test reason",
    )

    retrieved_policy = store.get_policy(policy.policy_id)
    assert retrieved_policy == policy
