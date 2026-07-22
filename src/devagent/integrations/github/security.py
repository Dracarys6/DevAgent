import hmac
from hashlib import sha256

# * webhook 签名校验
GITHUB_SIGNATURE_PREFIX = "sha256="


class GitHubSignatureError(ValueError):
    pass


def verify_github_signature(
    *,
    body: bytes,
    signature_header: str | None,
    secret: str,
) -> None:
    if not secret:
        raise GitHubSignatureError("webhook secret 未配置")
    if (
        not signature_header
        or not signature_header.startswith(GITHUB_SIGNATURE_PREFIX)
        or len(signature_header) != len(GITHUB_SIGNATURE_PREFIX) + 64
    ):
        raise GitHubSignatureError("缺少有效的 GitHub webhook 签名")

    expected = (
        GITHUB_SIGNATURE_PREFIX
        + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()
    )

    if not hmac.compare_digest(expected, signature_header):
        raise GitHubSignatureError("GitHub webhook 签名无效")
