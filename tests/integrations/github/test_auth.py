from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from devagent.integrations.github.auth import (
    GITHUB_API_VERSION,
    GitHubAppCredentials,
    GitHubAuthenticationError,
    GitHubInstallationTokenProvider,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> Any:
        return self.payload


class FakeHTTPClient:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def rsa_key_pair(tmp_path: Path) -> tuple[Path, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_path = tmp_path / "github-app.pem"
    key_path.write_bytes(private_bytes)
    return key_path, public_bytes


def make_token_response(token: str, expires_at: datetime) -> FakeResponse:
    return FakeResponse(
        201,
        {
            "token": token,
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        },
    )


def make_provider(
    *,
    key_path: Path,
    client: FakeHTTPClient,
    clock: MutableClock,
) -> GitHubInstallationTokenProvider:
    return GitHubInstallationTokenProvider(
        credentials=GitHubAppCredentials(
            client_id="Iv1.devagent",
            private_key_path=key_path,
        ),
        http_client=client,
        api_base_url="https://github.example/api/v3",
        clock=clock,
    )


def test_provider_generates_rs256_jwt_and_requests_installation_token(
    rsa_key_pair: tuple[Path, bytes],
) -> None:
    key_path, public_key = rsa_key_pair
    now = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)
    client = FakeHTTPClient([make_token_response("opaque-token-value", now + timedelta(hours=1))])
    provider = make_provider(
        key_path=key_path,
        client=client,
        clock=MutableClock(now),
    )

    token = provider.get_token(123)

    assert token.get_secret_value() == "opaque-token-value"
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://github.example/api/v3/app/installations/123/access_tokens"
    headers = call["headers"]
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == GITHUB_API_VERSION
    encoded = headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        encoded,
        public_key,
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims == {
        "iat": int(now.timestamp()) - 60,
        "exp": int(now.timestamp()) + 540,
        "iss": "Iv1.devagent",
    }


def test_provider_reuses_valid_token_and_refreshes_near_expiry(
    rsa_key_pair: tuple[Path, bytes],
) -> None:
    key_path, _ = rsa_key_pair
    now = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)
    clock = MutableClock(now)
    client = FakeHTTPClient(
        [
            make_token_response("first-token", now + timedelta(minutes=10)),
            make_token_response("second-token-with-new-format", now + timedelta(hours=1)),
        ]
    )
    provider = make_provider(key_path=key_path, client=client, clock=clock)

    assert provider.get_token(123).get_secret_value() == "first-token"
    assert provider.get_token(123).get_secret_value() == "first-token"
    clock.value = now + timedelta(minutes=9, seconds=1)
    assert provider.get_token(123).get_secret_value() == "second-token-with-new-format"
    assert len(client.calls) == 2


def test_provider_caches_tokens_per_installation(
    rsa_key_pair: tuple[Path, bytes],
) -> None:
    key_path, _ = rsa_key_pair
    now = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)
    client = FakeHTTPClient(
        [
            make_token_response("installation-one", now + timedelta(hours=1)),
            make_token_response("installation-two", now + timedelta(hours=1)),
        ]
    )
    provider = make_provider(
        key_path=key_path,
        client=client,
        clock=MutableClock(now),
    )

    assert provider.get_token(1).get_secret_value() == "installation-one"
    assert provider.get_token(2).get_secret_value() == "installation-two"
    assert provider.get_token(1).get_secret_value() == "installation-one"
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(401, {"message": "private-response-token"}),
        FakeResponse(201, {"token": "secret-only"}),
        RuntimeError("network-secret-detail"),
    ],
)
def test_provider_sanitizes_token_errors(
    rsa_key_pair: tuple[Path, bytes],
    response: FakeResponse | Exception,
) -> None:
    key_path, _ = rsa_key_pair
    now = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)
    provider = make_provider(
        key_path=key_path,
        client=FakeHTTPClient([response]),
        clock=MutableClock(now),
    )

    with pytest.raises(GitHubAuthenticationError) as exc_info:
        provider.get_token(123)

    message = str(exc_info.value)
    assert "private-response-token" not in message
    assert "secret-only" not in message
    assert "network-secret-detail" not in message


def test_provider_rejects_invalid_configuration(
    rsa_key_pair: tuple[Path, bytes],
) -> None:
    key_path, _ = rsa_key_pair
    client = FakeHTTPClient([])

    with pytest.raises(ValueError, match="HTTPS"):
        GitHubInstallationTokenProvider(
            credentials=GitHubAppCredentials(
                client_id="Iv1.devagent",
                private_key_path=key_path,
            ),
            http_client=client,
            api_base_url="http://api.github.test",
        )
