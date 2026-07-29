class TraceService:
    def build_trace(self, task_id: str) -> "TaskTrace":
        """Build an ordered trace from every event belonging to task_id."""
        events = self.event_store.list_by_task(task_id)
        return TaskTrace(task_id=task_id, events=sorted(events, key=lambda item: item.sequence_id))
