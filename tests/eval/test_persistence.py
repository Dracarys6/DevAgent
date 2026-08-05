from pathlib import Path

import pytest
from pydantic import BaseModel

from devagent.eval import (
    EvalRunStatus,
    LiveCIDiagnosisMetrics,
    LiveCIDiagnosisRun,
    SQLiteEvalRunRepository,
    build_eval_run_record,
)
from devagent.storage import SQLiteDatabase, SQLiteSettings


class SampleMetrics(BaseModel):
    hit_rate: float
    latency_p95_ms: float
    passed: bool


class SampleRun(BaseModel):
    provider: str
    model: str
    api_mode: str
    latency_ms: float
    metrics: SampleMetrics


def make_repository(tmp_path: Path) -> SQLiteEvalRunRepository:
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "eval.db"))
    database.initialize()
    return SQLiteEvalRunRepository(database)


def make_run(hit_rate: float, *, passed: bool = True) -> SampleRun:
    return SampleRun(
        provider="openai-compatible",
        model="deepseek-chat",
        api_mode="chat_completions",
        latency_ms=120,
        metrics=SampleMetrics(
            hit_rate=hit_rate,
            latency_p95_ms=20,
            passed=passed,
        ),
    )


def test_eval_run_survives_repository_reconstruction(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    record = build_eval_run_record(
        eval_type="rag_live",
        dataset_id="rag-v1",
        run=make_run(0.8),
        config={"top_k": 5, "api_key": "secret"},
    )
    saved = repository.save(record)

    restored = make_repository(tmp_path).get(saved.run_id)

    assert restored.status == EvalRunStatus.PASSED
    assert restored.metrics["hit_rate"] == 0.8
    assert restored.config == {"top_k": 5, "api_key": "[REDACTED]"}
    assert restored.schema_valid is True


def test_eval_run_list_filters_and_limits(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    repository.save(build_eval_run_record(eval_type="rag", run=make_run(0.7)))
    repository.save(build_eval_run_record(eval_type="review", run=make_run(0.9)))

    records = repository.list(eval_type="rag", provider="openai-compatible")

    assert len(records) == 1
    assert records[0].eval_type == "rag"
    with pytest.raises(ValueError, match="limit"):
        repository.list(limit=0)


def test_eval_run_comparison_calculates_numeric_metric_deltas(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    baseline = repository.save(
        build_eval_run_record(eval_type="rag", run=make_run(0.6))
    )
    candidate = repository.save(
        build_eval_run_record(eval_type="rag", run=make_run(0.85))
    )

    comparison = repository.compare(baseline.run_id, candidate.run_id)

    assert comparison.metric_deltas == {
        "hit_rate": pytest.approx(0.25),
        "latency_p95_ms": 0,
    }


def test_eval_run_comparison_rejects_different_eval_types(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    baseline = repository.save(
        build_eval_run_record(eval_type="rag", run=make_run(0.6))
    )
    candidate = repository.save(
        build_eval_run_record(eval_type="review", run=make_run(0.8))
    )

    with pytest.raises(ValueError, match="相同 eval_type"):
        repository.compare(baseline.run_id, candidate.run_id)


def test_build_record_adapts_existing_live_diagnosis_contract() -> None:
    run = LiveCIDiagnosisRun(
        provider="deepseek",
        model="deepseek-chat",
        api_mode="chat_completions",
        target="abc123",
        workspace_label="sample",
        expected_keywords=["timeout"],
        latency_ms=321,
        attempt_count=1,
        metrics=LiveCIDiagnosisMetrics(
            diagnosed=False,
            required_evidence_covered=False,
            evidence_references_grounded=False,
            root_cause_finding_count=0,
            recommendation_count=0,
            expected_keyword_hit_count=0,
            expected_keyword_count=1,
            expected_keyword_hit_rate=0,
            passed=False,
        ),
    )

    record = build_eval_run_record(eval_type="ci_diagnosis_live", run=run)

    assert record.provider == "deepseek"
    assert record.status == EvalRunStatus.FAILED
    assert record.latency_ms == 321
    assert record.result["target"] == "abc123"
