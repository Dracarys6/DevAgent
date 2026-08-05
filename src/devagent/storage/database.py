from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .migrations import apply_migrations


@dataclass(frozen=True)
class SQLiteSettings:
    path: Path
    busy_timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        path = Path(self.path).expanduser()
        if path.name in {"", ".", ".."} or path.is_dir():
            raise ValueError("SQLite path 必须指向数据库文件")
        if str(path) == ":memory:":
            raise ValueError("SQLiteDatabase 使用短连接，不支持独立的 :memory: 数据库")
        if isinstance(self.busy_timeout_ms, bool) or not isinstance(
            self.busy_timeout_ms, int
        ):
            raise TypeError("busy_timeout_ms 必须是整数")
        if not 1 <= self.busy_timeout_ms <= 600_000:
            raise ValueError("busy_timeout_ms 必须位于 1 到 600000")
        object.__setattr__(self, "path", path.resolve())


class SQLiteDatabase:
    """为同步 Repository 提供统一连接、migration 与短事务边界。"""

    def __init__(self, settings: SQLiteSettings) -> None:
        self.settings = settings

    def initialize(self) -> None:
        self.settings.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise RuntimeError("SQLite 文件数据库无法启用 WAL")
            apply_migrations(connection)
        finally:
            connection.close()

    def connect(self) -> sqlite3.Connection:
        self.settings.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.settings.path,
            timeout=self.settings.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {self.settings.busy_timeout_ms}")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
