import sqlite3
from pathlib import Path

import pytest

from devagent.storage import (
    MIGRATIONS,
    SCHEMA_V1,
    SCHEMA_V2,
    SCHEMA_V3,
    Migration,
    MigrationError,
    SQLiteDatabase,
    SQLiteSettings,
    apply_migrations,
)


def make_database(tmp_path: Path) -> SQLiteDatabase:
    return SQLiteDatabase(SQLiteSettings(path=tmp_path / "devagent.db"))


def test_all_migrations_are_recorded_once(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    database.initialize()
    database.initialize()

    connection = database.connect()
    try:
        rows = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchall()
    finally:
        connection.close()
    assert [dict(row) for row in rows] == [
        {
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
        }
        for migration in MIGRATIONS
    ]


def test_apply_migrations_supports_default_tuple_rows(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "plain-connection.db", isolation_level=None)
    try:
        apply_migrations(connection)
        rows = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [
        (migration.version, migration.name, migration.checksum)
        for migration in MIGRATIONS
    ]


def test_apply_migrations_rejects_existing_transaction(tmp_path: Path) -> None:
    connection = sqlite3.connect(
        tmp_path / "nested-transaction.db", isolation_level=None
    )
    try:
        connection.execute("BEGIN")
        with pytest.raises(MigrationError, match="已有事务"):
            apply_migrations(connection)
        assert connection.in_transaction is True
    finally:
        connection.rollback()
        connection.close()


def test_changed_applied_migration_checksum_is_rejected(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    database.initialize()
    changed = Migration(
        version=1,
        name=SCHEMA_V1.name,
        statements=(*SCHEMA_V1.statements, "CREATE TABLE unexpected_change(id TEXT)"),
    )

    connection = database.connect()
    try:
        with pytest.raises(MigrationError, match="checksum 不一致"):
            apply_migrations(connection, (changed, SCHEMA_V2, SCHEMA_V3))
    finally:
        connection.close()


def test_database_version_above_supported_is_rejected(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    database.initialize()
    connection = database.connect()
    try:
        connection.execute(
            """
            INSERT INTO schema_migrations(version, name, checksum, applied_at)
            VALUES (4, 'future', 'future-checksum', '2026-08-05T00:00:00+00:00')
            """
        )
        with pytest.raises(MigrationError, match="程序支持范围"):
            apply_migrations(connection, MIGRATIONS)
    finally:
        connection.close()


def test_failed_migration_rolls_back_schema_and_version_record(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    database.initialize()
    broken = Migration(
        version=4,
        name="broken_migration",
        statements=(
            "CREATE TABLE migration_probe(id TEXT PRIMARY KEY)",
            "INSERT INTO missing_table(id) VALUES ('failure')",
        ),
    )

    connection = database.connect()
    try:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            apply_migrations(connection, (*MIGRATIONS, broken))
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'migration_probe'"
        ).fetchone()
        version = connection.execute(
            "SELECT version FROM schema_migrations WHERE version = 4"
        ).fetchone()
    finally:
        connection.close()
    assert table is None
    assert version is None


def test_migration_definitions_must_be_unique_and_contiguous(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    connection = database.connect()
    duplicate = Migration(version=1, name="duplicate", statements=("SELECT 1",))
    gap = Migration(version=3, name="gap", statements=("SELECT 1",))
    try:
        with pytest.raises(MigrationError, match="不能重复"):
            apply_migrations(connection, (SCHEMA_V1, duplicate))
        with pytest.raises(MigrationError, match="连续递增"):
            apply_migrations(connection, (SCHEMA_V1, gap))
    finally:
        connection.close()


def test_migration_checksum_is_stable_and_sensitive_to_sql() -> None:
    same = Migration(
        version=SCHEMA_V1.version,
        name=SCHEMA_V1.name,
        statements=SCHEMA_V1.statements,
    )
    changed = Migration(
        version=SCHEMA_V1.version,
        name=SCHEMA_V1.name,
        statements=(*SCHEMA_V1.statements, "SELECT 1"),
    )

    assert same.checksum == SCHEMA_V1.checksum
    assert changed.checksum != SCHEMA_V1.checksum


def test_schema_v3_preserves_existing_publication_and_allows_delivery_release(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(tmp_path / "upgrade-v3.db", isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(connection, (SCHEMA_V1, SCHEMA_V2))
        connection.execute(
            """
            INSERT INTO webhook_deliveries(delivery_id, state, updated_at)
            VALUES ('delivery-1', 'processing', '2026-08-05T00:00:00+00:00')
            """
        )
        connection.execute(
            """
            INSERT INTO github_review_publications(
                publication_id, delivery_id, repository_full_name,
                pull_number, head_sha, status, created_at, updated_at
            ) VALUES (
                'publication-1', 'delivery-1', 'openai/devagent',
                42, 'bbbbbbb', 'failed',
                '2026-08-05T00:00:00+00:00', '2026-08-05T00:00:00+00:00'
            )
            """
        )

        apply_migrations(connection, MIGRATIONS)
        connection.execute(
            "DELETE FROM webhook_deliveries WHERE delivery_id = 'delivery-1'"
        )
        publication = connection.execute(
            """
            SELECT delivery_id, status FROM github_review_publications
            WHERE publication_id = 'publication-1'
            """
        ).fetchone()
    finally:
        connection.close()

    assert publication == ("delivery-1", "failed")
