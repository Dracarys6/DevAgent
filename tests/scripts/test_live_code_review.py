from pathlib import Path

import pytest

from devagent.review import ReviewSeverity

from scripts.run_live_code_review import (
    DEFAULT_BASE_REF,
    DEFAULT_EXPECTED_FINDING,
    DEFAULT_HEAD_REF,
    DEFAULT_OUTPUT,
    DEFAULT_WORKSPACE,
    PROJECT_ROOT,
    _load_live_settings,
    _workspace_label,
)


def test_live_review_settings_require_explicit_cost_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVAGENT_ENABLE_LIVE_EVAL", raising=False)
    monkeypatch.setattr(
        "scripts.run_live_code_review.load_dotenv",
        lambda **kwargs: False,
    )

    with pytest.raises(SystemExit, match="显式设置"):
        _load_live_settings()


def test_live_review_settings_load_provider_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.run_live_code_review.load_dotenv",
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


def test_live_review_defaults_define_real_local_case(tmp_path: Path) -> None:
    assert DEFAULT_BASE_REF == "7229c86^"
    assert DEFAULT_HEAD_REF == "7229c86"
    assert DEFAULT_WORKSPACE == PROJECT_ROOT / "examples" / "sample_repo"
    assert DEFAULT_OUTPUT == PROJECT_ROOT / "eval" / "reports" / "code_review_live.md"
    assert DEFAULT_EXPECTED_FINDING.file_path == "src/sample_app/uploader.py"
    assert DEFAULT_EXPECTED_FINDING.line == 24
    assert ReviewSeverity.MEDIUM in DEFAULT_EXPECTED_FINDING.severities
    assert _workspace_label(DEFAULT_WORKSPACE) == "examples/sample_repo"
    assert _workspace_label(tmp_path) == tmp_path.name
