import pytest
from pydantic import BaseModel

from devagent.agent import (
    AgentEvent,
    AgentEventType,
    AgentRunResult,
    AgentRunStatus,
    AgentRuntime,
)
from devagent.event import InMemoryEventBus, InMemorySequenceAllocator
from devagent.llm import LLMResponse, MockLLMClient, ToolCall
from devagent.memory import RetrievalResult
from devagent.permission import InMemoryPermissionManager, PermissionDecision, RiskLevel
from devagent.task.manager import (
    LLMClientFactory,
    TaskManager,
    create_low_risk_registry,
)
from devagent.task.models import AgentTask, InvalidTaskTransitionError, TaskStatus
from devagent.task.repository import InMemoryTaskRepository
from devagent.tools import BaseTool, ToolExecutor, ToolRegistry, ToolResult


class ManagedApprovalArgs(BaseModel):
    value: str


class ManagedApprovalTool(BaseTool[ManagedApprovalArgs]):
    name = "managed_approval"
    description = "测试 TaskManager 审批恢复。"
    args_model = ManagedApprovalArgs
    risk_level = RiskLevel.HIGH

    def __init__(self) -> None:
        self.call_count = 0

    def execute(self, args: ManagedApprovalArgs) -> ToolResult:
        self.call_count += 1
        return ToolResult.ok(f"managed:{args.value}")


class SuccessRuntime:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def run(self, question: str) -> AgentRunResult:
        self.questions.append(question)
        return AgentRunResult(
            success=True,
            status=AgentRunStatus.SUCCESS,
            final_answer="执行成功",
            events=[
                AgentEvent(type=AgentEventType.RUN_START, message="开始"),
                AgentEvent(type=AgentEventType.RUN_END, message="结束"),
            ],
        )


class FailedRuntime:
    def run(self, question: str) -> AgentRunResult:
        return AgentRunResult(
            success=False,
            status=AgentRunStatus.LLM_ERROR,
            error_message="模型调用失败",
            events=[
                AgentEvent(type=AgentEventType.RUN_START, message="开始"),
                AgentEvent(type=AgentEventType.ERROR, message="模型调用失败"),
            ],
        )


class RaisingRuntime:
    def run(self, question: str) -> AgentRunResult:
        raise RuntimeError("boom")


class RecordingLLMClientFactory:
    def __init__(self) -> None:
        self.tool_names: list[str] = []

    def create_client(self, task: AgentTask, tool_registry):
        self.tool_names = [tool.name for tool in tool_registry.list()]
        return MockLLMClient()


def test_create_task_returns_pending_task():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository)

    task = manager.create_task(
        question="请分析项目",
        workspace=".",
        provider="mock",
        max_steps=3,
        max_tool_calls=5,
    )

    assert task.status == TaskStatus.PENDING
    assert task.question == "请分析项目"
    assert task.max_steps == 3
    assert task.max_tool_calls == 5
    assert repository.get(task.task_id).status == TaskStatus.PENDING


def test_llm_client_factory_creates_mock_client():
    factory = LLMClientFactory()
    task = AgentTask(question="请分析项目", provider="mock")

    client = factory.create_client(task, create_low_risk_registry())

    assert isinstance(client, MockLLMClient)


