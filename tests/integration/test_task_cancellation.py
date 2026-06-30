from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes.tasks import task_manager
from devagent.task.models import TaskStatus

client = TestClient(app)


# 未开始任务取消后不会执行
def test_cancel_not_started_task():
    task = task_manager.create_task(question="取消任务测试")  # 创建一个任务
    task_manager.cancel_task(task.task_id)  # 取消任务
    task_manager.run_task(task.task_id)  # 尝试运行任务
    task = task_manager.repository.get(task.task_id)  # 获取任务状态
    assert task.status == TaskStatus.CANCELLED  # 任务状态应为已取消
    events = task_manager.event_store.list(task.task_id)
    assert len(events) == 0  # 任务取消后不会产生事件


# 重复取消返回409
def test_duplicate_cancel_returns_409():
    task = task_manager.create_task(question="重复取消任务测试")
    client.post(f"/api/v1/agent/tasks/{task.task_id}/cancel")  # 第一次取消
    response = client.post(f"/api/v1/agent/tasks/{task.task_id}/cancel")  # 第二次取消
    assert response.status_code == 409  # 第二次取消应返回冲突状态码


# 已完成任务不能取消
def test_cannot_cancel_completed_task():
    task = task_manager.create_task(question="已完成任务取消测试")
    task_manager.run_task(task.task_id)  # 运行任务
    response = client.post(
        f"/api/v1/agent/tasks/{task.task_id}/cancel"
    )  # 尝试取消已完成任务
    assert response.status_code == 409  # 已完成任务取消应返回冲突状态码
    assert "DONE -> CANCELLED" in response.json()["detail"]
