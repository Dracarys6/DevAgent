from pathlib import Path

import pytest

from devagent.eval import RAGEvalCase
from scripts.run_live_rag_eval import (
    DEFAULT_LIVE_CASE_IDS,
    _load_live_settings,
    _select_cases,
)


def make_cases() -> list[RAGEvalCase]:
    cases = [
        RAGEvalCase(
            case_id=case_id,
            description=f"case {case_id}",
            category="negative" if case_id.startswith("negative-") else "code",
            query=case_id,
            expect_empty=case_id.startswith("negative-"),
            expected_paths=[] if case_id.startswith("negative-") else ["src/app.py"],
            expected_keywords=[] if case_id.startswith("negative-") else ["alpha"],
        )
        for case_id in DEFAULT_LIVE_CASE_IDS
    ]
    return cases


def test_live_settings_require_explicit_cost_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVAGENT_ENABLE_LIVE_EVAL", raising=False)
    monkeypatch.setattr("scripts.run_live_rag_eval.load_dotenv", lambda **kwargs: False)

    with pytest.raises(SystemExit, match="显式设置"):
        _load_live_settings()


def test_live_settings_load_provider_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("scripts.run_live_rag_eval.load_dotenv", lambda **kwargs: True)
    monkeypatch.setenv("DEVAGENT_ENABLE_LIVE_EVAL", "1")
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "live-model")
    monkeypatch.setenv("DEVAGENT_LLM_API_MODE", "responses")

    settings = _load_live_settings()

    assert settings["api_key"] == "secret-key"
    assert settings["model"] == "live-model"
    assert settings["api_mode"] == "responses"


def test_select_cases_uses_stratified_live_default() -> None:
    selected = _select_cases(
        make_cases(),
        requested_case_ids=[],
        all_cases=False,
    )

    assert [case.case_id for case in selected] == list(DEFAULT_LIVE_CASE_IDS)
    assert sum(case.expect_empty for case in selected) == 2


def test_select_cases_rejects_unknown_or_unbalanced_selection() -> None:
    cases = make_cases()
    with pytest.raises(SystemExit, match="未知"):
        _select_cases(
            cases,
            requested_case_ids=["missing"],
            all_cases=False,
        )

    with pytest.raises(SystemExit, match="负样本"):
        _select_cases(
            cases,
            requested_case_ids=["event-bus-publish"],
            all_cases=False,
        )


def test_default_output_is_inside_project_reports() -> None:
    from scripts.run_live_rag_eval import DEFAULT_OUTPUT, PROJECT_ROOT

    assert DEFAULT_OUTPUT == PROJECT_ROOT / "eval" / "reports" / "rag_live_provider.md"
    assert isinstance(DEFAULT_OUTPUT, Path)
