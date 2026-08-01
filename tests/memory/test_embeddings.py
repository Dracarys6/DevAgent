from math import sqrt

import pytest

from devagent.memory import (
    EmbeddingProviderError,
    normalize_embedding_vector,
    validate_embedding_vector,
)


def test_validate_embedding_vector_returns_immutable_float_tuple() -> None:
    source = [1, 2.5]

    vector = validate_embedding_vector(source)
    source[0] = 9

    assert vector == (1.0, 2.5)


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ([], "不能为空"),
        ([True, 1], "只能包含数值"),
        (["1", 2], "只能包含数值"),
        ([float("nan"), 1], "有限数值"),
        ([float("inf"), 1], "有限数值"),
        ([0, 0], "全零向量"),
        ("1,2", "数值序列"),
    ],
)
def test_validate_embedding_vector_rejects_invalid_provider_output(
    values: object,
    error: str,
) -> None:
    with pytest.raises(EmbeddingProviderError, match=error):
        validate_embedding_vector(values)  # type: ignore[arg-type]


def test_validate_embedding_vector_rejects_dimension_mismatch() -> None:
    with pytest.raises(EmbeddingProviderError, match="维度不一致"):
        validate_embedding_vector([1, 2], expected_dimensions=3)


@pytest.mark.parametrize("dimensions", [True, 1.5, "2"])
def test_validate_embedding_vector_rejects_invalid_dimension_type(
    dimensions: object,
) -> None:
    with pytest.raises(TypeError, match="必须是整数"):
        validate_embedding_vector(
            [1, 2],
            expected_dimensions=dimensions,  # type: ignore[arg-type]
        )


def test_validate_embedding_vector_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError, match="大于 0"):
        validate_embedding_vector([1, 2], expected_dimensions=0)


def test_normalize_embedding_vector_returns_unit_length() -> None:
    vector = normalize_embedding_vector([3, 4])

    assert vector == pytest.approx((0.6, 0.8))
    assert sqrt(sum(value * value for value in vector)) == pytest.approx(1)


def test_normalize_embedding_vector_handles_large_finite_values() -> None:
    vector = normalize_embedding_vector([1e308, 1e308])

    assert vector == pytest.approx((2**-0.5, 2**-0.5))
