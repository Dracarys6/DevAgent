from pathlib import Path

import pytest

from scripts.run_live_ci_diagnosis import (
    DEFAULT_OUTPUT,
    DEFAULT_WORKSPACE,
    PROJECT_ROOT,
    _load_live_settings,
    _workspace_label,
)


def test_live_ci_settings_require_explicit_cost_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVAGENT_ENABLE_LIVE_EVAL", raising=False)
    monkeypatch.setattr(
        "scripts.run_live_ci_diagnosis.load_dotenv",
        lambda **kwargs: False,
    )

    with pytest.raises(SystemExit, match="显式设置"):
        _load_live_settings()


def test_live_ci_settings_load_provider_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.run_live_ci_diagnosis.load_dotenv",
        lambda **kwargs: True,
    )
    monkeypatch.setenv("DEVAGENT_ENABLE_LIVE_EVAL", "1")
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "live-model")
    monkeypatch.setenv("DEVAGENT_LLM_API_MODE", "responses")

    settings = _load_live_settings()

    assert settings["api_key"] == "secret-key"
    assert settings["model"] == "live-model"
    assert settings["api_mode"] == "responses"


def test_live_ci_defaults_and_workspace_label_are_project_relative(
    tmp_path: Path,
) -> None:
    assert DEFAULT_WORKSPACE == PROJECT_ROOT / "examples" / "sample_repo"
    assert DEFAULT_OUTPUT == PROJECT_ROOT / "eval" / "reports" / "ci_diagnosis_live.md"
    assert _workspace_label(DEFAULT_WORKSPACE) == "examples/sample_repo"
    assert _workspace_label(tmp_path) == tmp_path.name
