import pytest

from devagent.task.models import AgentTask, InvalidTaskTransitionError, TaskStatus


def test_default_status():
    task = AgentTask(question="请分析项目")
    assert task.status == TaskStatus.PENDING


def test_gen_task_id():
    task = AgentTask(question="请分析项目")
    assert task.task_id is not None


def test_time_zone():
    task = AgentTask(question="请分析项目")
    assert task.created_at.tzinfo is not None
    assert task.updated_at.tzinfo is not None


def test_pending_can_transition_to_running():
    task = AgentTask(question="请分析项目")

    task.transition_to(TaskStatus.RUNNING)

    assert task.status == TaskStatus.RUNNING


def test_running_can_transition_to_done():
    task = AgentTask(question="请分析项目")

    task.transition_to(TaskStatus.RUNNING)
    task.transition_to(TaskStatus.DONE)

    assert task.status == TaskStatus.DONE


def test_running_can_transition_to_failed_with_error_message():
    task = AgentTask(question="请分析项目")

    task.transition_to(TaskStatus.RUNNING)
    task.transition_to(TaskStatus.FAILED, error_message="模型调用失败")

    assert task.status == TaskStatus.FAILED
    assert task.error_message == "模型调用失败"


def test_running_can_wait_permission_then_resume():
    task = AgentTask(question="请分析项目")

    task.transition_to(TaskStatus.RUNNING)
    task.transition_to(TaskStatus.WAITING_PERMISSION)
    task.transition_to(TaskStatus.RUNNING)

    assert task.status == TaskStatus.RUNNING


def test_pending_cannot_transition_to_done():
    task = AgentTask(question="请分析项目")

    with pytest.raises(InvalidTaskTransitionError, match="PENDING -> DONE"):
        task.transition_to(TaskStatus.DONE)


def test_done_is_terminal_status():
    task = AgentTask(question="请分析项目")
    task.transition_to(TaskStatus.RUNNING)
    task.transition_to(TaskStatus.DONE)

    with pytest.raises(InvalidTaskTransitionError, match="DONE -> RUNNING"):
        task.transition_to(TaskStatus.RUNNING)
