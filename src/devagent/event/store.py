from copy import deepcopy

from devagent.agent import AgentEvent


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events_by_task_id: dict[str, list[AgentEvent]] = {}

    def append(self, task_id: str, event: AgentEvent) -> None:
        if task_id not in self._events_by_task_id:
            self._events_by_task_id[task_id] = []
        self._events_by_task_id[task_id].append(deepcopy(event))

    def append_many(self, task_id: str, events: list[AgentEvent]) -> None:
        if task_id not in self._events_by_task_id:
            self._events_by_task_id[task_id] = []
        self._events_by_task_id[task_id].extend(deepcopy(events))

    def list(self, task_id: str) -> list[AgentEvent]:
        return deepcopy(self._events_by_task_id.get(task_id, []))

    def clear(self, task_id: str) -> None:
        if task_id in self._events_by_task_id:
            del self._events_by_task_id[task_id]
