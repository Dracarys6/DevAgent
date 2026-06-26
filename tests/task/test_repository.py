import pytest

from devagent.task.models import AgentTask, InvalidTaskTransitionError, TaskStatus
from devagent.task.repository import InMemoryTaskRepository, TaskNotFoundError


def test_create_then_get_task():
    repository = InMemoryTaskRepository()
    task = AgentTask(question="请分析项目")

    created = repository.create(task)
    saved = repository.get(created.task_id)

    assert saved.task_id == task.task_id
    assert saved.question == "请分析项目"
    assert saved.status == TaskStatus.PENDING


def test_get_missing_task_raises_not_found():
    repository = InMemoryTaskRepository()

    with pytest.raises(TaskNotFoundError, match="任务不存在"):
        repository.get("missing-task-id")


def test_update_status_returns_updated_task():
    repository = InMemoryTaskRepository()
    created = repository.create(AgentTask(question="请分析项目"))

    updated = repository.update_status(created.task_id, TaskStatus.RUNNING)

    assert updated.status == TaskStatus.RUNNING
    assert repository.get(created.task_id).status == TaskStatus.RUNNING


def test_update_status_records_error_message():
    repository = InMemoryTaskRepository()
    created = repository.create(AgentTask(question="请分析项目"))
    repository.update_status(created.task_id, TaskStatus.RUNNING)

    updated = repository.update_status(
        created.task_id,
        TaskStatus.FAILED,
        error_message="执行失败",
    )

    assert updated.status == TaskStatus.FAILED
    assert updated.error_message == "执行失败"


def test_update_missing_task_raises_not_found():
    repository = InMemoryTaskRepository()

    with pytest.raises(TaskNotFoundError, match="任务不存在"):
        repository.update_status("missing-task-id", TaskStatus.RUNNING)


def test_invalid_transition_raises_error():
    repository = InMemoryTaskRepository()
    created = repository.create(AgentTask(question="请分析项目"))

    with pytest.raises(InvalidTaskTransitionError, match="PENDING -> DONE"):
        repository.update_status(created.task_id, TaskStatus.DONE)


def test_list_returns_all_tasks_in_create_order():
    repository = InMemoryTaskRepository()
    first = repository.create(AgentTask(question="第一个任务"))
    second = repository.create(AgentTask(question="第二个任务"))

    tasks = repository.list()

    assert [task.task_id for task in tasks] == [first.task_id, second.task_id]


def test_create_stores_copy_to_protect_repository_state():
    repository = InMemoryTaskRepository()
    task = AgentTask(question="请分析项目")
    created = repository.create(task)

    task.status = TaskStatus.DONE

    assert repository.get(created.task_id).status == TaskStatus.PENDING


def test_get_returns_copy_to_protect_repository_state():
    repository = InMemoryTaskRepository()
    created = repository.create(AgentTask(question="请分析项目"))

    returned = repository.get(created.task_id)
    returned.status = TaskStatus.DONE

    assert repository.get(created.task_id).status == TaskStatus.PENDING


def test_list_returns_copies_to_protect_repository_state():
    repository = InMemoryTaskRepository()
    created = repository.create(AgentTask(question="请分析项目"))

    tasks = repository.list()
    tasks[0].status = TaskStatus.DONE

    assert repository.get(created.task_id).status == TaskStatus.PENDING
