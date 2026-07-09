import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from devagent.agent import AgentEvent, AgentEventType, AgentRuntime, AgentRunResult
from devagent.event import InMemoryEventStore, InMemoryEventBus
from devagent.llm import (
    LLMClient,
    MockLLMClient,
    OpenAICompatibleLLMClient,
    tool_registry_to_openai_tools,
)
from devagent.tools import ReadFileTool, RiskLevel, SearchCodeTool, ToolRegistry
from devagent.tools.builtin import create_builtin_registry

from .models import AgentTask, TaskStatus
from .repository import InMemoryTaskRepository


class RuntimeLike(Protocol):
    def run(self, question: str) -> AgentRunResult: ...


def create_low_risk_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(SearchCodeTool())
    return registry


class LLMClientFactory:
    def create_client(self, task: AgentTask, tool_registry: ToolRegistry) -> LLMClient:
        if task.provider == "mock":
            return MockLLMClient()

        if task.provider == "real":
            return self._create_real_client(task, tool_registry)

        raise ValueError(f"不支持的 LLM provider: {task.provider}")

    def _create_real_client(
        self,
        task: AgentTask,
        tool_registry: ToolRegistry,
    ) -> LLMClient:
        load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
        api_key = os.getenv("DEVAGENT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        model = task.model or os.getenv("DEVAGENT_LLM_MODEL")
        base_url = task.base_url or os.getenv("DEVAGENT_LLM_BASE_URL")

        if not api_key:
            raise ValueError("缺少 LLM API Key，请设置 DEVAGENT_LLM_API_KEY")
        if not model:
            raise ValueError(
                "缺少 LLM 模型名称，请在请求中传入 model 或设置 DEVAGENT_LLM_MODEL"
            )

        return OpenAICompatibleLLMClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            tools=tool_registry_to_openai_tools(
                registry=tool_registry,
                allowed_risk_levels={RiskLevel.LOW},
            ),
        )


RuntimeFactory = Callable[[AgentTask], RuntimeLike]


class TaskManager:
    def __init__(
        self,
        repository: InMemoryTaskRepository,
        runtime_factory: RuntimeFactory | None = None,
        llm_client_factory: LLMClientFactory | None = None,
        event_store: InMemoryEventStore | None = None,
        event_bus: InMemoryEventBus | None = None,
    ) -> None:
        self.repository = repository
        self._runtime_factory = runtime_factory or self._create_runtime
        self.llm_client_factory = llm_client_factory or LLMClientFactory()
        self.event_store = event_store or InMemoryEventStore()
        self.event_bus = event_bus or InMemoryEventBus()

    def _create_runtime(self, task: AgentTask) -> AgentRuntime:
        tool_registry = self._create_tool_registry(task)
        client = self.llm_client_factory.create_client(task, tool_registry)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=tool_registry,
            max_steps=task.max_steps,
            max_tool_calls=task.max_tool_calls,
            event_bus=self.event_bus,
            task_id=task.task_id,
        )
        return runtime

    def _create_tool_registry(self, task: AgentTask) -> ToolRegistry:
        if task.provider == "real":
            return create_low_risk_registry()
        return create_builtin_registry()

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
        task = self.repository.get(task_id)
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
