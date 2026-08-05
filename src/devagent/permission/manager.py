from typing import Any

from devagent.event import (
    BaseEvent,
    EventBusDeliveryError,
    InMemoryEventBus,
    InMemorySequenceAllocator,
    PermissionRequested,
    PermissionResolved,
    SequenceAllocator,
)
from devagent.tools.models import RiskLevel

from .models import PermissionDecision, PermissionRequest, PermissionStatus
from .request_store import (
    InMemoryPermissionRequestStore,
    PermissionRequestStore,
)


class InMemoryPermissionManager:
    """内存中的权限管理器"""

    def __init__(
        self,
        event_bus: InMemoryEventBus | None = None,
        sequence_allocator: SequenceAllocator | None = None,
        session_id: str | None = None,
        request_store: PermissionRequestStore | None = None,
    ) -> None:
        self.request_store = request_store or InMemoryPermissionRequestStore()
        self.event_bus = event_bus
        self.sequence_allocator = sequence_allocator or InMemorySequenceAllocator()
        self.session_id = session_id

    def request_permission(
        self,
        *,
        tool_name: str,
        risk_level: RiskLevel,
        reason: str,
        tool_arguments: dict[str, Any] | None = None,
        task_id: str | None = None,
        tool_call_id: str | None = None,
        event_bus: InMemoryEventBus | None = None,
        sequence_allocator: SequenceAllocator | None = None,
        session_id: str | None = None,
    ) -> PermissionRequest:
        """创建并保存权限请求，然后发布请求事件。"""
        request = PermissionRequest(
            task_id=task_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
            risk_level=risk_level,
            reason=reason,
        )
        request = self.request_store.create(request)
        self._publish_event(
            self._build_permission_requested_event(
                request,
                event_bus=event_bus,
                sequence_allocator=sequence_allocator,
                session_id=session_id,
            )
        )
        return request

    def get_request(self, request_id: str) -> PermissionRequest:
        """返回权限请求的深拷贝，避免外部修改内部状态。"""
        return self.request_store.get(request_id)

    def resolve(
        self,
        request_id: str,
        decision: PermissionDecision,
        decision_reason: str | None = None,
        event_bus: InMemoryEventBus | None = None,
        sequence_allocator: SequenceAllocator | None = None,
        session_id: str | None = None,
    ) -> PermissionRequest:
        """解决权限请求并发布处理结果事件。"""
        request = self.request_store.resolve(request_id, decision, decision_reason)
        self._publish_event(
            self._build_permission_resolved_event(
                request,
                event_bus=event_bus,
                sequence_allocator=sequence_allocator,
                session_id=session_id,
            )
        )
        return request

    def list_pending(self) -> list[PermissionRequest]:
        """列出所有待处理的权限请求。"""
        return self.request_store.list(status=PermissionStatus.PENDING)

    def list_all(self) -> list[PermissionRequest]:
        return self.request_store.list()

    def check_request_status(self, request_id: str) -> PermissionStatus:
        request = self.get_request(request_id)
        return request.status

    def _publish_event(
        self,
        event: BaseEvent | None,
    ) -> None:
        if event is None:
            return
        event_bus = self.event_bus
        if event_bus is None:
            return
        try:
            event_bus.publish(event)
        except EventBusDeliveryError:
            return

    def _build_permission_requested_event(
        self,
        request: PermissionRequest,
        *,
        event_bus: InMemoryEventBus | None = None,
        sequence_allocator: SequenceAllocator | None = None,
        session_id: str | None = None,
    ) -> PermissionRequested | None:
        if request.task_id is None:
            return None
        effective_event_bus = event_bus or self.event_bus
        if effective_event_bus is None:
            return None
        self.event_bus = effective_event_bus
        effective_allocator = sequence_allocator or self.sequence_allocator
        self.sequence_allocator = effective_allocator
        if session_id is not None:
            self.session_id = session_id
        return PermissionRequested(
            task_id=request.task_id,
            session_id=session_id if session_id is not None else self.session_id,
            sequence_id=effective_allocator.next(request.task_id),
            message="权限请求已创建",
            request_id=request.request_id,
            tool_name=request.tool_name,
            risk_level=request.risk_level.value,
            payload={
                "tool_call_id": request.tool_call_id,
                "reason": request.reason,
                "tool_arguments": request.tool_arguments,
            },
        )

    def _build_permission_resolved_event(
        self,
        request: PermissionRequest,
        *,
        event_bus: InMemoryEventBus | None = None,
        sequence_allocator: SequenceAllocator | None = None,
        session_id: str | None = None,
    ) -> PermissionResolved | None:
        if request.task_id is None or request.decision is None:
            return None
        effective_event_bus = event_bus or self.event_bus
        if effective_event_bus is None:
            return None
        self.event_bus = effective_event_bus
        effective_allocator = sequence_allocator or self.sequence_allocator
        self.sequence_allocator = effective_allocator
        if session_id is not None:
            self.session_id = session_id
        return PermissionResolved(
            task_id=request.task_id,
            session_id=session_id if session_id is not None else self.session_id,
            sequence_id=effective_allocator.next(request.task_id),
            message="权限请求已处理",
            request_id=request.request_id,
            decision=request.decision.value,
            status=request.status.value,
            payload={
                "tool_name": request.tool_name,
                "tool_call_id": request.tool_call_id,
                "decision_reason": request.decision_reason,
            },
        )
