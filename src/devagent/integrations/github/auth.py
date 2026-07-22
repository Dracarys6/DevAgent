from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
import threading
from typing import Any, Protocol

import jwt
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

GITHUB_API_VERSION = "2026-03-10"
DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
TOKEN_REFRESH_MARGIN = timedelta(seconds=60)


class GitHubAuthenticationError(RuntimeError):
    """GitHub App 无法安全获取 installation access token。"""


class GitHubHTTPResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class GitHubHTTPClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
        timeout: float,
    ) -> GitHubHTTPResponse: ...


class GitHubAuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitHubAppCredentials(GitHubAuthModel):
    client_id: str = Field(min_length=1, max_length=255)
    private_key_path: Path

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("GitHub App client_id 不能包含首尾空白")
        return value


class InstallationToken(GitHubAuthModel):
    token: SecretStr
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("expires_at 必须包含时区")
        return value.astimezone(UTC)


class GitHubInstallationTokenProvider:
    """生成短期 App JWT，并按 installation 缓存短期 access token。"""

    def __init__(
        self,
        *,
        credentials: GitHubAppCredentials,
        http_client: GitHubHTTPClient,
        api_base_url: str = DEFAULT_GITHUB_API_BASE_URL,
        timeout_seconds: float = 10.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        normalized_base_url = api_base_url.rstrip("/")
        if not normalized_base_url.startswith("https://"):
            raise ValueError("GitHub API base URL 必须使用 HTTPS")
        self._credentials = credentials
        self._http_client = http_client
        self._api_base_url = normalized_base_url
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tokens: dict[int, InstallationToken] = {}
        self._lock = threading.Lock()

    def get_token(self, installation_id: int) -> SecretStr:
        if isinstance(installation_id, bool) or installation_id < 1:
            raise ValueError("installation_id 必须大于或等于 1")
        with self._lock:
            now = _ensure_aware_utc(self._clock())
            cached = self._tokens.get(installation_id)
            if cached and cached.expires_at - now > TOKEN_REFRESH_MARGIN:
                return SecretStr(cached.token.get_secret_value())
            token = self._request_token(installation_id=installation_id, now=now)
            self._tokens[installation_id] = token
            return SecretStr(token.token.get_secret_value())

    def _request_token(
        self,
        *,
        installation_id: int,
        now: datetime,
    ) -> InstallationToken:
        app_jwt = self._build_app_jwt(now)
        try:
            response = self._http_client.request(
                "POST",
                f"{self._api_base_url}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {app_jwt}",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                    "User-Agent": "DevAgent/0.1.0",
                },
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise GitHubAuthenticationError(
                "GitHub installation token 请求失败"
            ) from exc
        if response.status_code != 201:
            raise GitHubAuthenticationError(
                f"GitHub installation token 请求被拒绝: status={response.status_code}"
            )
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("token response 必须是 object")
            raw_token = payload["token"]
            raw_expiry = payload["expires_at"]
            if not isinstance(raw_token, str) or not raw_token:
                raise ValueError("token 不能为空")
            if not isinstance(raw_expiry, str):
                raise TypeError("expires_at 必须是字符串")
            expires_at = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
            token = InstallationToken(
                token=SecretStr(raw_token),
                expires_at=expires_at,
            )
        except Exception as exc:
            raise GitHubAuthenticationError(
                "GitHub installation token 响应格式无效"
            ) from exc
        if token.expires_at <= now + TOKEN_REFRESH_MARGIN:
            raise GitHubAuthenticationError("GitHub installation token 有效期不足")
        return token

    def _build_app_jwt(self, now: datetime) -> str:
        try:
            private_key = self._credentials.private_key_path.read_text(
                encoding="utf-8"
            )
            return jwt.encode(
                {
                    "iat": int(now.timestamp()) - 60,
                    "exp": int(now.timestamp()) + 9 * 60,
                    "iss": self._credentials.client_id,
                },
                private_key,
                algorithm="RS256",
            )
        except Exception as exc:
            raise GitHubAuthenticationError("无法生成 GitHub App JWT") from exc


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise GitHubAuthenticationError("GitHub token provider 时钟必须包含时区")
    return value.astimezone(UTC)
