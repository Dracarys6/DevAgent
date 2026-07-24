from collections.abc import Callable
from math import inf, nan

import pytest
from pydantic import ValidationError

from devagent.memory import (
    Chunk,
    ChunkType,
    Document,
    EvidenceSnippet,
    LineRange,
    RetrievalResult,
)


def make_document(**overrides: object) -> Document:
    data: dict[str, object] = {
        "document_id": "doc-1",
        "source": "workspace",
        "path": "src/devagent/event/bus.py",
        "document_type": ChunkType.CODE,
        "content": "class EventBus:\n    pass\n",
        "metadata": {"language": "python"},
    }
    data.update(overrides)
    return Document.model_validate(data)


def make_chunk(**overrides: object) -> Chunk:
    data: dict[str, object] = {
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "source": "workspace",
        "path": "src/devagent/event/bus.py",
        "line_range": {"start": 1, "end": 2},
        "chunk_type": ChunkType.CODE,
        "content": "class EventBus:\n    pass\n",
        "metadata": {"language": "python"},
    }
    data.update(overrides)
    return Chunk.model_validate(data)


def make_snippet(**overrides: object) -> EvidenceSnippet:
    data: dict[str, object] = {
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "source": "workspace",
        "path": "src/devagent/event/bus.py",
        "line_range": {"start": 1, "end": 2},
        "excerpt": "class EventBus:\n    pass\n",
        "score": 4.2,
        "rank": 1,
        "metadata": {"language": "python"},
    }
    data.update(overrides)
    return EvidenceSnippet.model_validate(data)


def make_result(**overrides: object) -> RetrievalResult:
    data: dict[str, object] = {
        "query": "事件在哪里发布",
        "top_k": 5,
        "total_candidates": 2,
        "items": [
            make_snippet(),
            make_snippet(
                chunk_id="chunk-2",
                path="src/devagent/event/models.py",
                line_range={"start": 10, "end": 18},
                score=2.8,
                rank=2,
            ),
        ],
        "retrieval_ms": 12.5,
        "truncated": False,
    }
    data.update(overrides)
    return RetrievalResult.model_validate(data)


def test_memory_chunk_type_has_expected_values() -> None:
    assert {item.value for item in ChunkType} == {
        "code",
        "markdown",
        "log",
        "ci_json",
        "text",
    }


@pytest.mark.parametrize(
    ("start", "end"),
    [(1, 1), (3, 8)],
)
def test_line_range_accepts_one_based_closed_range(start: int, end: int) -> None:
    line_range = LineRange(start=start, end=end)

    assert line_range.start == start
    assert line_range.end == end


@pytest.mark.parametrize(
    ("start", "end"),
    [(0, 1), (-1, 1), (2, 0), (3, 2)],
)
def test_line_range_rejects_invalid_bounds(start: int, end: int) -> None:
    with pytest.raises(ValidationError):
        LineRange(start=start, end=end)


@pytest.mark.parametrize("document_type", list(ChunkType))
def test_document_accepts_each_supported_type(
    document_type: ChunkType,
) -> None:
    assert make_document(document_type=document_type).document_type == document_type


def test_document_preserves_content_formatting() -> None:
    content = "  indented\n\ntrailing  \n"

    document = make_document(content=content)

    assert document.content == content


def test_document_metadata_default_is_not_shared() -> None:
    first = make_document(metadata={})
    second = make_document(document_id="doc-2", metadata={})

    first.metadata["language"] = "python"

    assert second.metadata == {}


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/file.py",
        "../outside.py",
        "src/../../outside.py",
        r"src\devagent\memory.py",
        ".",
        " src/devagent/memory.py",
        "src/devagent/memory.py ",
    ],
)
@pytest.mark.parametrize(
    "factory",
    [make_document, make_chunk, make_snippet],
)
def test_memory_records_require_relative_posix_path(
    path: str,
    factory: Callable[..., object],
) -> None:
    with pytest.raises(ValidationError, match="path"):
        factory(path=path)


@pytest.mark.parametrize(
    "factory",
    [make_document, make_chunk],
)
def test_document_and_chunk_reject_blank_content(
    factory: Callable[..., object],
) -> None:
    with pytest.raises(ValidationError, match="content"):
        factory(content=" \n\t")


def test_chunk_keeps_document_identity_and_location() -> None:
    chunk = make_chunk()

    assert chunk.document_id == "doc-1"
    assert chunk.source == "workspace"
    assert chunk.path == "src/devagent/event/bus.py"
    assert chunk.line_range == LineRange(start=1, end=2)
    assert chunk.chunk_type == ChunkType.CODE


