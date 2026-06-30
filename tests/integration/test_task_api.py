from fastapi.testclient import TestClient

from devagent.api.app import app

client = TestClient(app)


# 连续创建多个任务
def test_create_multiple_tasks_keeps_task_state_isolated():
    first = client.post("/api/v1/agent/tasks", json={"question": "任务 A"})
    second = client.post("/api/v1/agent/tasks", json={"question": "任务 B"})

    assert first.status_code == 201
    assert second.status_code == 201

    first_id = first.json()["task_id"]
    second_id = second.json()["task_id"]

    assert first_id != second_id, "任务 ID 应该是唯一的"

    first_task = client.get(f"/api/v1/agent/tasks/{first_id}").json()
    second_task = client.get(f"/api/v1/agent/tasks/{second_id}").json()

    assert first_task["question"] == "任务 A", "第一个任务的内容应该是 '任务 A'"
    assert second_task["question"] == "任务 B", "第二个任务的内容应该是 '任务 B'"
    assert first_task["status"] == "DONE"
    assert second_task["status"] == "DONE"


# 事件按 task_id 隔离
def test_task_events_are_isolated_by_task_id():
    task_A = client.post("/api/v1/agent/tasks", json={"question": "任务 A"})
    task_B = client.post("/api/v1/agent/tasks", json={"question": "任务 B"})

    assert task_A.status_code == 201
    assert task_B.status_code == 201

    task_A_id = task_A.json()["task_id"]
    task_B_id = task_B.json()["task_id"]

    A_response = client.get(f"/api/v1/agent/tasks/{task_A_id}/events")
    B_response = client.get(f"/api/v1/agent/tasks/{task_B_id}/events")

    assert A_response.status_code == 200
    assert B_response.status_code == 200

    A_events = A_response.json()
    B_events = B_response.json()

    A_event_types = [event["type"] for event in A_events["events"]]
    B_event_types = [event["type"] for event in B_events["events"]]

    assert "run_start" in A_event_types, "任务 A 应该有 run_start 事件"
    assert "run_start" in B_event_types, "任务 B 应该有 run_start 事件"
    assert "run_end" in A_event_types, "任务 A 应该有 run_end 事件"
    assert "run_end" in B_event_types, "任务 B 应该有 run_end 事件"

    A_run_start = [
        event for event in A_events["events"] if event["type"] == "run_start"
    ][0]
    B_run_start = [
        event for event in B_events["events"] if event["type"] == "run_start"
    ][0]

    assert (
        A_run_start["metadata"]["user_input"] == "任务 A"
    ), "task A 的 run_start metadata.user_input 是任务 A"
    assert (
        B_run_start["metadata"]["user_input"] == "任务 B"
    ), "task B 的 run_start metadata.user_input 是任务 B"


# 列表接口包含新任务
def test_list_agent_tasks_contains_created_task():
    created = client.post(
        "/api/v1/agent/tasks",
        json={"question": "请分析列表接口"},
    )
    task_id = created.json()["task_id"]

    response = client.get("/api/v1/agent/tasks/list")

    assert response.status_code == 200
    task_ids = [task["task_id"] for task in response.json()["tasks"]]
    assert task_id in task_ids
