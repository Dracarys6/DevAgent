class TaskManager:
    def cancel_task(self, task_id: str) -> None:
        task = self.require_task(task_id)
        task.cancellation_event.set()
        task.status = "cancelled"