def test_llm_client_factory_creates_real_client_from_request_and_env(
    monkeypatch,
):
    created: dict[str, object] = {}

    class FakeOpenAICompatibleLLMClient:
        def __init__(self, **kwargs) -> None:
            created.update(kwargs)

    monkeypatch.setattr("devagent.task.manager.load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("DEVAGENT_LLM_API_MODE", "chat_completions")
    monkeypatch.delenv("DEVAGENT_LLM_REASONING_EFFORT", raising=False)
    monkeypatch.setattr(
        "devagent.task.manager.create_openai_llm_client",
        lambda **kwargs: FakeOpenAICompatibleLLMClient(**kwargs),
    )
    factory = LLMClientFactory()
    task = AgentTask(
        question="请分析项目",
        provider="real",
        model="test-model",
        base_url="https://example.test/v1",
    )

    client = factory.create_client(task, create_low_risk_registry())

    assert isinstance(client, FakeOpenAICompatibleLLMClient)
    assert created["api_key"] == "test-key"
    assert created["model"] == "test-model"
    assert created["base_url"] == "https://example.test/v1"
    assert created["api_mode"] == "chat_completions"
    assert created["reasoning_effort"] is None
    tool_names = [tool["function"]["name"] for tool in created["tools"]]
    assert tool_names == ["read_file", "search_code"]


def test_llm_client_factory_creates_real_client_from_env_defaults(monkeypatch):
    created: dict[str, object] = {}

    class FakeOpenAICompatibleLLMClient:
        def __init__(self, **kwargs) -> None:
            created.update(kwargs)

    monkeypatch.setattr("devagent.task.manager.load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "env-model")
    monkeypatch.setenv("DEVAGENT_LLM_BASE_URL", "https://env.example.test/v1")
    monkeypatch.setenv("DEVAGENT_LLM_API_MODE", "chat_completions")
    monkeypatch.delenv("DEVAGENT_LLM_REASONING_EFFORT", raising=False)
    monkeypatch.setattr(
        "devagent.task.manager.create_openai_llm_client",
        lambda **kwargs: FakeOpenAICompatibleLLMClient(**kwargs),
    )
    factory = LLMClientFactory()
    task = AgentTask(question="请分析项目", provider="real")

    factory.create_client(task, create_low_risk_registry())

    assert created["api_key"] == "test-key"
    assert created["model"] == "env-model"
    assert created["base_url"] == "https://env.example.test/v1"
    assert created["api_mode"] == "chat_completions"


def test_llm_client_factory_forwards_responses_and_reasoning_env(monkeypatch):
    created: dict[str, object] = {}

    monkeypatch.setattr("devagent.task.manager.load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("DEVAGENT_LLM_API_MODE", "responses")
    monkeypatch.setenv("DEVAGENT_LLM_REASONING_EFFORT", "medium")
    monkeypatch.setattr(
        "devagent.task.manager.create_openai_llm_client",
        lambda **kwargs: created.update(kwargs) or MockLLMClient(),
    )

    LLMClientFactory().create_client(
        AgentTask(question="请分析项目", provider="real"),
        create_low_risk_registry(),
    )

    assert created["api_mode"] == "responses"
    assert created["reasoning_effort"] == "medium"


def test_llm_client_factory_rejects_real_client_without_api_key(monkeypatch):
    monkeypatch.setattr("devagent.task.manager.load_dotenv", lambda **kwargs: None)
    monkeypatch.delenv("DEVAGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    factory = LLMClientFactory()
    task = AgentTask(question="请分析项目", provider="real", model="test-model")

    with pytest.raises(ValueError, match="缺少 LLM API Key"):
        factory.create_client(task, create_low_risk_registry())


def test_llm_client_factory_rejects_real_client_without_model(monkeypatch):
    monkeypatch.setattr("devagent.task.manager.load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "test-key")
    monkeypatch.delenv("DEVAGENT_LLM_MODEL", raising=False)
    factory = LLMClientFactory()
    task = AgentTask(question="请分析项目", provider="real")

    with pytest.raises(ValueError, match="缺少 LLM 模型名称"):
        factory.create_client(task, create_low_risk_registry())


def test_default_runtime_exposes_builtin_tools_through_permission_aware_executor():
    repository = InMemoryTaskRepository()
    llm_client_factory = RecordingLLMClientFactory()
    manager = TaskManager(
        repository,
        llm_client_factory=llm_client_factory,
    )
    task = manager.create_task(
        question="请分析项目",
        provider="real",
        model="test-model",
    )

    manager._create_runtime(task)

    assert llm_client_factory.tool_names == [
        "get_ci_result",
        "git_compare",
        "git_diff",
        "knowledge_retrieve",
        "read_file",
        "run_shell",
        "search_code",
        "search_log",
    ]


def test_task_manager_injects_knowledge_strategy_into_runtime_registry():
    calls: list[tuple[str, str, int]] = []

    def retrieve(query: str, workspace: str, top_k: int) -> RetrievalResult:
        calls.append((query, workspace, top_k))
        return RetrievalResult(
            query=query,
            top_k=top_k,
            total_candidates=0,
            retrieval_ms=2.0,
        )

    manager = TaskManager(
        InMemoryTaskRepository(),
        knowledge_retriever=retrieve,
    )
    task = manager.create_task(question="检索 runtime", workspace="workspace")

    result = manager._create_tool_registry(task).execute(
        "knowledge_retrieve",
        {"query": "runtime", "workspace": task.workspace, "top_k": 3},
    )

    assert result.success is True
    assert calls == [("runtime", "workspace", 3)]


def test_run_task_success_marks_task_done():
    repository = InMemoryTaskRepository()
    runtime = SuccessRuntime()
    manager = TaskManager(repository, runtime_factory=lambda task: runtime)
    task = manager.create_task(question="请分析项目")

    updated = manager.run_task(task.task_id)

    assert updated.status == TaskStatus.DONE
    assert repository.get(task.task_id).status == TaskStatus.DONE
    assert runtime.questions == ["请分析项目"]


def test_run_task_success_saves_events():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository, runtime_factory=lambda task: SuccessRuntime())
    task = manager.create_task(question="请分析项目")

    manager.run_task(task.task_id)

    events = manager.event_store.list(task.task_id)
    assert [event.type for event in events] == [
        AgentEventType.RUN_START,
        AgentEventType.RUN_END,
    ]


def test_run_task_failed_result_marks_task_failed():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository, runtime_factory=lambda task: FailedRuntime())
    task = manager.create_task(question="请分析项目")

    updated = manager.run_task(task.task_id)

    assert updated.status == TaskStatus.FAILED
    assert updated.error_message == "模型调用失败"
    assert repository.get(task.task_id).status == TaskStatus.FAILED


def test_run_task_failed_result_saves_events():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository, runtime_factory=lambda task: FailedRuntime())
    task = manager.create_task(question="请分析项目")

    manager.run_task(task.task_id)

    events = manager.event_store.list(task.task_id)
    assert [event.type for event in events] == [
        AgentEventType.RUN_START,
        AgentEventType.ERROR,
    ]


def test_task_manager_resumes_suspended_runtime_after_approval():
    repository = InMemoryTaskRepository()
    event_bus = InMemoryEventBus()
    allocator = InMemorySequenceAllocator()
    permission_manager = InMemoryPermissionManager(
        event_bus=event_bus,
        sequence_allocator=allocator,
    )
    registry = ToolRegistry()
    tool = ManagedApprovalTool()
    registry.register(tool)
    executor = ToolExecutor(
        registry=registry,
        permission_manager=permission_manager,
    )
    client = MockLLMClient(
        responses=[
            LLMResponse.tool_calls_response(
                [
                    ToolCall(
                        id="managed-call-1",
                        name=tool.name,
                        arguments={"value": "safe"},
                    )
                ]
            ),
            LLMResponse.final_answer("任务完成"),
        ]
    )

    def create_runtime(task: AgentTask) -> AgentRuntime:
        return AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            tool_executor=executor,
            event_bus=event_bus,
            sequence_allocator=allocator,
            task_id=task.task_id,
            workspace=task.workspace,
        )

    manager = TaskManager(
        repository,
        runtime_factory=create_runtime,
        event_bus=event_bus,
        permission_manager=permission_manager,
        sequence_allocator=allocator,
    )
    task = manager.create_task(question="执行受控工具")

    waiting = manager.run_task(task.task_id)
    pending_request = permission_manager.list_pending()[0]

    assert waiting.status == TaskStatus.WAITING_PERMISSION
    assert manager.can_resume_permission(pending_request.request_id) is True
    assert tool.call_count == 0

    permission_manager.resolve(
        pending_request.request_id,
        PermissionDecision.ALLOW,
    )
    completed = manager.resume_task(pending_request.request_id)

    assert completed.status == TaskStatus.DONE
    assert manager.can_resume_permission(pending_request.request_id) is False
    assert tool.call_count == 1
    assert [event.type for event in manager.event_store.list(task.task_id)].count(
        AgentEventType.RUN_START
    ) == 1


def test_run_task_runtime_exception_marks_task_failed():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository, runtime_factory=lambda task: RaisingRuntime())
    task = manager.create_task(question="请分析项目")

    updated = manager.run_task(task.task_id)

    assert updated.status == TaskStatus.FAILED
    assert "任务执行失败: boom" == updated.error_message


def test_run_task_runtime_exception_saves_error_event():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository, runtime_factory=lambda task: RaisingRuntime())
    task = manager.create_task(question="请分析项目")

    manager.run_task(task.task_id)

    events = manager.event_store.list(task.task_id)
    assert len(events) == 1
    assert events[0].type == AgentEventType.ERROR
    assert events[0].message == "任务执行失败: boom"


def test_run_task_skips_cancelled_task():
    repository = InMemoryTaskRepository()
    runtime = SuccessRuntime()
    manager = TaskManager(repository, runtime_factory=lambda task: runtime)
    task = manager.create_task(question="请分析项目")
    manager.cancel_task(task.task_id)

    updated = manager.run_task(task.task_id)

    assert updated.status == TaskStatus.CANCELLED
    assert runtime.questions == []


def test_cancel_task_uses_state_machine():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository)
    task = manager.create_task(question="请分析项目")

    cancelled = manager.cancel_task(task.task_id)

    assert cancelled.status == TaskStatus.CANCELLED
    with pytest.raises(InvalidTaskTransitionError, match="CANCELLED -> CANCELLED"):
        manager.cancel_task(task.task_id)
