from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes import evals as evals_route
from devagent.eval import EvalRunRecord, EvalRunStatus, SQLiteEvalRunRepository
from devagent.storage import SQLiteDatabase, SQLiteSettings


def make_record(run_id: str, hit_rate: float) -> EvalRunRecord:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return EvalRunRecord(
        run_id=run_id,
        eval_type="rag",
        status=EvalRunStatus.PASSED,
        metrics={"hit_rate": hit_rate},
        started_at=now,
        finished_at=now,
    )


def test_eval_api_lists_gets_and_compares_persisted_runs(tmp_path: Path) -> None:
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "eval-api.db"))
    database.initialize()
    repository = SQLiteEvalRunRepository(database)
    repository.save(make_record("baseline", 0.6))
    repository.save(make_record("candidate", 0.9))
    original = evals_route.repository
    evals_route.repository = repository
    client = TestClient(app)
    try:
        listed = client.get("/api/v1/eval/runs", params={"eval_type": "rag"})
        fetched = client.get("/api/v1/eval/runs/candidate")
        compared = client.get(
            "/api/v1/eval/runs/compare",
            params={
                "baseline_run_id": "baseline",
                "candidate_run_id": "candidate",
            },
        )
    finally:
        evals_route.repository = original

    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == "candidate"
    assert compared.status_code == 200
    assert compared.json()["metric_deltas"]["hit_rate"] == pytest.approx(0.3)


def test_eval_api_requires_persistence_configuration() -> None:
    original = evals_route.repository
    evals_route.repository = None
    try:
        response = TestClient(app).get("/api/v1/eval/runs")
    finally:
        evals_route.repository = original

    assert response.status_code == 503
