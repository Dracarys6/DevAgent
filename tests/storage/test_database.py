import sqlite3
from pathlib import Path

import pytest

from devagent.storage import MIGRATIONS, SQLiteDatabase, SQLiteSettings

EXPECTED_TABLES = {
    "schema_migrations",
    "agent_tasks",
    "agent_events",
    "tool_calls",
    "permission_requests",
    "permission_policies",
    "eval_runs",
    "webhook_deliveries",
    "github_review_publications",
    "event_sequences",
}

EXPECTED_INDEXES = {
    "idx_agent_events_task_timestamp",
    "idx_agent_events_type_timestamp",
    "idx_tool_calls_task_started",
    "idx_permission_requests_task_status",
    "idx_permission_policies_tool_enabled",
    "idx_eval_runs_type_started",
    "idx_eval_runs_model_started",
    "idx_webhook_deliveries_repo_updated",
    "idx_review_publications_delivery",
}


def make_database(tmp_path: Path, *, busy_timeout_ms: int = 2_000) -> SQLiteDatabase:
    return SQLiteDatabase(
        SQLiteSettings(
            path=tmp_path / "state" / "devagent.db",
            busy_timeout_ms=busy_timeout_ms,
        )
    )


def insert_task(connection: sqlite3.Connection, task_id: str = "task-1") -> None:
    connection.execute(
        """
        INSERT INTO agent_tasks(
            task_id, question, workspace, provider, model, base_url,
            max_steps, max_tool_calls, status, error_message,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            "diagnose failure",
            ".",
            "mock",
            None,
            None,
            10,
            20,
            "PENDING",
            None,
            "2026-08-05T00:00:00+00:00",
            "2026-08-05T00:00:00+00:00",
        ),
    )


def test_initialize_creates_current_schema_and_is_idempotent(tmp_path: Path) -> None:
    database = make_database(tmp_path)

    database.initialize()
    database.initialize()

    connection = database.connect()
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        migration_count = connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()["count"]
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    finally:
        connection.close()
    assert EXPECTED_TABLES <= tables
    assert EXPECTED_INDEXES <= indexes
    assert migration_count == len(MIGRATIONS)


def test_connect_applies_pragmas_and_row_factory(tmp_path: Path) -> None:
    database = make_database(tmp_path, busy_timeout_ms=3_210)
    database.initialize()

    connection = database.connect()
    try:
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 3_210
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        connection.close()


def test_connect_closes_connection_when_configuration_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InterruptingConnection:
        row_factory: object | None = None
        closed = False

        def execute(self, _statement: str) -> None:
            raise KeyboardInterrupt

        def close(self) -> None:
            self.closed = True

    connection = InterruptingConnection()
    monkeypatch.setattr(
        "devagent.storage.database.sqlite3.connect",
        lambda *_args, **_kwargs: connection,
    )
    database = make_database(tmp_path)

    with pytest.raises(KeyboardInterrupt):
        database.connect()

    assert connection.closed is True


def test_transaction_commits_all_statements_and_closes_connection(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    database.initialize()

    with database.transaction() as transaction_connection:
        insert_task(transaction_connection)

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        transaction_connection.execute("SELECT 1")
    connection = database.connect()
    try:
        assert (
            connection.execute(
                "SELECT question FROM agent_tasks WHERE task_id = 'task-1'"
            ).fetchone()["question"]
            == "diagnose failure"
        )
    finally:
        connection.close()


def test_transaction_rolls_back_all_statements_and_closes_connection(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    database.initialize()

    with (
        pytest.raises(RuntimeError, match="abort transaction"),
        database.transaction() as transaction_connection,
    ):
        insert_task(transaction_connection)
        raise RuntimeError("abort transaction")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        transaction_connection.execute("SELECT 1")
    connection = database.connect()
    try:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM agent_tasks"
        ).fetchone()["count"]
    finally:
        connection.close()
    assert count == 0


def test_transaction_rolls_back_process_interrupt(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    database.initialize()

    with (
        pytest.raises(KeyboardInterrupt),
        database.transaction() as transaction_connection,
    ):
        insert_task(transaction_connection)
        raise KeyboardInterrupt

    connection = database.connect()
    try:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM agent_tasks"
        ).fetchone()["count"]
    finally:
        connection.close()
    assert count == 0


def test_transaction_can_begin_immediate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingConnection:
        def __init__(self) -> None:
            self.statements: list[str] = []
            self.committed = False
            self.closed = False

        def execute(self, statement: str) -> None:
            self.statements.append(statement)

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            raise AssertionError("成功事务不应 rollback")

        def close(self) -> None:
            self.closed = True

    connection = RecordingConnection()
    database = make_database(tmp_path)
    monkeypatch.setattr(database, "connect", lambda: connection)

    with database.transaction(immediate=True) as yielded:
        assert yielded is connection

    assert connection.statements == ["BEGIN IMMEDIATE"]
    assert connection.committed is True
    assert connection.closed is True


def test_committed_data_survives_new_database_instance(tmp_path: Path) -> None:
    path = tmp_path / "persistent.db"
    first = SQLiteDatabase(SQLiteSettings(path=path))
    first.initialize()
    with first.transaction() as connection:
        insert_task(connection, "restart-task")

    second = SQLiteDatabase(SQLiteSettings(path=path))
    second.initialize()
    connection = second.connect()
    try:
        row = connection.execute(
            "SELECT status FROM agent_tasks WHERE task_id = 'restart-task'"
        ).fetchone()
    finally:
        connection.close()
    assert row["status"] == "PENDING"


def test_event_sequence_is_unique_per_task(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    database.initialize()
    with (
        pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"),
        database.transaction() as connection,
    ):
        insert_task(connection)
        values = (
            "task-1",
            None,
            1,
            "agent_started",
            "started",
            "{}",
            "2026-08-05T00:00:00+00:00",
        )
        connection.execute(
            """
            INSERT INTO agent_events(
                event_id, task_id, session_id, sequence_id,
                event_type, message, event_json, timestamp
            ) VALUES ('event-1', ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        connection.execute(
            """
            INSERT INTO agent_events(
                event_id, task_id, session_id, sequence_id,
                event_type, message, event_json, timestamp
            ) VALUES ('event-2', ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )


def test_event_requires_existing_task(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    database.initialize()

    with (
        pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"),
        database.transaction() as connection,
    ):
        connection.execute(
            """
            INSERT INTO agent_events(
                event_id, task_id, sequence_id, event_type,
                message, event_json, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "missing-task",
                1,
                "agent_started",
                "started",
                "{}",
                "2026-08-05T00:00:00+00:00",
            ),
        )


def test_webhook_delivery_accepts_current_store_contract_and_validates_state(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    database.initialize()

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO webhook_deliveries(
                delivery_id, state, updated_at
            ) VALUES (?, ?, ?)
            """,
            ("delivery-1", "processing", "2026-08-05T00:00:00+00:00"),
        )

    with (
        pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"),
        database.transaction() as connection,
    ):
        connection.execute(
            """
            INSERT INTO webhook_deliveries(
                delivery_id, state, updated_at
            ) VALUES (?, ?, ?)
            """,
            ("delivery-2", "unknown", "2026-08-05T00:00:00+00:00"),
        )


@pytest.mark.parametrize("busy_timeout_ms", [0, 600_001, True, 1.5])
def test_settings_reject_invalid_busy_timeout(
    tmp_path: Path,
    busy_timeout_ms: object,
) -> None:
    expected_error = (
        TypeError if isinstance(busy_timeout_ms, (bool, float)) else ValueError
    )
    with pytest.raises(expected_error):
        SQLiteSettings(
            path=tmp_path / "devagent.db",
            busy_timeout_ms=busy_timeout_ms,  # type: ignore[arg-type]
        )


def test_settings_reject_memory_database() -> None:
    with pytest.raises(ValueError, match="不支持"):
        SQLiteSettings(path=Path(":memory:"))
