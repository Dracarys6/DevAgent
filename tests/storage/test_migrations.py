import sqlite3
from pathlib import Path

import pytest

from devagent.storage import (
    MIGRATIONS,
    SCHEMA_V1,
    Migration,
    MigrationError,
    SQLiteDatabase,
    SQLiteSettings,
    apply_migrations,
)


def make_database(tmp_path: Path) -> SQLiteDatabase:
    return SQLiteDatabase(SQLiteSettings(path=tmp_path / "devagent.db"))


def test_schema_v1_is_recorded_once(tmp_path: Path) -> None:
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
    assert len(rows) == 1
    assert dict(rows[0]) == {
        "version": 1,
        "name": SCHEMA_V1.name,
        "checksum": SCHEMA_V1.checksum,
    }


def test_apply_migrations_supports_default_tuple_rows(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "plain-connection.db", isolation_level=None)
    try:
        apply_migrations(connection)
        row = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchone()
    finally:
        connection.close()

    assert row == (SCHEMA_V1.version, SCHEMA_V1.name, SCHEMA_V1.checksum)


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
            apply_migrations(connection, (changed,))
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
            VALUES (2, 'future', 'future-checksum', '2026-08-05T00:00:00+00:00')
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
        version=2,
        name="broken_migration",
        statements=(
            "CREATE TABLE migration_probe(id TEXT PRIMARY KEY)",
            "INSERT INTO missing_table(id) VALUES ('failure')",
        ),
    )

    connection = database.connect()
    try:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            apply_migrations(connection, (SCHEMA_V1, broken))
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'migration_probe'"
        ).fetchone()
        version = connection.execute(
            "SELECT version FROM schema_migrations WHERE version = 2"
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
