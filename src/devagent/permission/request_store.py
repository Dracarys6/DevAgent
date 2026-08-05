from copy import deepcopy
from typing import Protocol

from .models import PermissionDecision, PermissionRequest, PermissionStatus


class PermissionRequestNotFoundError(KeyError):
    """查询的权限请求不存在。"""


class PermissionRequestStore(Protocol):
    def create(self, request: PermissionRequest) -> PermissionRequest: ...

    def get(self, request_id: str) -> PermissionRequest: ...

    def resolve(
        self,
        request_id: str,
        decision: PermissionDecision,
        decision_reason: str | None = None,
    ) -> PermissionRequest: ...

    def list(
        self, *, status: PermissionStatus | None = None
    ) -> list[PermissionRequest]: ...


class InMemoryPermissionRequestStore:
    def __init__(self) -> None:
        self._requests: dict[str, PermissionRequest] = {}

    def create(self, request: PermissionRequest) -> PermissionRequest:
        self._requests[request.request_id] = deepcopy(request)
        return deepcopy(request)

    def get(self, request_id: str) -> PermissionRequest:
        try:
            return deepcopy(self._requests[request_id])
        except KeyError as exc:
            raise PermissionRequestNotFoundError(
                f"权限请求不存在: {request_id}"
            ) from exc

    def resolve(
        self,
        request_id: str,
        decision: PermissionDecision,
        decision_reason: str | None = None,
    ) -> PermissionRequest:
        try:
            request = self._requests[request_id]
        except KeyError as exc:
            raise PermissionRequestNotFoundError(
                f"权限请求不存在: {request_id}"
            ) from exc
        request.resolve(decision, decision_reason)
        return deepcopy(request)

    def list(
        self,
        *,
        status: PermissionStatus | None = None,
    ) -> list[PermissionRequest]:
        return [
            deepcopy(request)
            for request in self._requests.values()
            if status is None or request.status == status
        ]
