from types import SimpleNamespace

import pytest

from devagent.memory import (
    EmbeddingProviderError,
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
)


def make_response(
    vectors: list[list[float]],
    *,
    indexes: list[int] | None = None,
    prompt_tokens: int = 0,
) -> SimpleNamespace:
    resolved_indexes = indexes or list(range(len(vectors)))
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in zip(resolved_indexes, vectors, strict=True)
        ],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens),
    )


class FakeEmbeddingsResource:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_provider(
    responses: list[object],
    *,
    batch_size: int = 64,
    dimensions: int | None = None,
) -> tuple[OpenAIEmbeddingProvider, FakeEmbeddingsResource]:
    resource = FakeEmbeddingsResource(responses)
    client = SimpleNamespace(embeddings=resource)
    provider = OpenAIEmbeddingProvider(
        client=client,
        config=OpenAIEmbeddingConfig(
            model="embedding-test",
            batch_size=batch_size,
            dimensions=dimensions,
        ),
    )
    return provider, resource


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"model": ""}, "model"),
        ({"model": " padded "}, "model"),
        ({"model": "model", "batch_size": True}, "batch_size"),
        ({"model": "model", "batch_size": 0}, "batch_size"),
        ({"model": "model", "batch_size": 2049}, "batch_size"),
        ({"model": "model", "dimensions": True}, "dimensions"),
        ({"model": "model", "dimensions": 0}, "dimensions"),
    ],
)
def test_embedding_config_rejects_invalid_values(
    kwargs: dict[str, object],
    error: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=error):
        OpenAIEmbeddingConfig(**kwargs)  # type: ignore[arg-type]


def test_embed_documents_batches_and_restores_response_index_order() -> None:
    provider, resource = make_provider(
        [
            make_response([[0, 1], [1, 0]], indexes=[1, 0], prompt_tokens=4),
            make_response([[2, 2]], prompt_tokens=2),
        ],
        batch_size=2,
    )

    vectors = provider.embed_documents(["alpha", "beta", "gamma"])

    assert vectors == [(1.0, 0.0), (0.0, 1.0), (2.0, 2.0)]
    assert [call["input"] for call in resource.calls] == [
        ["alpha", "beta"],
        ["gamma"],
    ]
    assert all(call["model"] == "embedding-test" for call in resource.calls)
    assert all(call["encoding_format"] == "float" for call in resource.calls)
    assert all("dimensions" not in call for call in resource.calls)
    assert provider.document_request_count == 2
    assert provider.query_request_count == 0
    assert provider.input_tokens == 6
    assert provider.observed_dimensions == 2


def test_embed_query_sends_dimensions_only_when_configured() -> None:
    provider, resource = make_provider(
        [make_response([[1, 2, 3]], prompt_tokens=3)],
        dimensions=3,
    )

    vector = provider.embed_query("find evidence")

    assert vector == (1.0, 2.0, 3.0)
    assert resource.calls == [
        {
            "input": ["find evidence"],
            "model": "embedding-test",
            "encoding_format": "float",
            "dimensions": 3,
        }
    ]
    assert provider.query_request_count == 1
    assert provider.provider_name == "openai-compatible:embedding-test"
    assert provider.model_name == "embedding-test"


def test_embed_documents_empty_input_does_not_call_sdk() -> None:
    provider, resource = make_provider([])

    assert provider.embed_documents([]) == []
    assert resource.calls == []


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (SimpleNamespace(data=None), "data 格式"),
        (make_response([[1, 0]]), "数量不匹配"),
        (make_response([[1, 0], [0, 1]], indexes=[0, 0]), "index 无效"),
        (make_response([[1, 0], [0, 1]], indexes=[0, 2]), "index 无效"),
        (make_response([[1, float("nan")], [0, 1]]), "vector 无效"),
        (make_response([[0, 0], [0, 1]]), "vector 无效"),
    ],
)
def test_embed_documents_rejects_untrusted_response(
    response: object,
    error: str,
) -> None:
    provider, _ = make_provider([response])

    with pytest.raises(EmbeddingProviderError, match=error):
        provider.embed_documents(["alpha", "beta"])


def test_provider_rejects_dimension_drift_between_calls() -> None:
    provider, _ = make_provider(
        [
            make_response([[1, 0]]),
            make_response([[1, 0, 0]]),
        ]
    )
    provider.embed_documents(["alpha"])

    with pytest.raises(EmbeddingProviderError, match="vector 无效"):
        provider.embed_query("query")


def test_provider_converts_sdk_error_without_leaking_input() -> None:
    provider, _ = make_provider([RuntimeError("secret query and provider body")])

    with pytest.raises(EmbeddingProviderError) as captured:
        provider.embed_query("private source content")

    assert str(captured.value) == "embedding API 调用失败"
    assert "private source content" not in str(captured.value)
    assert "secret" not in str(captured.value)


@pytest.mark.parametrize("value", ["", "  ", 123])
def test_provider_rejects_invalid_input_before_sdk(value: object) -> None:
    provider, resource = make_provider([])

    with pytest.raises((TypeError, ValueError), match="不能为空|字符串"):
        provider.embed_query(value)  # type: ignore[arg-type]

    assert resource.calls == []
