import hashlib
import hmac

import pytest

from devagent.integrations.github.security import (
    GitHubSignatureError,
    verify_github_signature,
)


def sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_github_signature_accepts_original_body() -> None:
    body = b'{"action":"opened"}'

    verify_github_signature(
        body=body,
        signature_header=sign(body, "test-secret"),
        secret="test-secret",
    )


@pytest.mark.parametrize(
    ("body", "signature", "secret"),
    [
        (b'{"action":"reopened"}', sign(b'{"action":"opened"}', "secret"), "secret"),
        (b'{"action":"opened"}', sign(b'{"action":"opened"}', "other"), "secret"),
        (b"{}", None, "secret"),
        (b"{}", "sha1=" + "0" * 40, "secret"),
        (b"{}", "sha256=short", "secret"),
        (b"{}", sign(b"{}", "secret"), ""),
    ],
)
def test_verify_github_signature_rejects_invalid_inputs(
    body: bytes,
    signature: str | None,
    secret: str,
) -> None:
    with pytest.raises(GitHubSignatureError):
        verify_github_signature(
            body=body,
            signature_header=signature,
            secret=secret,
        )


def test_verify_github_signature_uses_compare_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"{}"
    calls: list[tuple[str, str]] = []

    def record_compare(expected: str, actual: str) -> bool:
        calls.append((expected, actual))
        return True

    monkeypatch.setattr("devagent.integrations.github.security.hmac.compare_digest", record_compare)

    verify_github_signature(
        body=body,
        signature_header=sign(body, "secret"),
        secret="secret",
    )

    assert len(calls) == 1


def test_signature_error_does_not_leak_inputs() -> None:
    secret = "secret-never-log"
    body = b'{"private":"payload-never-log"}'
    signature = "sha256=" + "0" * 64

    with pytest.raises(GitHubSignatureError) as exc_info:
        verify_github_signature(
            body=body,
            signature_header=signature,
            secret=secret,
        )

    message = str(exc_info.value)
    assert secret not in message
    assert signature not in message
    assert body.decode() not in message
