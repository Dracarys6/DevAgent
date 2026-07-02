from copy import deepcopy
from typing import Any

from devagent.tools.models import RiskLevel

from .models import PermissionDecision, PermissionRequest, PermissionStatus


class PermissionRequestNotFoundError(KeyError):
    # 权限请求未找到
    pass


class InMemoryPermissionManager:
    """内存中的权限管理器"""

    def __init__(self):
        self._requests: dict[str, PermissionRequest] = {}

    def request_permission(
        self,
        *,
        tool_name: str,
        risk_level: RiskLevel,
        reason: str,
        tool_arguments: dict[str, Any] | None = None,
        task_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> PermissionRequest:
        # 创建一次权限请求
        request = PermissionRequest(
            task_id=task_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
            risk_level=risk_level,
            reason=reason,
        )
        self._requests[request.request_id] = deepcopy(request)
        return deepcopy(request)

    def get_request(self, request_id: str) -> PermissionRequest:
        # 创建一次权限请求
        if request_id not in self._requests:
            raise PermissionRequestNotFoundError(f"权限请求不存在: {request_id}")
        return deepcopy(self._requests[request_id])

    def _get_stored_request(self, request_id: str) -> PermissionRequest:
        # 获取存储的权限请求对象（非深拷贝）
        if request_id not in self._requests:
            raise PermissionRequestNotFoundError(f"权限请求不存在: {request_id}")
        return self._requests[request_id]

    def resolve(
        self,
        request_id: str,
        decision: PermissionDecision,
        decision_reason: str | None = None,
    ) -> PermissionRequest:
        # 批准或拒绝权限请求
        request = self._get_stored_request(request_id)
        request.resolve(decision, decision_reason)
        return deepcopy(request)

    def list_pending(self) -> list[PermissionRequest]:
        # 列出所有待处理
        return [
            deepcopy(r)
            for r in self._requests.values()
            if r.status == PermissionStatus.PENDING
        ]

    def list_all(self) -> list[PermissionRequest]:
        return [deepcopy(r) for r in self._requests.values()]

    def check_request_status(self, request_id: str) -> PermissionStatus:
        request = self.get_request(request_id)
        return request.status
