from argparse import Namespace
from pathlib import Path

import pytest

from devagent.integrations.github import GitHubIntegrationSettings
from scripts.github_pr_smoke import (
    _load_installation_id,
    _require_explicit_enable,
    _validate_local_files,
)


def test_smoke_requires_explicit_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVAGENT_ENABLE_GITHUB_SMOKE", raising=False)

    with pytest.raises(SystemExit, match="显式设置"):
        _require_explicit_enable()

    monkeypatch.setenv("DEVAGENT_ENABLE_GITHUB_SMOKE", "1")
    _require_explicit_enable()


def test_installation_id_uses_argument_then_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVAGENT_GITHUB_INSTALLATION_ID", "456")

    assert _load_installation_id(Namespace(installation_id=123)) == 123
    assert _load_installation_id(Namespace(installation_id=None)) == 456


def test_smoke_rejects_missing_local_files(tmp_path: Path) -> None:
    settings = GitHubIntegrationSettings(
        app_client_id="Iv1.devagent",
        app_private_key_path=tmp_path / "missing.pem",
        allowed_repository="openai/devagent",
        workspace=tmp_path / "missing-workspace",
    )

    with pytest.raises(SystemExit, match="private key"):
        _validate_local_files(settings)
