from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from devagent.tools.models import RiskLevel


class PermissionDecision(str, Enum):
    """权限决策"""

    ALLOW = "ALLOW"
    DENY = "DENY"


class PermissionStatus(str, Enum):
    """权限状态"""

    PENDING = "PENDING"  # 等待用户处理
    APPROVED = "APPROVED"  # 用户已批准
    DENIED = "DENIED"  # 用户已拒绝
    CANCELLED = "CANCELLED"  # 任务已取消
    EXPIRED = "EXPIRED"  # 请求过期


class InvalidPermissionTransitionError(ValueError):
    pass


class PermissionRequest(BaseModel):
    """权限请求"""

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str | None = None
    tool_call_id: str | None = None
    tool_name: str
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel
    reason: str
    status: PermissionStatus = PermissionStatus.PENDING
    decision: PermissionDecision | None = None
    decision_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None

    def resolve(
        self,
        decision: PermissionDecision,
        decision_reason: str | None = None,
    ) -> None:
        decision = PermissionDecision(decision)

        if self.status != PermissionStatus.PENDING:
            raise InvalidPermissionTransitionError(
                f"权限请求已处理，不能重复审批: {self.status.value}"
            )

        now = datetime.now(timezone.utc)
        if decision == PermissionDecision.ALLOW:
            self.status = PermissionStatus.APPROVED
        elif decision == PermissionDecision.DENY:
            self.status = PermissionStatus.DENIED

        self.decision = decision
        self.decision_reason = decision_reason
        self.updated_at = now
        self.resolved_at = now


class PermissionPolicy(BaseModel):
    """权限策略"""

    policy_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    tool_name: str | None = None  # 策略适用的工具
    risk_levels: list[RiskLevel] = Field(default_factory=list)  # 策略适用的风险等级
    decision: PermissionDecision  # 匹配后允许还是拒绝
    enabled: bool = True  # 策略是否启用
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
