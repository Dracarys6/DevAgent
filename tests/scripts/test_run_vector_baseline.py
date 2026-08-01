from pathlib import Path

import pytest

from scripts.run_vector_baseline import (
    DEFAULT_OUTPUT,
    PROJECT_ROOT,
    _load_live_settings,
)


def clear_embedding_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL",
        "DEVAGENT_EMBEDDING_API_KEY",
        "DEVAGENT_EMBEDDING_MODEL",
        "DEVAGENT_EMBEDDING_BASE_URL",
        "DEVAGENT_EMBEDDING_DIMENSIONS",
        "DEVAGENT_EMBEDDING_BATCH_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "scripts.run_vector_baseline.load_dotenv", lambda **kwargs: False
    )


def test_live_embedding_settings_require_explicit_cost_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_embedding_environment(monkeypatch)

    with pytest.raises(SystemExit, match="显式设置"):
        _load_live_settings()


def test_live_embedding_settings_load_independent_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_embedding_environment(monkeypatch)
    monkeypatch.setenv("DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL", "1")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_API_KEY", "secret-key")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_DIMENSIONS", "1024")

    settings = _load_live_settings()

    assert settings.api_key == "secret-key"
    assert settings.model == "embedding-model"
    assert settings.base_url == "https://example.test/v1"
    assert settings.dimensions == 1024
    assert settings.batch_size == 10


def test_live_embedding_settings_reject_full_resource_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_embedding_environment(monkeypatch)
    monkeypatch.setenv("DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL", "1")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_API_KEY", "secret-key")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv(
        "DEVAGENT_EMBEDDING_BASE_URL",
        "https://example.test/v1/embeddings",
    )

    with pytest.raises(SystemExit, match="不能包含 /embeddings"):
        _load_live_settings()


@pytest.mark.parametrize("dimensions", ["zero", "0", "-1"])
def test_live_embedding_settings_reject_invalid_dimensions(
    monkeypatch: pytest.MonkeyPatch,
    dimensions: str,
) -> None:
    clear_embedding_environment(monkeypatch)
    monkeypatch.setenv("DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL", "1")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_API_KEY", "secret-key")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_DIMENSIONS", dimensions)

    with pytest.raises(SystemExit, match="正整数"):
        _load_live_settings()


@pytest.mark.parametrize("batch_size", ["many", "0", "2049"])
def test_live_embedding_settings_reject_invalid_batch_size(
    monkeypatch: pytest.MonkeyPatch,
    batch_size: str,
) -> None:
    clear_embedding_environment(monkeypatch)
    monkeypatch.setenv("DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL", "1")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_API_KEY", "secret-key")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEVAGENT_EMBEDDING_BATCH_SIZE", batch_size)

    with pytest.raises(SystemExit, match="1 到 2048"):
        _load_live_settings()


def test_default_output_is_inside_project_reports() -> None:
    assert (
        DEFAULT_OUTPUT == PROJECT_ROOT / "eval" / "reports" / "rag_vector_baseline.md"
    )
    assert isinstance(DEFAULT_OUTPUT, Path)
