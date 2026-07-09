from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes.tasks import event_bus, task_manager
from devagent.event import AgentFinished, AgentStarted

client = TestClient(app)


def test_get_agent_task_trace_returns_trace():
    task = task_manager.create_task(question="请分析 Trace")
    event_bus.publish(
        AgentStarted(
            task_id=task.task_id,
            sequence_id=1,
            message="Agent 运行开始",
            user_input=task.question,
        )
    )
    event_bus.publish(
        AgentFinished(
            task_id=task.task_id,
            sequence_id=2,
            message="Agent 运行结束",
            status="success",
            final_answer="Trace 已生成",
        )
    )

    response = client.get(f"/api/v1/agent/tasks/{task.task_id}/trace")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == task.task_id
    assert data["summary"]["event_count"] == 2
    assert data["summary"]["final_status"] == "success"
    assert data["summary"]["final_answer"] == "Trace 已生成"
    assert [step["sequence_id"] for step in data["steps"]] == [1, 2]
    assert data["steps"][0]["details"]["user_input"] == "请分析 Trace"


def test_get_agent_task_trace_returns_empty_trace_for_task_without_events():
    task = task_manager.create_task(question="空 Trace")

    response = client.get(f"/api/v1/agent/tasks/{task.task_id}/trace")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == task.task_id
    assert data["summary"]["event_count"] == 0
    assert data["steps"] == []


def test_get_agent_task_trace_returns_404_for_missing_task():
    response = client.get("/api/v1/agent/tasks/not-found/trace")

    assert response.status_code == 404


def test_trace_route_is_registered_in_openapi():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/agent/tasks/{task_id}/trace" in response.json()["paths"]


def test_trace_api_does_not_break_task_events_api():
    task = task_manager.create_task(question="事件接口仍可用")
    event_bus.publish(
        AgentStarted(
            task_id=task.task_id,
            sequence_id=1,
            message="Agent 运行开始",
            user_input=task.question,
        )
    )

    trace_response = client.get(f"/api/v1/agent/tasks/{task.task_id}/trace")
    events_response = client.get(f"/api/v1/agent/tasks/{task.task_id}/events")

    assert trace_response.status_code == 200
    assert events_response.status_code == 200
    assert events_response.json()["task_id"] == task.task_id
