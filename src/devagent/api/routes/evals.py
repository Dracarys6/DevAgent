import os

from fastapi import APIRouter, HTTPException, Query

from devagent.eval.persistence import (
    EvalRunComparison,
    EvalRunNotFoundError,
    EvalRunRecord,
    SQLiteEvalRunRepository,
)
from devagent.event import EVENT_DATABASE_PATH_ENV
from devagent.storage import SQLiteDatabase, SQLiteSettings

router = APIRouter(prefix="/api/v1/eval/runs", tags=["evaluation"])


def _configured_repository() -> SQLiteEvalRunRepository | None:
    path = os.getenv(EVENT_DATABASE_PATH_ENV)
    if not path:
        return None
    database = SQLiteDatabase(SQLiteSettings(path=path))
    database.initialize()
    return SQLiteEvalRunRepository(database)


repository = _configured_repository()


def _repository() -> SQLiteEvalRunRepository:
    if repository is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation persistence requires DEVAGENT_DATABASE_PATH",
        )
    return repository


@router.get("", response_model=list[EvalRunRecord])
def list_eval_runs(
    eval_type: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[EvalRunRecord]:
    return _repository().list(
        eval_type=eval_type,
        provider=provider,
        model=model,
        limit=limit,
    )


@router.get("/compare", response_model=EvalRunComparison)
def compare_eval_runs(
    baseline_run_id: str,
    candidate_run_id: str,
) -> EvalRunComparison:
    try:
        return _repository().compare(baseline_run_id, candidate_run_id)
    except EvalRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{run_id}", response_model=EvalRunRecord)
def get_eval_run(run_id: str) -> EvalRunRecord:
    try:
        return _repository().get(run_id)
    except EvalRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
