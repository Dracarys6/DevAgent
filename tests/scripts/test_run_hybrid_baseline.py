import sys
from pathlib import Path

import pytest

from scripts.run_hybrid_baseline import DEFAULT_OUTPUT, PROJECT_ROOT, main


def test_hybrid_runner_requires_cost_gate_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_created = False

    def reject_settings() -> None:
        raise SystemExit("真实 Embedding Evaluation 未启用")

    def track_client(**kwargs: object) -> object:
        nonlocal client_created
        client_created = True
        return object()

    monkeypatch.setattr(
        "scripts.run_hybrid_baseline.load_live_embedding_settings",
        lambda project_root: reject_settings(),
    )
    monkeypatch.setattr("scripts.run_hybrid_baseline.OpenAI", track_client)
    monkeypatch.setattr(sys, "argv", ["run_hybrid_baseline.py"])

    with pytest.raises(SystemExit, match="未启用"):
        main()

    assert client_created is False


def test_hybrid_runner_rejects_invalid_fusion_config_before_network_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Settings:
        api_key = "secret"
        base_url = "https://example.test/v1"
        model = "embedding-model"
        batch_size = 10
        dimensions = None

    monkeypatch.setattr(
        "scripts.run_hybrid_baseline.load_live_embedding_settings",
        lambda project_root: Settings(),
    )
    monkeypatch.setattr(
        "scripts.run_hybrid_baseline.OpenAI",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_hybrid_baseline.py", "--candidate-k", "0"],
    )

    with pytest.raises(ValueError, match="candidate_k"):
        main()


def test_default_output_is_inside_project_reports() -> None:
    assert (
        DEFAULT_OUTPUT == PROJECT_ROOT / "eval" / "reports" / "rag_hybrid_baseline.md"
    )
    assert isinstance(DEFAULT_OUTPUT, Path)
