from collections.abc import Callable
from typing import Protocol

from devagent.agent import AgentEvent, AgentEventType, AgentRuntime, AgentRunResult
from devagent.event import InMemoryEventStore
from devagent.llm.mock_client import MockLLMClient
from devagent.tools.builtin import create_builtin_registry

from .models import AgentTask, TaskStatus
from .repository import InMemoryTaskRepository


class RuntimeLike(Protocol):
    def run(self, question: str) -> AgentRunResult:
        ...


RuntimeFactory = Callable[[AgentTask], RuntimeLike]


class TaskManager:
    def __init__(
        self,
        repository: InMemoryTaskRepository,
        runtime_factory: RuntimeFactory | None = None,
        event_store: InMemoryEventStore | None = None,
    ) -> None:
        self.repository = repository
        self._runtime_factory = runtime_factory or self._create_runtime
        self.event_store = event_store or InMemoryEventStore()

    def _create_runtime(self, task: AgentTask) -> AgentRuntime:
        client = MockLLMClient()
        tool_registry = create_builtin_registry()
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=tool_registry,
            max_steps=task.max_steps,
            max_tool_calls=task.max_tool_calls,
        )
        return runtime

    def create_task(
        self,
        *,
        question: str,
        workspace: str = ".",
        provider: str = "mock",
        model: str | None = None,
        base_url: str | None = None,
        max_steps: int = 10,
        max_tool_calls: int = 20,
    ) -> AgentTask:
        task = AgentTask(
            question=question,
            workspace=workspace,
            provider=provider,
            model=model,
            base_url=base_url,
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
        )
        return self.repository.create(task)

    def run_task(self, task_id: str) -> AgentTask:
        task: AgentTask = self.repository.get(task_id)
        if task.status in (TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.DONE):
            return task

        task = self.repository.update_status(task_id, TaskStatus.RUNNING)

        try:
            runtime = self._runtime_factory(task)
            result: AgentRunResult = runtime.run(task.question)
        except Exception as exc:
            self.event_store.append(
                task_id,
                AgentEvent(
                    type=AgentEventType.ERROR,
                    message=f"任务执行失败: {exc}",
                ),
            )
            return self.repository.update_status(
                task_id,
                TaskStatus.FAILED,
                error_message=f"任务执行失败: {exc}",
            )

        self.event_store.append_many(task_id, result.events)

        if result.success:
            return self.repository.update_status(task_id, TaskStatus.DONE)

        return self.repository.update_status(
            task_id,
            TaskStatus.FAILED,
            error_message=result.error_message or result.status.value,
        )

    def cancel_task(self, task_id: str) -> AgentTask:
        return self.repository.update_status(
            task_id=task_id, status=TaskStatus.CANCELLED
        )
