import pytest

from devagent.agent import AgentRunResult, AgentRunStatus
from devagent.task.manager import TaskManager
from devagent.task.models import InvalidTaskTransitionError, TaskStatus
from devagent.task.repository import InMemoryTaskRepository


class SuccessRuntime:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def run(self, question: str) -> AgentRunResult:
        self.questions.append(question)
        return AgentRunResult(
            success=True,
            status=AgentRunStatus.SUCCESS,
            final_answer="执行成功",
        )


class FailedRuntime:
    def run(self, question: str) -> AgentRunResult:
        return AgentRunResult(
            success=False,
            status=AgentRunStatus.LLM_ERROR,
            error_message="模型调用失败",
        )


class RaisingRuntime:
    def run(self, question: str) -> AgentRunResult:
        raise RuntimeError("boom")


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


def test_run_task_success_marks_task_done():
    repository = InMemoryTaskRepository()
    runtime = SuccessRuntime()
    manager = TaskManager(repository, runtime_factory=lambda task: runtime)
    task = manager.create_task(question="请分析项目")

    updated = manager.run_task(task.task_id)

    assert updated.status == TaskStatus.DONE
    assert repository.get(task.task_id).status == TaskStatus.DONE
    assert runtime.questions == ["请分析项目"]


def test_run_task_failed_result_marks_task_failed():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository, runtime_factory=lambda task: FailedRuntime())
    task = manager.create_task(question="请分析项目")

    updated = manager.run_task(task.task_id)

    assert updated.status == TaskStatus.FAILED
    assert updated.error_message == "模型调用失败"
    assert repository.get(task.task_id).status == TaskStatus.FAILED


def test_run_task_runtime_exception_marks_task_failed():
    repository = InMemoryTaskRepository()
    manager = TaskManager(repository, runtime_factory=lambda task: RaisingRuntime())
    task = manager.create_task(question="请分析项目")

    updated = manager.run_task(task.task_id)

    assert updated.status == TaskStatus.FAILED
    assert "任务执行失败: boom" == updated.error_message


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
