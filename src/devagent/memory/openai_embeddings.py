from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .embeddings import (
    EmbeddingProviderError,
    EmbeddingVector,
    validate_embedding_vector,
)


class _EmbeddingsResource(Protocol):
    def create(self, **kwargs: Any) -> object: ...


class OpenAIEmbeddingClient(Protocol):
    embeddings: _EmbeddingsResource


@dataclass(frozen=True)
class OpenAIEmbeddingConfig:
    """OpenAI-compatible embedding 请求配置。"""

    model: str
    batch_size: int = 10
    dimensions: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model:
            raise ValueError("model 不能为空")
        if self.model != self.model.strip() or len(self.model) > 200:
            raise ValueError("model 格式无效")
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int):
            raise TypeError("batch_size 必须是整数")
        if not 1 <= self.batch_size <= 2_048:
            raise ValueError("batch_size 必须位于 1 到 2048")
        if self.dimensions is not None:
            if isinstance(self.dimensions, bool) or not isinstance(
                self.dimensions, int
            ):
                raise TypeError("dimensions 必须是整数")
            if self.dimensions < 1:
                raise ValueError("dimensions 必须大于 0")


class OpenAIEmbeddingProvider:
    """把 OpenAI-compatible embeddings API 适配为项目统一协议。"""

    def __init__(
        self,
        *,
        client: OpenAIEmbeddingClient,
        config: OpenAIEmbeddingConfig,
    ) -> None:
        self._client = client
        self.config = config
        self._observed_dimensions: int | None = config.dimensions
        self._document_request_count = 0
        self._query_request_count = 0
        self._input_tokens = 0

    @property
    def provider_name(self) -> str:
        return f"openai-compatible:{self.config.model}"

    @property
    def model_name(self) -> str:
        return self.config.model

    @property
    def observed_dimensions(self) -> int | None:
        return self._observed_dimensions

    @property
    def document_request_count(self) -> int:
        return self._document_request_count

    @property
    def query_request_count(self) -> int:
        return self._query_request_count

    @property
    def input_tokens(self) -> int:
        return self._input_tokens

    def embed_documents(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        normalized = _validate_texts(texts)
        vectors: list[EmbeddingVector] = []
        for start in range(0, len(normalized), self.config.batch_size):
            batch = normalized[start : start + self.config.batch_size]
            vectors.extend(self._embed_batch(batch, request_kind="document"))
        return vectors

    def embed_query(self, text: str) -> EmbeddingVector:
        normalized = _validate_text(text)
        return self._embed_batch([normalized], request_kind="query")[0]

    def _embed_batch(
        self,
        texts: list[str],
        *,
        request_kind: str,
    ) -> list[EmbeddingVector]:
        kwargs: dict[str, object] = {
            "input": texts,
            "model": self.config.model,
            "encoding_format": "float",
        }
        if self.config.dimensions is not None:
            kwargs["dimensions"] = self.config.dimensions

        if request_kind == "document":
            self._document_request_count += 1
        else:
            self._query_request_count += 1
        try:
            response = self._client.embeddings.create(**kwargs)
        except Exception as exc:
            # ! Provider exceptions may contain request details; expose only a stable error.
            raise EmbeddingProviderError("embedding API 调用失败") from exc

        vectors = self._validate_response(response, expected_count=len(texts))
        self._record_usage(response)
        return vectors

    def _validate_response(
        self,
        response: object,
        *,
        expected_count: int,
    ) -> list[EmbeddingVector]:
        data = getattr(response, "data", None)
        if isinstance(data, (str, bytes)) or not isinstance(data, Sequence):
            raise EmbeddingProviderError("embedding response data 格式无效")
        if len(data) != expected_count:
            raise EmbeddingProviderError("embedding response data 数量不匹配")

        indexed: dict[int, object] = {}
        for item in data:
            index = getattr(item, "index", None)
            if isinstance(index, bool) or not isinstance(index, int):
                raise EmbeddingProviderError("embedding response index 无效")
            if not 0 <= index < expected_count or index in indexed:
                raise EmbeddingProviderError("embedding response index 无效")
            indexed[index] = item
        if set(indexed) != set(range(expected_count)):
            raise EmbeddingProviderError("embedding response index 无效")

        expected_dimensions = self._observed_dimensions
        vectors: list[EmbeddingVector] = []
        for index in range(expected_count):
            values = getattr(indexed[index], "embedding", None)
            try:
                vector = validate_embedding_vector(
                    values,
                    expected_dimensions=expected_dimensions,
                )
            except (EmbeddingProviderError, TypeError) as exc:
                raise EmbeddingProviderError("embedding response vector 无效") from exc
            if expected_dimensions is None:
                expected_dimensions = len(vector)
            vectors.append(vector)

        self._observed_dimensions = expected_dimensions
        return vectors

    def _record_usage(self, response: object) -> None:
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool):
            self._input_tokens += max(prompt_tokens, 0)


def _validate_texts(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
        raise TypeError("texts 必须是字符串序列")
    return [_validate_text(text) for text in texts]


def _validate_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("embedding input 必须是字符串")
    if not text.strip():
        raise ValueError("embedding input 不能为空")
    return text
