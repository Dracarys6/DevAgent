from datetime import UTC, datetime
from pathlib import Path

from devagent.eval import EvalRunRecord, EvalRunStatus, SQLiteEvalRunRepository
from devagent.event import AgentFinished, AgentStarted, create_event_runtime
from devagent.integrations.github import (
    DeliveryState,
    PublicationStatus,
    SQLiteGitHubReviewPublicationStore,
    SQLiteWebhookDeliveryStore,
)
from devagent.permission import PermissionDecision, RiskLevel, create_permission_runtime
from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import AgentTask, SQLiteTaskRepository
from devagent.tools import ToolCallRecord, ToolResult


def initialize(database_path: Path):
    database = SQLiteDatabase(SQLiteSettings(path=database_path))
    database.initialize()
    tasks = SQLiteTaskRepository(database)
    events = create_event_runtime(database_path)
    permissions = create_permission_runtime(
        database_path,
        event_bus=events.event_bus,
        sequence_allocator=events.sequence_allocator,
    )
    return database, tasks, events, permissions


def test_week10_records_survive_complete_adapter_reconstruction(tmp_path: Path) -> None:
    database_path = tmp_path / "week10.db"
    database, tasks, events, permissions = initialize(database_path)
    task = tasks.create(
        AgentTask(task_id="task-1", question="Week10 restart acceptance")
    )
    events.event_bus.publish(
        AgentStarted(
            task_id=task.task_id,
            sequence_id=events.sequence_allocator.next(task.task_id),
            message="started",
            user_input=task.question,
        )
    )
    request = permissions.manager.request_permission(
        task_id=task.task_id,
        tool_call_id="call-1",
        tool_name="run_shell",
        risk_level=RiskLevel.HIGH,
        reason="approval",
    )
    permissions.manager.resolve(request.request_id, PermissionDecision.DENY)
    policy = permissions.policy_store.create_policy(
        name="deny shell",
        decision=PermissionDecision.DENY,
        tool_name="run_shell",
        risk_levels=[RiskLevel.HIGH],
    )
    assert permissions.tool_call_store is not None
    permissions.tool_call_store.start(
        ToolCallRecord(
            task_id=task.task_id,
            tool_call_id="call-1",
            tool_name="run_shell",
            arguments={"command": ["pytest", "-q"]},
            risk_level="HIGH",
            status="STARTED",
        )
    )
    permissions.tool_call_store.save_result(
        task.task_id,
        "call-1",
        status="BLOCKED",
        result=ToolResult.fail(
            error_code="PERMISSION_DENIED",
            error_message="denied",
        ),
        duration_ms=2,
    )
    events.event_bus.publish(
        AgentFinished(
            task_id=task.task_id,
            sequence_id=events.sequence_allocator.next(task.task_id),
            message="finished",
            status="blocked",
        )
    )
    now = datetime.now(UTC)
    eval_run = SQLiteEvalRunRepository(database).save(
        EvalRunRecord(
            eval_type="week10_acceptance",
            status=EvalRunStatus.PASSED,
            metrics={"trace_complete": 1.0},
            started_at=now,
            finished_at=now,
        )
    )
    deliveries = SQLiteWebhookDeliveryStore(database)
    deliveries.claim("delivery-1")
    publications = SQLiteGitHubReviewPublicationStore(database)
    publication = publications.claim(
        delivery_id="delivery-1",
        repository_full_name="openai/devagent",
        pull_number=42,
        head_sha="b" * 40,
    )
    publications.mark_completed(publication.publication.publication_id, "comment-1")
    deliveries.mark_completed("delivery-1")

    reopened_database, reopened_tasks, reopened_events, reopened_permissions = (
        initialize(database_path)
    )

    assert reopened_tasks.get(task.task_id) == task
    restored_events = reopened_events.event_bus.list_events(task.task_id)
    assert [event.sequence_id for event in restored_events] == [1, 2, 3, 4]
    assert reopened_permissions.manager.get_request(request.request_id).decision == (
        PermissionDecision.DENY
    )
    assert reopened_permissions.policy_store.get_policy(policy.policy_id) == policy
    assert reopened_permissions.tool_call_store is not None
    assert reopened_permissions.tool_call_store.get(task.task_id, "call-1").status == (
        "BLOCKED"
    )
    assert SQLiteEvalRunRepository(reopened_database).get(eval_run.run_id) == eval_run
    assert (
        SQLiteWebhookDeliveryStore(reopened_database).get_state("delivery-1")
        == DeliveryState.COMPLETED
    )
    restored_publication = SQLiteGitHubReviewPublicationStore(reopened_database).get(
        publication.publication.publication_id
    )
    assert restored_publication.status == PublicationStatus.COMPLETED
    assert restored_publication.external_comment_id == "comment-1"
