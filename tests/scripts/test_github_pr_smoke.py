from argparse import Namespace
from pathlib import Path

import pytest

from devagent.integrations.github import GitHubIntegrationSettings
from scripts.github_pr_smoke import (
    _load_installation_id,
    _require_explicit_enable,
    _validate_local_files,
    main,
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


def test_main_loads_dotenv_before_checking_enable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("DEVAGENT_ENABLE_GITHUB_SMOKE=1\n", encoding="utf-8")
    monkeypatch.setattr("scripts.github_pr_smoke.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["github_pr_smoke.py", "--check-config"])
    monkeypatch.delenv("DEVAGENT_ENABLE_GITHUB_SMOKE", raising=False)
    for variable in (
        "DEVAGENT_GITHUB_APP_CLIENT_ID",
        "DEVAGENT_GITHUB_APP_PRIVATE_KEY_PATH",
        "DEVAGENT_GITHUB_ALLOWED_REPOSITORY",
        "DEVAGENT_GITHUB_WORKSPACE",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(SystemExit, match="配置不完整"):
        main()
