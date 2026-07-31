from pathlib import Path

import pytest

from scripts.run_live_log_diagnosis import (
    DEFAULT_DATA_DIR,
    DEFAULT_EXPECTED_KEYWORDS,
    DEFAULT_OUTPUT,
    DEFAULT_TARGET,
    PROJECT_ROOT,
    _data_dir_label,
    _load_live_settings,
)


def test_live_log_settings_require_explicit_cost_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVAGENT_ENABLE_LIVE_EVAL", raising=False)
    monkeypatch.setattr(
        "scripts.run_live_log_diagnosis.load_dotenv",
        lambda **kwargs: False,
    )

    with pytest.raises(SystemExit, match="显式设置"):
        _load_live_settings()


def test_live_log_settings_load_provider_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.run_live_log_diagnosis.load_dotenv",
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


def test_live_log_defaults_define_real_fixture(tmp_path: Path) -> None:
    assert DEFAULT_TARGET == "task_001"
    assert DEFAULT_DATA_DIR == PROJECT_ROOT / "examples" / "sample_logs"
    assert DEFAULT_OUTPUT == PROJECT_ROOT / "eval" / "reports" / "log_diagnosis_live.md"
    assert DEFAULT_EXPECTED_KEYWORDS == [
        "UploadTimeoutError",
        "RetryExhaustedError",
        "3 秒",
    ]
    assert _data_dir_label(DEFAULT_DATA_DIR) == "examples/sample_logs"
    assert _data_dir_label(tmp_path) == tmp_path.name
