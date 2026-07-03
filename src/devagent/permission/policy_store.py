import json
from copy import deepcopy
from hashlib import sha256
from typing import Any

from devagent.tools.models import RiskLevel

from .models import PermissionDecision, PermissionPolicy


class PermissionPolicyNotFoundError(KeyError):
    pass


def fingerprint_arguments(tool_arguments: dict[str, Any] | None) -> str | None:
    if tool_arguments is None:
        return None

    arguments_str = json.dumps(
        tool_arguments,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(arguments_str.encode()).hexdigest()


class InMemoryPermissionPolicyStore:
    def __init__(self) -> None:
        self._policies: dict[str, PermissionPolicy] = {}

    def create_policy(
        self,
        *,
        name: str,
        decision: PermissionDecision,
        tool_name: str | None = None,
        risk_levels: list[RiskLevel] | None = None,
        tool_arguments: dict[str, Any] | None = None,
        reason: str | None = None,
        enabled: bool = True,
    ) -> PermissionPolicy:
        policy = PermissionPolicy(
            name=name,
            decision=decision,
            tool_name=tool_name,
            risk_levels=risk_levels or [],
            arguments_fingerprint=fingerprint_arguments(tool_arguments),
            reason=reason,
            enabled=enabled,
        )
        self._policies[policy.policy_id] = deepcopy(policy)
        return deepcopy(policy)

    def get_policy(self, policy_id: str) -> PermissionPolicy:
        if policy_id not in self._policies:
            raise PermissionPolicyNotFoundError(f"权限策略不存在: {policy_id}")
        return deepcopy(self._policies[policy_id])

    def _get_stored_policy(self, policy_id: str) -> PermissionPolicy:
        if policy_id not in self._policies:
            raise PermissionPolicyNotFoundError(f"权限策略不存在: {policy_id}")
        return self._policies[policy_id]

    def list_policies(self, *, enabled_only: bool = False) -> list[PermissionPolicy]:
        return [
            deepcopy(policy)
            for policy in self._policies.values()
            if not enabled_only or policy.enabled
        ]

    def disable_policy(self, policy_id: str) -> PermissionPolicy:
        policy = self._get_stored_policy(policy_id)
        policy.enabled = False
        return deepcopy(policy)

    def match_policy(
        self,
        *,
        tool_name: str,
        risk_level: RiskLevel,
        tool_arguments: dict[str, Any] | None = None,
    ) -> PermissionPolicy | None:
        """匹配权限策略"""
        arguments_fingerprint = fingerprint_arguments(tool_arguments)
        for policy in reversed(self._policies.values()):
            if not policy.enabled:
                continue
            if policy.tool_name and policy.tool_name != tool_name:
                continue
            if policy.risk_levels and risk_level not in policy.risk_levels:
                continue
            if (
                policy.arguments_fingerprint
                and policy.arguments_fingerprint != arguments_fingerprint
            ):
                continue
            return deepcopy(policy)
        return None