def test_evidence_snippet_accepts_unbounded_bm25_score() -> None:
    snippet = make_snippet(score=18.75)

    assert snippet.score == 18.75


@pytest.mark.parametrize("score", [-1.0, nan, inf, -inf])
def test_evidence_snippet_rejects_invalid_score(score: float) -> None:
    with pytest.raises(ValidationError, match="score"):
        make_snippet(score=score)


def test_evidence_snippet_rejects_zero_rank() -> None:
    with pytest.raises(ValidationError, match="rank"):
        make_snippet(rank=0)


def test_evidence_snippet_preserves_excerpt_formatting() -> None:
    excerpt = "  if allowed:\n      run()\n"

    snippet = make_snippet(excerpt=excerpt)

    assert snippet.excerpt == excerpt


def test_evidence_snippet_rejects_blank_excerpt() -> None:
    with pytest.raises(ValidationError, match="excerpt"):
        make_snippet(excerpt="\n\t")


def test_retrieval_result_accepts_empty_result() -> None:
    result = make_result(total_candidates=0, items=[])

    assert result.items == []
    assert result.total_candidates == 0


def test_retrieval_result_accepts_more_candidates_than_returned_items() -> None:
    result = make_result(total_candidates=20)

    assert len(result.items) == 2
    assert result.total_candidates == 20


def test_retrieval_result_rejects_items_beyond_top_k() -> None:
    with pytest.raises(ValidationError, match="items 长度不能超过 top_k"):
        make_result(top_k=1)


def test_retrieval_result_rejects_candidate_count_below_item_count() -> None:
    with pytest.raises(
        ValidationError,
        match="total_candidates 不能小于 items 长度",
    ):
        make_result(total_candidates=1)


def test_retrieval_result_rejects_duplicate_chunk_ids() -> None:
    duplicate = make_snippet(
        path="src/devagent/event/models.py",
        score=2.8,
        rank=2,
    )

    with pytest.raises(ValidationError, match="chunk_id 不能重复"):
        make_result(items=[make_snippet(), duplicate])


@pytest.mark.parametrize(
    "ranks",
    [(2, 3), (1, 1), (1, 3)],
)
def test_retrieval_result_requires_contiguous_ranks(
    ranks: tuple[int, int],
) -> None:
    items = [
        make_snippet(rank=ranks[0]),
        make_snippet(chunk_id="chunk-2", score=2.8, rank=ranks[1]),
    ]

    with pytest.raises(ValidationError, match="rank 必须从 1 开始连续递增"):
        make_result(items=items)


def test_retrieval_result_requires_descending_scores() -> None:
    items = [
        make_snippet(score=2.8),
        make_snippet(chunk_id="chunk-2", score=4.2, rank=2),
    ]

    with pytest.raises(ValidationError, match="score 从高到低"):
        make_result(items=items)


def test_retrieval_result_accepts_equal_scores() -> None:
    items = [
        make_snippet(score=4.2),
        make_snippet(chunk_id="chunk-2", score=4.2, rank=2),
    ]

    assert make_result(items=items).items == items


def test_retrieval_result_rejects_blank_query() -> None:
    with pytest.raises(ValidationError, match="query"):
        make_result(query=" \t")


def test_retrieval_result_supports_json_round_trip() -> None:
    result = make_result()

    restored = RetrievalResult.model_validate_json(result.model_dump_json())

    assert restored == result


@pytest.mark.parametrize(
    ("model_type", "data"),
    [
        (
            LineRange,
            {"start": 1, "end": 1, "unknown": True},
        ),
        (
            Document,
            {
                **make_document().model_dump(),
                "unknown": True,
            },
        ),
        (
            Chunk,
            {
                **make_chunk().model_dump(),
                "unknown": True,
            },
        ),
        (
            EvidenceSnippet,
            {
                **make_snippet().model_dump(),
                "unknown": True,
            },
        ),
        (
            RetrievalResult,
            {
                **make_result().model_dump(),
                "unknown": True,
            },
        ),
    ],
)
def test_memory_models_reject_unknown_fields(
    model_type: type[LineRange]
    | type[Document]
    | type[Chunk]
    | type[EvidenceSnippet]
    | type[RetrievalResult],
    data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="unknown"):
        model_type.model_validate(data)
