from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


class MigrationError(RuntimeError):
    """数据库 migration 定义或已应用版本不可信。"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("migration version 必须是整数")
        if self.version < 1:
            raise ValueError("migration version 必须大于或等于 1")
        if not self.name or self.name != self.name.strip():
            raise ValueError("migration name 不能为空或包含首尾空白")
        if not self.statements or any(
            not statement.strip() for statement in self.statements
        ):
            raise ValueError("migration statements 不能为空")

    @property
    def checksum(self) -> str:
        payload = f"{self.version}\n{self.name}\n" + "\n-- statement --\n".join(
            statement.strip() for statement in self.statements
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_CREATE_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


SCHEMA_V1 = Migration(
    version=1,
    name="initial_persistence_schema",
    statements=(
        """
        CREATE TABLE agent_tasks (
            task_id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            workspace TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT,
            base_url TEXT,
            max_steps INTEGER NOT NULL CHECK (max_steps > 0),
            max_tool_calls INTEGER NOT NULL CHECK (max_tool_calls > 0),
            status TEXT NOT NULL CHECK (
                status IN ('PENDING', 'RUNNING', 'WAITING_PERMISSION',
                           'DONE', 'FAILED', 'CANCELLED')
            ),
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE agent_events (
            event_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            session_id TEXT,
            sequence_id INTEGER NOT NULL CHECK (sequence_id > 0),
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            event_json TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES agent_tasks(task_id),
            UNIQUE (task_id, sequence_id)
        )
        """,
        "CREATE INDEX idx_agent_events_task_timestamp ON agent_events(task_id, timestamp)",
        "CREATE INDEX idx_agent_events_type_timestamp ON agent_events(event_type, timestamp)",
        """
        CREATE TABLE tool_calls (
            task_id TEXT NOT NULL,
            tool_call_id TEXT NOT NULL,
            session_id TEXT,
            tool_name TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            risk_level TEXT,
            status TEXT NOT NULL,
            result_json TEXT,
            error_code TEXT,
            error_message TEXT,
            duration_ms REAL CHECK (duration_ms IS NULL OR duration_ms >= 0),
            started_at TEXT NOT NULL,
            finished_at TEXT,
            PRIMARY KEY (task_id, tool_call_id),
            FOREIGN KEY (task_id) REFERENCES agent_tasks(task_id)
        )
        """,
        "CREATE INDEX idx_tool_calls_task_started ON tool_calls(task_id, started_at)",
        """
        CREATE TABLE permission_requests (
            request_id TEXT PRIMARY KEY,
            task_id TEXT,
            tool_call_id TEXT,
            tool_name TEXT NOT NULL,
            tool_arguments_json TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('PENDING', 'APPROVED', 'DENIED', 'CANCELLED', 'EXPIRED')
            ),
            decision TEXT CHECK (decision IS NULL OR decision IN ('ALLOW', 'DENY')),
            decision_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT,
            FOREIGN KEY (task_id) REFERENCES agent_tasks(task_id)
        )
        """,
        "CREATE INDEX idx_permission_requests_task_status ON permission_requests(task_id, status)",
        """
        CREATE TABLE permission_policies (
            policy_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tool_name TEXT,
            risk_levels_json TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('ALLOW', 'DENY')),
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
            arguments_fingerprint TEXT,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_permission_policies_tool_enabled ON permission_policies(tool_name, enabled)",
        """
        CREATE TABLE eval_runs (
            run_id TEXT PRIMARY KEY,
            eval_type TEXT NOT NULL,
            dataset_id TEXT,
            provider TEXT,
            model TEXT,
            api_mode TEXT,
            status TEXT NOT NULL,
            config_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            schema_valid INTEGER NOT NULL CHECK (schema_valid IN (0, 1)),
            started_at TEXT NOT NULL,
            finished_at TEXT,
            latency_ms REAL CHECK (latency_ms IS NULL OR latency_ms >= 0)
        )
        """,
        "CREATE INDEX idx_eval_runs_type_started ON eval_runs(eval_type, started_at)",
        "CREATE INDEX idx_eval_runs_model_started ON eval_runs(provider, model, started_at)",
        """
        CREATE TABLE webhook_deliveries (
            delivery_id TEXT PRIMARY KEY,
            event_name TEXT,
            repository_full_name TEXT,
            state TEXT NOT NULL CHECK (state IN ('processing', 'completed')),
            claimed_at TEXT,
            completed_at TEXT,
            error_message TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_webhook_deliveries_repo_updated ON webhook_deliveries(repository_full_name, updated_at)",
        """
        CREATE TABLE github_review_publications (
            publication_id TEXT PRIMARY KEY,
            delivery_id TEXT NOT NULL,
            repository_full_name TEXT NOT NULL,
            pull_number INTEGER NOT NULL CHECK (pull_number > 0),
            head_sha TEXT NOT NULL,
            status TEXT NOT NULL,
            external_comment_id TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (delivery_id) REFERENCES webhook_deliveries(delivery_id),
            UNIQUE (repository_full_name, pull_number, head_sha)
        )
        """,
        "CREATE INDEX idx_review_publications_delivery ON github_review_publications(delivery_id)",
    ),
)

SCHEMA_V2 = Migration(
    version=2,
    name="persistent_event_sequence",
    statements=(
        """
        ALTER TABLE agent_events
        ADD COLUMN event_model TEXT NOT NULL DEFAULT 'BaseEvent'
        """,
        """
        CREATE TABLE event_sequences (
            task_id TEXT PRIMARY KEY,
            next_sequence_id INTEGER NOT NULL CHECK (next_sequence_id > 0),
            FOREIGN KEY (task_id) REFERENCES agent_tasks(task_id)
        )
        """,
    ),
)

MIGRATIONS: tuple[Migration, ...] = (SCHEMA_V1, SCHEMA_V2)


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> None:
    """在一个事务内校验并应用缺失 migration。"""
    if connection.in_transaction:
        raise MigrationError("migration 不能在已有事务中执行")
    ordered = _validate_migrations(migrations)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_CREATE_MIGRATION_TABLE)
        applied_rows = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        # * 使用位置索引，同时兼容 sqlite3.Row 与调用方提供的普通 tuple row。
        applied = {
            int(row[0]): {"name": str(row[1]), "checksum": str(row[2])}
            for row in applied_rows
        }
        supported = {migration.version: migration for migration in ordered}

        unsupported = sorted(set(applied) - set(supported))
        if unsupported:
            raise MigrationError(
                f"数据库版本高于或不属于程序支持范围: {unsupported[-1]}"
            )
        for version, row in applied.items():
            migration = supported[version]
            if row["name"] != migration.name or row["checksum"] != migration.checksum:
                raise MigrationError(f"migration {version} checksum 不一致")

        for migration in ordered:
            if migration.version in applied:
                continue
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    datetime.now(UTC).isoformat(),
                ),
            )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _validate_migrations(migrations: tuple[Migration, ...]) -> tuple[Migration, ...]:
    if not migrations:
        raise MigrationError("migrations 不能为空")
    ordered = tuple(sorted(migrations, key=lambda item: item.version))
    versions = [item.version for item in ordered]
    if len(versions) != len(set(versions)):
        raise MigrationError("migration version 不能重复")
    if versions != list(range(1, versions[-1] + 1)):
        raise MigrationError("migration version 必须从 1 开始连续递增")
    return ordered
