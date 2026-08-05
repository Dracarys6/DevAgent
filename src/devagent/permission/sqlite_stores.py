from __future__ import annotations

import json
import sqlite3

from devagent.event import redact_sensitive_values
from devagent.storage import SQLiteDatabase
from devagent.tools.models import RiskLevel

from .models import (
    InvalidPermissionTransitionError,
    PermissionDecision,
    PermissionPolicy,
    PermissionRequest,
    PermissionStatus,
)
from .policy_store import PermissionPolicyNotFoundError, fingerprint_arguments
from .request_store import PermissionRequestNotFoundError


class PermissionPersistenceError(RuntimeError):
    """权限数据无法可靠保存或恢复。"""


class SQLitePermissionRequestStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def create(self, request: PermissionRequest) -> PermissionRequest:
        arguments = redact_sensitive_values(request.tool_arguments)
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO permission_requests(
                        request_id, task_id, tool_call_id, tool_name,
                        tool_arguments_json, risk_level, reason, status,
                        decision, decision_reason, created_at, updated_at, resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.request_id,
                        request.task_id,
                        request.tool_call_id,
                        request.tool_name,
                        json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                        request.risk_level.value,
                        request.reason,
                        request.status.value,
                        request.decision.value if request.decision else None,
                        request.decision_reason,
                        request.created_at.isoformat(),
                        request.updated_at.isoformat(),
                        request.resolved_at.isoformat()
                        if request.resolved_at
                        else None,
                    ),
                )
        except sqlite3.Error as exc:
            raise PermissionPersistenceError("保存权限请求失败") from exc
        return self.get(request.request_id)

    def get(self, request_id: str) -> PermissionRequest:
        connection = self._database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM permission_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise PermissionPersistenceError("读取权限请求失败") from exc
        finally:
            connection.close()
        if row is None:
            raise PermissionRequestNotFoundError(f"权限请求不存在: {request_id}")
        return _request_from_row(row)

    def resolve(
        self,
        request_id: str,
        decision: PermissionDecision,
        decision_reason: str | None = None,
    ) -> PermissionRequest:
        try:
            with self._database.transaction(immediate=True) as connection:
                row = connection.execute(
                    "SELECT * FROM permission_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise PermissionRequestNotFoundError(
                        f"权限请求不存在: {request_id}"
                    )
                request = _request_from_row(row)
                request.resolve(decision, decision_reason)
                connection.execute(
                    """
                    UPDATE permission_requests
                    SET status = ?, decision = ?, decision_reason = ?,
                        updated_at = ?, resolved_at = ?
                    WHERE request_id = ?
                    """,
                    (
                        request.status.value,
                        request.decision.value,
                        request.decision_reason,
                        request.updated_at.isoformat(),
                        request.resolved_at.isoformat(),
                        request_id,
                    ),
                )
        except (PermissionRequestNotFoundError, InvalidPermissionTransitionError):
            raise
        except sqlite3.Error as exc:
            raise PermissionPersistenceError("处理权限请求失败") from exc
        return request

    def list(
        self,
        *,
        status: PermissionStatus | None = None,
    ) -> list[PermissionRequest]:
        connection = self._database.connect()
        try:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM permission_requests ORDER BY created_at, request_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM permission_requests
                    WHERE status = ? ORDER BY created_at, request_id
                    """,
                    (status.value,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise PermissionPersistenceError("读取权限请求失败") from exc
        finally:
            connection.close()
        return [_request_from_row(row) for row in rows]


class SQLitePermissionPolicyStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def create_policy(
        self,
        *,
        name: str,
        decision: PermissionDecision,
        tool_name: str | None = None,
        risk_levels: list[RiskLevel] | None = None,
        tool_arguments: dict | None = None,
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
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO permission_policies(
                        policy_id, name, tool_name, risk_levels_json, decision,
                        enabled, arguments_fingerprint, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        policy.policy_id,
                        policy.name,
                        policy.tool_name,
                        json.dumps([level.value for level in policy.risk_levels]),
                        policy.decision.value,
                        int(policy.enabled),
                        policy.arguments_fingerprint,
                        policy.reason,
                        policy.created_at.isoformat(),
                    ),
                )
        except sqlite3.Error as exc:
            raise PermissionPersistenceError("保存权限策略失败") from exc
        return policy

    def get_policy(self, policy_id: str) -> PermissionPolicy:
        connection = self._database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM permission_policies WHERE policy_id = ?",
                (policy_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise PermissionPolicyNotFoundError(f"权限策略不存在: {policy_id}")
        return _policy_from_row(row)

    def list_policies(self, *, enabled_only: bool = False) -> list[PermissionPolicy]:
        connection = self._database.connect()
        try:
            query = "SELECT * FROM permission_policies"
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY created_at, policy_id"
            rows = connection.execute(query).fetchall()
        finally:
            connection.close()
        return [_policy_from_row(row) for row in rows]

    def disable_policy(self, policy_id: str) -> PermissionPolicy:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE permission_policies SET enabled = 0 WHERE policy_id = ?",
                (policy_id,),
            )
            if cursor.rowcount == 0:
                raise PermissionPolicyNotFoundError(f"权限策略不存在: {policy_id}")
        return self.get_policy(policy_id)

    def match_policy(
        self,
        *,
        tool_name: str,
        risk_level: RiskLevel,
        tool_arguments: dict | None = None,
    ) -> PermissionPolicy | None:
        fingerprint = fingerprint_arguments(tool_arguments)
        for policy in reversed(self.list_policies(enabled_only=True)):
            if policy.tool_name and policy.tool_name != tool_name:
                continue
            if policy.risk_levels and risk_level not in policy.risk_levels:
                continue
            if (
                policy.arguments_fingerprint
                and policy.arguments_fingerprint != fingerprint
            ):
                continue
            return policy
        return None


def _request_from_row(row: sqlite3.Row) -> PermissionRequest:
    return PermissionRequest.model_validate(
        {
            "request_id": row["request_id"],
            "task_id": row["task_id"],
            "tool_call_id": row["tool_call_id"],
            "tool_name": row["tool_name"],
            "tool_arguments": json.loads(row["tool_arguments_json"]),
            "risk_level": row["risk_level"],
            "reason": row["reason"],
            "status": row["status"],
            "decision": row["decision"],
            "decision_reason": row["decision_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
        }
    )


def _policy_from_row(row: sqlite3.Row) -> PermissionPolicy:
    return PermissionPolicy.model_validate(
        {
            "policy_id": row["policy_id"],
            "name": row["name"],
            "tool_name": row["tool_name"],
            "risk_levels": json.loads(row["risk_levels_json"]),
            "decision": row["decision"],
            "enabled": bool(row["enabled"]),
            "arguments_fingerprint": row["arguments_fingerprint"],
            "reason": row["reason"],
            "created_at": row["created_at"],
        }
    )
