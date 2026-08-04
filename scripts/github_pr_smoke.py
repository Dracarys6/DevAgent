import os
from argparse import ArgumentParser, Namespace
from pathlib import Path

import httpx
from dotenv import load_dotenv

from devagent.integrations.github import (
    ControlledGitHubWorkspace,
    GitHubAppCredentials,
    GitHubInstallationTokenProvider,
    GitHubIntegrationSettings,
    RealGitHubClient,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
    _require_explicit_enable()
    settings = _load_settings()
    _validate_local_files(settings)

    print("GitHub smoke 配置预检通过")
    print(f"允许仓库: {settings.allowed_repository}")
    print(f"受控 workspace: {settings.workspace.expanduser().resolve()}")
    if args.check_config and args.pull_number is None:
        return
    if args.pull_number is None:
        parser.error("只读 PR 探测需要 --pull-number")
    installation_id = _load_installation_id(args)
    _probe_pull_request(
        settings=settings,
        installation_id=installation_id,
        pull_number=args.pull_number,
    )


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="显式执行真实 GitHub PR smoke 预检")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="只校验本地 GitHub App 配置",
    )
    parser.add_argument(
        "--pull-number",
        type=int,
        help="使用真实 GitHub API 只读探测该 Pull Request",
    )
    parser.add_argument(
        "--installation-id",
        type=int,
        help="GitHub App installation ID；默认读取环境变量",
    )
    return parser


def _require_explicit_enable() -> None:
    if os.getenv("DEVAGENT_ENABLE_GITHUB_SMOKE") != "1":
        raise SystemExit(
            "真实 GitHub smoke 未启用；请显式设置 DEVAGENT_ENABLE_GITHUB_SMOKE=1"
        )


def _load_settings() -> GitHubIntegrationSettings:
    values = {
        "app_client_id": os.getenv("DEVAGENT_GITHUB_APP_CLIENT_ID"),
        "app_private_key_path": os.getenv("DEVAGENT_GITHUB_APP_PRIVATE_KEY_PATH"),
        "allowed_repository": os.getenv("DEVAGENT_GITHUB_ALLOWED_REPOSITORY"),
        "workspace": os.getenv("DEVAGENT_GITHUB_WORKSPACE"),
        "api_base_url": os.getenv(
            "DEVAGENT_GITHUB_API_BASE_URL", "https://api.github.com"
        ),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SystemExit("GitHub smoke 配置不完整，请检查 .env.example 中的变量")
    try:
        return GitHubIntegrationSettings.model_validate(values)
    except Exception as exc:
        raise SystemExit("GitHub smoke 配置格式无效") from exc


def _validate_local_files(settings: GitHubIntegrationSettings) -> None:
    if not settings.app_private_key_path.expanduser().resolve().is_file():
        raise SystemExit("GitHub App private key 文件不存在")
    if not settings.workspace.expanduser().resolve().is_dir():
        raise SystemExit("GitHub smoke workspace 不存在")


def _load_installation_id(args: Namespace) -> int:
    raw_value = args.installation_id or os.getenv("DEVAGENT_GITHUB_INSTALLATION_ID")
    try:
        installation_id = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise SystemExit("缺少有效的 GitHub App installation ID") from exc
    if installation_id < 1:
        raise SystemExit("GitHub App installation ID 必须大于 0")
    return installation_id


def _probe_pull_request(
    *,
    settings: GitHubIntegrationSettings,
    installation_id: int,
    pull_number: int,
) -> None:
    workspace = settings.workspace.expanduser().resolve()
    with httpx.Client() as http_client:
        token_provider = GitHubInstallationTokenProvider(
            credentials=GitHubAppCredentials(
                client_id=settings.app_client_id,
                private_key_path=settings.app_private_key_path.expanduser().resolve(),
            ),
            http_client=http_client,
            api_base_url=settings.api_base_url,
            timeout_seconds=settings.api_timeout_seconds,
        )
        workspace_provider = ControlledGitHubWorkspace(
            allowed_repository=settings.allowed_repository,
            workspace=workspace,
            allowed_root=workspace.parent,
            timeout_seconds=settings.git_timeout_seconds,
        )
        client = RealGitHubClient(
            installation_id=installation_id,
            token_provider=token_provider,
            workspace_provider=workspace_provider,
            http_client=http_client,
            api_base_url=settings.api_base_url,
            timeout_seconds=settings.api_timeout_seconds,
        )
        pull_request = client.get_pull_request(
            repository=settings.allowed_repository,
            number=pull_number,
        )

    print("真实 GitHub Pull Request 只读探测通过")
    print(f"PR: {settings.allowed_repository}#{pull_number}")
    print(f"Base SHA: {pull_request.base_ref}")
    print(f"Head SHA: {pull_request.head_sha}")
    print(f"可定位 diff 行数: {len(pull_request.diff_lines)}")


if __name__ == "__main__":
    main()
