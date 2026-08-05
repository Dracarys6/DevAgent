import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from devagent.agent import (
    AgentEvent,
    AgentEventType,
    AgentRunResult,
    AgentRunStatus,
    AgentRuntime,
)
from devagent.event import (
    AgentRunEventStore,
    InMemoryEventBus,
    InMemoryEventStore,
    InMemorySequenceAllocator,
    SequenceAllocator,
)
from devagent.llm import (
    LLMClient,
    MockLLMClient,
    create_openai_llm_client,
    tool_registry_to_openai_tools,
)
from devagent.permission import (
    InMemoryPermissionManager,
    InMemoryPermissionPolicyStore,
)
from devagent.tools import (
    ReadFileTool,
    SearchCodeTool,
    ToolExecutor,
    ToolRegistry,
)
from devagent.tools.builtin import create_builtin_registry
from devagent.tools.knowledge_tools import KnowledgeRetriever, knowledge_retrieve

from .models import AgentTask, InvalidTaskTransitionError, TaskStatus
from .repository import TaskRepository


class RuntimeLike(Protocol):
    def run(self, question: str) -> AgentRunResult: ...

    def resume(self, permission_request_id: str) -> AgentRunResult: ...


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
        api_mode = os.getenv("DEVAGENT_LLM_API_MODE", "chat_completions")
        reasoning_effort = os.getenv("DEVAGENT_LLM_REASONING_EFFORT") or None

        if not api_key:
            raise ValueError("缺少 LLM API Key，请设置 DEVAGENT_LLM_API_KEY")
        if not model:
            raise ValueError(
                "缺少 LLM 模型名称，请在请求中传入 model 或设置 DEVAGENT_LLM_MODEL"
            )

        return create_openai_llm_client(
            api_key=api_key,
            model=model,
            base_url=base_url,
            api_mode=api_mode,
            reasoning_effort=reasoning_effort,
            tools=tool_registry_to_openai_tools(registry=tool_registry),
        )


RuntimeFactory = Callable[[AgentTask], RuntimeLike]


class TaskManager:
    def __init__(
        self,
        repository: TaskRepository,
        runtime_factory: RuntimeFactory | None = None,
        llm_client_factory: LLMClientFactory | None = None,
        event_store: AgentRunEventStore | None = None,
        event_bus: InMemoryEventBus | None = None,
        permission_manager: InMemoryPermissionManager | None = None,
        policy_store: InMemoryPermissionPolicyStore | None = None,
        sequence_allocator: SequenceAllocator | None = None,
        knowledge_retriever: KnowledgeRetriever = knowledge_retrieve,
    ) -> None:
        self.repository = repository
        self._runtime_factory = runtime_factory or self._create_runtime
        self.llm_client_factory = llm_client_factory or LLMClientFactory()
        self.event_store = event_store or InMemoryEventStore()
        self.event_bus = event_bus or InMemoryEventBus()
        self.sequence_allocator = sequence_allocator or InMemorySequenceAllocator()
        self.permission_manager = permission_manager or InMemoryPermissionManager(
            event_bus=self.event_bus,
            sequence_allocator=self.sequence_allocator,
        )
        self.policy_store = policy_store or InMemoryPermissionPolicyStore()
        self._knowledge_retriever = knowledge_retriever
        self._suspended_runtimes: dict[str, RuntimeLike] = {}

    def _create_runtime(self, task: AgentTask) -> AgentRuntime:
        tool_registry = self._create_tool_registry(task)
        client = self.llm_client_factory.create_client(task, tool_registry)
        tool_executor = ToolExecutor(
            registry=tool_registry,
            permission_manager=self.permission_manager,
            policy_store=self.policy_store,
        )
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            max_steps=task.max_steps,
            max_tool_calls=task.max_tool_calls,
            event_bus=self.event_bus,
            sequence_allocator=self.sequence_allocator,
            task_id=task.task_id,
            workspace=task.workspace,
        )
        return runtime

    def _create_tool_registry(self, task: AgentTask) -> ToolRegistry:
        return create_builtin_registry(
            knowledge_retriever=self._knowledge_retriever,
        )

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
        # ! Runtime 工厂和运行循环是任务状态机的故障边界。
        except Exception as exc:  # noqa: BLE001
            return self._fail_task(task_id, exc)

        return self._apply_runtime_result(task_id, runtime, result)

    def resume_task(self, permission_request_id: str) -> AgentTask:
        """恢复一个已审批且处于 WAITING_PERMISSION 的 Agent 任务。"""
        permission_request = self.permission_manager.get_request(permission_request_id)
        if permission_request.task_id is None:
            raise ValueError("权限请求没有关联 Agent 任务")
        task_id = permission_request.task_id
        task = self.repository.get(task_id)
        if task.status != TaskStatus.WAITING_PERMISSION:
            raise InvalidTaskTransitionError(
                f"任务不在等待权限状态: {task.status.value}"
            )
        try:
            runtime = self._suspended_runtimes[task_id]
        except KeyError as exc:
            raise RuntimeError("等待权限的 AgentRuntime 不存在") from exc

        self.repository.update_status(task_id, TaskStatus.RUNNING)
        try:
            result = runtime.resume(permission_request_id)
        # ! 恢复路径必须把任意运行时故障收敛为 FAILED 并清理暂停态。
        except Exception as exc:  # noqa: BLE001
            self._suspended_runtimes.pop(task_id, None)
            return self._fail_task(task_id, exc)
        return self._apply_runtime_result(task_id, runtime, result)

    def can_resume_permission(self, permission_request_id: str) -> bool:
        """判断权限请求是否对应当前进程中暂停的 Agent 工作流。"""
        request = self.permission_manager.get_request(permission_request_id)
        if request.task_id is None or request.task_id not in self._suspended_runtimes:
            return False
        try:
            task = self.repository.get(request.task_id)
        except KeyError:
            return False
        runtime = self._suspended_runtimes[request.task_id]
        return (
            task.status == TaskStatus.WAITING_PERMISSION
            and getattr(runtime, "pending_permission_request_id", None)
            == permission_request_id
        )

    def _apply_runtime_result(
        self,
        task_id: str,
        runtime: RuntimeLike,
        result: AgentRunResult,
    ) -> AgentTask:
        self.event_store.append_many(task_id, result.events)

        if result.status == AgentRunStatus.WAITING_PERMISSION:
            if result.permission_request_id is None:
                return self._fail_task(
                    task_id,
                    RuntimeError("等待权限结果缺少 permission_request_id"),
                )
            self._suspended_runtimes[task_id] = runtime
            return self.repository.update_status(
                task_id,
                TaskStatus.WAITING_PERMISSION,
            )

        self._suspended_runtimes.pop(task_id, None)
        if result.success:
            return self.repository.update_status(task_id, TaskStatus.DONE)
        return self.repository.update_status(
            task_id,
            TaskStatus.FAILED,
            error_message=result.error_message or result.status.value,
        )

    def _fail_task(self, task_id: str, exc: Exception) -> AgentTask:
        message = f"任务执行失败: {exc}"
        self.event_store.append(
            task_id,
            AgentEvent(
                type=AgentEventType.ERROR,
                message=message,
            ),
        )
        return self.repository.update_status(
            task_id,
            TaskStatus.FAILED,
            error_message=message,
        )

    def cancel_task(self, task_id: str) -> AgentTask:
        return self.repository.update_status(
            task_id=task_id, status=TaskStatus.CANCELLED
        )
