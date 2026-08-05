from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from devagent.event import redact_sensitive_values
from devagent.storage import SQLiteDatabase


class EvalRunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"


class EvalRunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    eval_type: str = Field(min_length=1)
    dataset_id: str | None = None
    provider: str | None = None
    model: str | None = None
    api_mode: str | None = None
    status: EvalRunStatus
    config: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    schema_valid: bool = True
    started_at: datetime
    finished_at: datetime | None = None
    latency_ms: float | None = Field(default=None, ge=0)


class EvalRunComparison(BaseModel):
    baseline_run_id: str
    candidate_run_id: str
    eval_type: str
    metric_deltas: dict[str, float]


class EvalRunNotFoundError(KeyError):
    pass


class EvalRunPersistenceError(RuntimeError):
    pass


class SQLiteEvalRunRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, record: EvalRunRecord) -> EvalRunRecord:
        sanitized = record.model_copy(
            update={
                "config": redact_sensitive_values(record.config),
                "result": redact_sensitive_values(record.result),
            }
        )
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO eval_runs(
                        run_id, eval_type, dataset_id, provider, model, api_mode,
                        status, config_json, metrics_json, result_json,
                        schema_valid, started_at, finished_at, latency_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sanitized.run_id,
                        sanitized.eval_type,
                        sanitized.dataset_id,
                        sanitized.provider,
                        sanitized.model,
                        sanitized.api_mode,
                        sanitized.status.value,
                        json.dumps(
                            sanitized.config, ensure_ascii=False, sort_keys=True
                        ),
                        json.dumps(
                            sanitized.metrics, ensure_ascii=False, sort_keys=True
                        ),
                        json.dumps(
                            sanitized.result, ensure_ascii=False, sort_keys=True
                        ),
                        int(sanitized.schema_valid),
                        sanitized.started_at.isoformat(),
                        sanitized.finished_at.isoformat()
                        if sanitized.finished_at
                        else None,
                        sanitized.latency_ms,
                    ),
                )
        except sqlite3.Error as exc:
            raise EvalRunPersistenceError("保存评测运行失败") from exc
        return sanitized

    def get(self, run_id: str) -> EvalRunRecord:
        connection = self._database.connect()
        try:
            row = connection.execute(
                "SELECT * FROM eval_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise EvalRunPersistenceError("读取评测运行失败") from exc
        finally:
            connection.close()
        if row is None:
            raise EvalRunNotFoundError(f"评测运行不存在: {run_id}")
        return _record_from_row(row)

    def list(
        self,
        *,
        eval_type: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        limit: int = 100,
    ) -> list[EvalRunRecord]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit 必须位于 1 到 1000")
        clauses: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("eval_type", eval_type),
            ("provider", provider),
            ("model", model),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        query = "SELECT * FROM eval_runs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY started_at DESC, run_id DESC LIMIT ?"
        values.append(limit)
        connection = self._database.connect()
        try:
            rows = connection.execute(query, values).fetchall()
        finally:
            connection.close()
        return [_record_from_row(row) for row in rows]

    def compare(self, baseline_run_id: str, candidate_run_id: str) -> EvalRunComparison:
        baseline = self.get(baseline_run_id)
        candidate = self.get(candidate_run_id)
        if baseline.eval_type != candidate.eval_type:
            raise ValueError("只能比较相同 eval_type 的评测运行")
        deltas = {
            key: float(candidate.metrics[key]) - float(value)
            for key, value in baseline.metrics.items()
            if _is_number(value) and _is_number(candidate.metrics.get(key))
        }
        return EvalRunComparison(
            baseline_run_id=baseline.run_id,
            candidate_run_id=candidate.run_id,
            eval_type=baseline.eval_type,
            metric_deltas=deltas,
        )


def build_eval_run_record(
    *,
    eval_type: str,
    run: BaseModel,
    dataset_id: str | None = None,
    config: dict[str, Any] | None = None,
) -> EvalRunRecord:
    result = run.model_dump(mode="json")
    raw_metrics = result.get("metrics", {})
    if not isinstance(raw_metrics, dict):
        raise TypeError("评测 run.metrics 必须是对象")
    latency = result.get("latency_ms")
    latency_ms = float(latency) if _is_number(latency) else None
    finished_at = datetime.now(UTC)
    started_at = (
        finished_at - timedelta(milliseconds=latency_ms)
        if latency_ms is not None
        else finished_at
    )
    passed = raw_metrics.get("passed")
    status = (
        EvalRunStatus.PASSED
        if passed is True
        else EvalRunStatus.FAILED
        if passed is False
        else EvalRunStatus.COMPLETED
    )
    return EvalRunRecord(
        eval_type=eval_type,
        dataset_id=dataset_id,
        provider=_optional_string(result.get("provider")),
        model=_optional_string(result.get("model")),
        api_mode=_optional_string(result.get("api_mode")),
        status=status,
        config=config or {},
        metrics=raw_metrics,
        result=result,
        schema_valid=True,
        started_at=started_at,
        finished_at=finished_at,
        latency_ms=latency_ms,
    )


def _record_from_row(row: sqlite3.Row) -> EvalRunRecord:
    return EvalRunRecord.model_validate(
        {
            "run_id": row["run_id"],
            "eval_type": row["eval_type"],
            "dataset_id": row["dataset_id"],
            "provider": row["provider"],
            "model": row["model"],
            "api_mode": row["api_mode"],
            "status": row["status"],
            "config": json.loads(row["config_json"]),
            "metrics": json.loads(row["metrics_json"]),
            "result": json.loads(row["result_json"]),
            "schema_valid": bool(row["schema_valid"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "latency_ms": row["latency_ms"],
        }
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
