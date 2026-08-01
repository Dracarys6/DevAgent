from collections.abc import Sequence
from math import hypot, isfinite
from typing import Protocol, TypeAlias

EmbeddingVector: TypeAlias = tuple[float, ...]


class EmbeddingProviderError(RuntimeError):
    """Embedding provider 无法返回可用向量。"""


class EmbeddingProvider(Protocol):
    """把文档与查询文本转换到兼容向量空间的 provider 协议。"""

    @property
    def provider_name(self) -> str: ...

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[EmbeddingVector]: ...

    def embed_query(self, text: str) -> EmbeddingVector: ...


def validate_embedding_vector(
    values: Sequence[float],
    *,
    expected_dimensions: int | None = None,
) -> EmbeddingVector:
    """验证 provider 输出并复制为不可变向量。"""
    if expected_dimensions is not None:
        if isinstance(expected_dimensions, bool) or not isinstance(
            expected_dimensions, int
        ):
            raise TypeError("expected_dimensions 必须是整数")
        if expected_dimensions < 1:
            raise ValueError("expected_dimensions 必须大于 0")
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise EmbeddingProviderError("embedding vector 必须是数值序列")
    if not values:
        raise EmbeddingProviderError("embedding vector 不能为空")

    vector: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EmbeddingProviderError("embedding vector 只能包含数值")
        normalized_value = float(value)
        if not isfinite(normalized_value):
            raise EmbeddingProviderError("embedding vector 只能包含有限数值")
        vector.append(normalized_value)

    if expected_dimensions is not None and len(vector) != expected_dimensions:
        raise EmbeddingProviderError("embedding vector 维度不一致")
    if not any(value != 0 for value in vector):
        raise EmbeddingProviderError("embedding vector 不能是全零向量")
    return tuple(vector)


def normalize_embedding_vector(
    values: Sequence[float],
    *,
    expected_dimensions: int | None = None,
) -> EmbeddingVector:
    """返回单位长度向量，供稳定计算 cosine similarity。"""
    vector = validate_embedding_vector(
        values,
        expected_dimensions=expected_dimensions,
    )
    magnitude = hypot(*vector)
    if not isfinite(magnitude) or magnitude == 0:
        raise EmbeddingProviderError("embedding vector 范数无效")
    return tuple(value / magnitude for value in vector)
