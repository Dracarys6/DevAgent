from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Protocol

from .models import BaseEvent

if TYPE_CHECKING:
    from devagent.agent.models import AgentEvent


class AgentRunEventStore(Protocol):
    """兼容 AgentRunResult.events 的摘要事件存储契约。"""

    def append(self, task_id: str, event: AgentEvent) -> None: ...

    def append_many(self, task_id: str, events: list[AgentEvent]) -> None: ...

    def list(self, task_id: str) -> list[AgentEvent]: ...

    def clear(self, task_id: str) -> None: ...


class InMemoryAgentRunEventStore:
    def __init__(self) -> None:
        self._events_by_task_id: dict[str, list[AgentEvent]] = {}

    def append(self, task_id: str, event: AgentEvent) -> None:
        self._events_by_task_id.setdefault(task_id, []).append(deepcopy(event))

    def append_many(self, task_id: str, events: list[AgentEvent]) -> None:
        self._events_by_task_id.setdefault(task_id, []).extend(deepcopy(events))

    def list(self, task_id: str) -> list[AgentEvent]:
        return deepcopy(self._events_by_task_id.get(task_id, []))

    def clear(self, task_id: str) -> None:
        self._events_by_task_id.pop(task_id, None)


# * 保留旧名称，避免已有 /events API 和导入在持久化 Trace 迁移时中断。
InMemoryEventStore = InMemoryAgentRunEventStore


class EventStoreError(RuntimeError):
    """结构化事件存储边界的基础异常。"""


class EventAlreadyExistsError(EventStoreError):
    pass


class EventPersistenceError(EventStoreError):
    pass


class EventStore(Protocol):
    def append(self, event: BaseEvent) -> None: ...

    def list(
        self,
        task_id: str,
        *,
        after_sequence_id: int | None = None,
    ) -> list[BaseEvent]: ...

    def clear(self, task_id: str) -> None: ...


class InMemoryStructuredEventStore:
    def __init__(self) -> None:
        self._events_by_task_id: dict[str, list[BaseEvent]] = {}
        self._event_ids: set[str] = set()

    def append(self, event: BaseEvent) -> None:
        events = self._events_by_task_id.setdefault(event.task_id, [])
        if event.event_id in self._event_ids or any(
            stored.sequence_id == event.sequence_id for stored in events
        ):
            raise EventAlreadyExistsError(
                f"事件已存在: {event.task_id}/{event.sequence_id}"
            )
        stored = deepcopy(event)
        events.append(stored)
        events.sort(key=lambda item: item.sequence_id)
        self._event_ids.add(stored.event_id)

    def list(
        self,
        task_id: str,
        *,
        after_sequence_id: int | None = None,
    ) -> list[BaseEvent]:
        return [
            deepcopy(event)
            for event in self._events_by_task_id.get(task_id, [])
            if after_sequence_id is None or event.sequence_id > after_sequence_id
        ]

    def clear(self, task_id: str) -> None:
        events = self._events_by_task_id.pop(task_id, [])
        self._event_ids.difference_update(event.event_id for event in events)
