import sys
from pathlib import Path

import pytest

from devagent.eval import RAGEvalCase
from scripts.run_live_rerank_eval import (
    DEFAULT_LIVE_CASE_IDS,
    DEFAULT_OUTPUT,
    PROJECT_ROOT,
    _load_live_llm_settings,
    _select_cases,
    main,
)


def make_cases() -> list[RAGEvalCase]:
    return [
        RAGEvalCase(
            case_id=case_id,
            description=case_id,
            category="negative" if case_id.startswith("negative-") else "code",
            query=case_id,
            expect_empty=case_id.startswith("negative-"),
            expected_paths=[] if case_id.startswith("negative-") else ["src/app.py"],
            expected_keywords=[] if case_id.startswith("negative-") else ["signal"],
        )
        for case_id in DEFAULT_LIVE_CASE_IDS
    ]


def test_runner_checks_embedding_gate_before_creating_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_created = False

    def reject_gate(project_root: Path) -> object:
        raise SystemExit("embedding gate disabled")

    def track_client(**kwargs: object) -> object:
        nonlocal client_created
        client_created = True
        return object()

    monkeypatch.setattr(
        "scripts.run_live_rerank_eval.load_live_embedding_settings", reject_gate
    )
    monkeypatch.setattr("scripts.run_live_rerank_eval.OpenAI", track_client)
    monkeypatch.setattr(sys, "argv", ["run_live_rerank_eval.py"])

    with pytest.raises(SystemExit, match="embedding gate"):
        main()

    assert client_created is False


def test_live_llm_settings_require_explicit_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.run_live_rerank_eval.load_dotenv", lambda **kwargs: False
    )
    monkeypatch.delenv("DEVAGENT_ENABLE_LIVE_EVAL", raising=False)

    with pytest.raises(SystemExit, match="显式设置"):
        _load_live_llm_settings()


def test_live_llm_settings_load_sanitized_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.run_live_rerank_eval.load_dotenv", lambda **kwargs: True
    )
    monkeypatch.setenv("DEVAGENT_ENABLE_LIVE_EVAL", "1")
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "secret")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "live-reranker")
    monkeypatch.setenv("DEVAGENT_LLM_API_MODE", "chat_completions")

    settings = _load_live_llm_settings()

    assert settings.api_key == "secret"
    assert settings.model == "live-reranker"
    assert settings.api_mode == "chat_completions"


def test_select_cases_uses_rank_gap_and_balanced_defaults() -> None:
    selected = _select_cases(
        make_cases(),
        requested_case_ids=[],
        all_cases=False,
    )

    assert [case.case_id for case in selected] == list(DEFAULT_LIVE_CASE_IDS)
    assert selected[0].case_id == "github-inline-fallback"
    assert sum(case.expect_empty for case in selected) == 2


def test_select_cases_rejects_unknown_and_unbalanced_cases() -> None:
    cases = make_cases()
    with pytest.raises(SystemExit, match="未知"):
        _select_cases(cases, requested_case_ids=["missing"], all_cases=False)
    with pytest.raises(SystemExit, match="负样本"):
        _select_cases(
            cases,
            requested_case_ids=["github-inline-fallback"],
            all_cases=False,
        )


def test_default_output_is_inside_project_reports() -> None:
    assert DEFAULT_OUTPUT == PROJECT_ROOT / "eval" / "reports" / "rag_rerank_live.md"
    assert isinstance(DEFAULT_OUTPUT, Path)
