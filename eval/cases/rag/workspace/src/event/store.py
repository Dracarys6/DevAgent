class EventStore:
    def append(self, task_id: str, event: "AgentEvent") -> None:
        self.events_by_task.setdefault(task_id, []).append(event)

    def list_by_task(self, task_id: str) -> list["AgentEvent"]:
        return list(self.events_by_task.get(task_id, []))
