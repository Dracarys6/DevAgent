import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


@dataclass(frozen=True)
class LiveEmbeddingSettings:
    api_key: str
    model: str
    base_url: str
    dimensions: int | None
    batch_size: int


def load_live_embedding_settings(project_root: str | Path) -> LiveEmbeddingSettings:
    """加载受显式费用开关保护的独立 embedding provider 配置。"""
    root = Path(project_root).expanduser().resolve()
    load_dotenv(dotenv_path=root / ".env", override=False)
    if os.getenv("DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL") != "1":
        raise SystemExit(
            "真实 Embedding Evaluation 未启用；"
            "请显式设置 DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL=1"
        )

    api_key = os.getenv("DEVAGENT_EMBEDDING_API_KEY", "").strip()
    model = os.getenv("DEVAGENT_EMBEDDING_MODEL", "").strip()
    base_url = os.getenv("DEVAGENT_EMBEDDING_BASE_URL", "").strip()
    if not api_key:
        raise SystemExit("真实 Embedding Evaluation 缺少 DEVAGENT_EMBEDDING_API_KEY")
    if not model:
        raise SystemExit("真实 Embedding Evaluation 缺少 DEVAGENT_EMBEDDING_MODEL")
    if not base_url:
        raise SystemExit("真实 Embedding Evaluation 缺少 DEVAGENT_EMBEDDING_BASE_URL")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("DEVAGENT_EMBEDDING_BASE_URL 必须是 HTTP(S) API 根路径")
    if parsed.path.rstrip("/").endswith("/embeddings"):
        raise SystemExit(
            "DEVAGENT_EMBEDDING_BASE_URL 应为 API 根路径，不能包含 /embeddings"
        )

    dimensions = _parse_optional_positive_integer(
        os.getenv("DEVAGENT_EMBEDDING_DIMENSIONS", "").strip(),
        name="DEVAGENT_EMBEDDING_DIMENSIONS",
    )
    batch_size = _parse_bounded_integer(
        os.getenv("DEVAGENT_EMBEDDING_BATCH_SIZE", "10").strip(),
        name="DEVAGENT_EMBEDDING_BATCH_SIZE",
        minimum=1,
        maximum=2_048,
    )
    return LiveEmbeddingSettings(
        api_key=api_key,
        model=model,
        base_url=base_url,
        dimensions=dimensions,
        batch_size=batch_size,
    )


def _parse_optional_positive_integer(value: str, *, name: str) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是正整数") from exc
    if parsed < 1:
        raise SystemExit(f"{name} 必须是正整数")
    return parsed


def _parse_bounded_integer(
    value: str,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是 {minimum} 到 {maximum} 的整数") from exc
    if not minimum <= parsed <= maximum:
        raise SystemExit(f"{name} 必须是 {minimum} 到 {maximum} 的整数")
    return parsed
