from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from devagent.event import redact_sensitive_values
from devagent.storage import SQLiteDatabase

from .models import ToolResult


class ToolCallRecord(BaseModel):
    task_id: str
    tool_call_id: str
    session_id: str | None = None
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: str | None = None
    status: str
    result: ToolResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class ToolCallStore(Protocol):
    def start(self, record: ToolCallRecord) -> None: ...

    def save_result(
        self,
        task_id: str,
        tool_call_id: str,
        *,
        status: str,
        result: ToolResult | None,
        duration_ms: float,
    ) -> None: ...

    def get(self, task_id: str, tool_call_id: str) -> ToolCallRecord: ...

    def list(self, task_id: str) -> list[ToolCallRecord]: ...


class SQLiteToolCallStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def start(self, record: ToolCallRecord) -> None:
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO tool_calls(
                        task_id, tool_call_id, session_id, tool_name,
                        arguments_json, risk_level, status, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id, tool_call_id) DO NOTHING
                    """,
                    (
                        record.task_id,
                        record.tool_call_id,
                        record.session_id,
                        record.tool_name,
                        json.dumps(
                            redact_sensitive_values(record.arguments),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        record.risk_level,
                        record.status,
                        record.started_at.isoformat(),
                    ),
                )
        except sqlite3.Error as exc:
            raise RuntimeError("保存工具调用失败") from exc

    def save_result(
        self,
        task_id: str,
        tool_call_id: str,
        *,
        status: str,
        result: ToolResult | None,
        duration_ms: float,
    ) -> None:
        finished_at = None if status == "WAITING_PERMISSION" else datetime.now(UTC)
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE tool_calls
                    SET status = ?, result_json = ?, error_code = ?,
                        error_message = ?, duration_ms = ?, finished_at = ?
                    WHERE task_id = ? AND tool_call_id = ?
                    """,
                    (
                        status,
                        result.model_dump_json() if result else None,
                        result.error_code.value
                        if result and result.error_code
                        else None,
                        result.error_message if result else None,
                        duration_ms,
                        finished_at.isoformat() if finished_at else None,
                        task_id,
                        tool_call_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise RuntimeError("工具调用不存在")
        except sqlite3.Error as exc:
            raise RuntimeError("更新工具调用失败") from exc

    def get(self, task_id: str, tool_call_id: str) -> ToolCallRecord:
        connection = self._database.connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM tool_calls
                WHERE task_id = ? AND tool_call_id = ?
                """,
                (task_id, tool_call_id),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(f"工具调用不存在: {task_id}/{tool_call_id}")
        return _record_from_row(row)

    def list(self, task_id: str) -> list[ToolCallRecord]:
        connection = self._database.connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM tool_calls
                WHERE task_id = ? ORDER BY started_at, tool_call_id
                """,
                (task_id,),
            ).fetchall()
        finally:
            connection.close()
        return [_record_from_row(row) for row in rows]


def _record_from_row(row: sqlite3.Row) -> ToolCallRecord:
    return ToolCallRecord.model_validate(
        {
            "task_id": row["task_id"],
            "tool_call_id": row["tool_call_id"],
            "session_id": row["session_id"],
            "tool_name": row["tool_name"],
            "arguments": json.loads(row["arguments_json"]),
            "risk_level": row["risk_level"],
            "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "duration_ms": row["duration_ms"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
    )
