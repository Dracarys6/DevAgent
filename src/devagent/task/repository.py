from copy import deepcopy

from devagent.task.models import AgentTask, TaskStatus


class TaskNotFoundError(KeyError):
    pass


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, AgentTask] = {}

    def create(self, task: AgentTask) -> AgentTask:
        self._tasks[task.task_id] = deepcopy(task)
        return deepcopy(task)

    def get(self, task_id: str) -> AgentTask:
        try:
            task = self._tasks[task_id]
        except KeyError as exc:
            raise TaskNotFoundError(f"任务不存在: {task_id}") from exc
        return deepcopy(task)

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        error_message: str | None = None,
    ) -> AgentTask:
        try:
            task = self._tasks[task_id]
        except KeyError as exc:
            raise TaskNotFoundError(f"任务不存在: {task_id}") from exc
        task.transition_to(status, error_message=error_message)
        return deepcopy(task)

    def list(self) -> list[AgentTask]:
        return [deepcopy(task) for task in self._tasks.values()]
