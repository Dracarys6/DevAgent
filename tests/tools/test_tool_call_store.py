from pathlib import Path

from devagent.storage import SQLiteDatabase, SQLiteSettings
from devagent.task import AgentTask, SQLiteTaskRepository
from devagent.tools import SQLiteToolCallStore, ToolCallRecord, ToolResult


def make_store(tmp_path: Path) -> SQLiteToolCallStore:
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "tools.db"))
    database.initialize()
    SQLiteTaskRepository(database).create(
        AgentTask(task_id="task-1", question="tool persistence")
    )
    return SQLiteToolCallStore(database)


def test_tool_call_lifecycle_survives_reopened_store(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.start(
        ToolCallRecord(
            task_id="task-1",
            tool_call_id="call-1",
            tool_name="read_file",
            arguments={"path": "README.md"},
            risk_level="LOW",
            status="STARTED",
        )
    )
    store.save_result(
        "task-1",
        "call-1",
        status="EXECUTED",
        result=ToolResult.ok("content"),
        duration_ms=12.5,
    )

    restored = store.get("task-1", "call-1")

    assert restored.status == "EXECUTED"
    assert restored.result == ToolResult.ok("content")
    assert restored.duration_ms == 12.5
    assert restored.finished_at is not None


def test_tool_call_waiting_state_has_no_finished_at_and_redacts_secrets(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.start(
        ToolCallRecord(
            task_id="task-1",
            tool_call_id="call-1",
            tool_name="request",
            arguments={"authorization": "Bearer secret"},
            status="STARTED",
        )
    )
    store.save_result(
        "task-1",
        "call-1",
        status="WAITING_PERMISSION",
        result=None,
        duration_ms=1,
    )

    restored = store.get("task-1", "call-1")
    assert restored.arguments == {"authorization": "[REDACTED]"}
    assert restored.finished_at is None
