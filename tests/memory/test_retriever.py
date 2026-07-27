from collections import Counter
from dataclasses import FrozenInstanceError

import pytest

import devagent.memory.retriever as retriever_module
from devagent.memory import Chunk, ChunkType, LineRange, KeywordRetriever
from devagent.memory.retriever import (
    BM25Config,
    RetrievalError,
    _build_excerpt,
    _prepare_query,
    _tokenize,
    _validate_top_k,
)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("k1", True),
        ("k1", "1.5"),
        ("k1", float("nan")),
        ("k1", float("inf")),
        ("b", True),
        ("b", "0.75"),
        ("b", float("nan")),
        ("b", float("-inf")),
        ("max_excerpt_chars", True),
        ("max_excerpt_chars", 10.5),
    ],
)
def test_bm25_config_rejects_invalid_types_and_non_finite_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        BM25Config(**{field: value})  # type: ignore[arg-type]


def test_bm25_config_accepts_b_boundaries() -> None:
    assert BM25Config(b=0).b == 0
    assert BM25Config(b=1).b == 1


def test_bm25_config_defaults_and_immutability() -> None:
    config = BM25Config()

    assert config.k1 == 1.5
    assert config.b == 0.75
    assert config.max_excerpt_chars == 2000
    with pytest.raises(FrozenInstanceError):
        config.k1 = 2.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"k1": 0},
        {"k1": -0.1},
        {"b": -0.1},
        {"b": 1.1},
        {"max_excerpt_chars": 0},
        {"max_excerpt_chars": 2001},
    ],
)
def test_bm25_config_rejects_out_of_range_values(
    kwargs: dict[str, int | float],
) -> None:
    with pytest.raises(ValueError):
        BM25Config(**kwargs)  # type: ignore[arg-type]


def test_tokenizer_expands_code_identifiers() -> None:
    assert _tokenize("PermissionManager") == [
        "permissionmanager",
        "permission",
        "manager",
    ]
    assert _tokenize("build_upload_timeout") == [
        "build_upload_timeout",
        "build",
        "upload",
        "timeout",
    ]
    assert _tokenize("HTTPResponse") == [
        "httpresponse",
        "http",
        "response",
    ]


def test_tokenizer_builds_chinese_bigrams() -> None:
    tokens = _tokenize("权限校验失败")
    assert "权限校验失败" in tokens
    assert "权限" in tokens
    assert "校验" in tokens
    assert "失败" in tokens


def test_tokenizer_handles_paths_repetition_and_punctuation() -> None:
    path_tokens = _tokenize("tests/test_uploader.py")

    assert {"tests", "test_uploader", "test", "uploader", "py"} <= set(path_tokens)
    assert _tokenize("timeout timeout").count("timeout") == 2
    assert _tokenize("!!!") == []


def make_chunk(
    chunk_id: str = "chunk-1",
    *,
    path: str = "src/uploader.py",
    content: str = "def build_upload_timeout():\n    pass\n",
    line_start: int = 1,
    line_end: int = 2,
    metadata: dict[str, str] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source="workspace",
        path=path,
        line_range=LineRange(start=line_start, end=line_end),
        chunk_type=ChunkType.CODE,
        content=content,
        metadata=metadata or {},
    )


def test_retriever_precomputes_index_statistics() -> None:
    retriever = KeywordRetriever([make_chunk()])

    assert len(retriever._indexed_chunks) == 1
    assert retriever._document_frequencies["upload"] == 1
    assert retriever._average_document_length > 0


def test_retriever_indexes_path_and_content() -> None:
    retriever = KeywordRetriever([make_chunk(path="tests/test_uploader.py")])

    tokens = retriever._indexed_chunks[0].tokens
    assert "test_uploader" in tokens
    assert "upload" in tokens


def test_retriever_snapshots_input_sequence() -> None:
    chunks = [make_chunk()]
    retriever = KeywordRetriever(chunks)

    chunks.append(make_chunk("chunk-2"))

    assert len(retriever._indexed_chunks) == 1


def test_retriever_rejects_duplicate_chunk_ids() -> None:
    with pytest.raises(RetrievalError, match="chunk_id"):
        KeywordRetriever([make_chunk(), make_chunk()])


def test_retriever_accepts_empty_index() -> None:
    retriever = KeywordRetriever([])
    assert retriever._indexed_chunks == ()
    assert retriever._document_frequencies == Counter()
    assert retriever._average_document_length == 0.0


def test_score_chunk_returns_positive_score_for_matching_terms() -> None:
    retriever = KeywordRetriever([make_chunk()])
    indexed_chunk = retriever._indexed_chunks[0]
    score = retriever._score_chunk(indexed_chunk, {"build", "upload"})
    assert score > 0


def test_score_chunk_returns_zero_for_missing_terms() -> None:
    retriever = KeywordRetriever([make_chunk()])
    indexed_chunk = retriever._indexed_chunks[0]
    score = retriever._score_chunk(indexed_chunk, {"nonexistent"})
    assert score == 0.0


def test_rare_term_scores_higher_than_common_term() -> None:
    retriever = KeywordRetriever(
        [
            make_chunk("chunk-1", content="common rare"),
            make_chunk("chunk-2", content="common event"),
            make_chunk("chunk-3", content="common task"),
        ]
    )
    indexed_chunk = retriever._indexed_chunks[0]

    common_score = retriever._score_chunk(indexed_chunk, {"common"})
    rare_score = retriever._score_chunk(indexed_chunk, {"rare"})

    assert rare_score > common_score


def test_term_frequency_increases_score_with_saturation() -> None:
    retriever = KeywordRetriever(
        [
            make_chunk("chunk-1", content="timeout"),
            make_chunk("chunk-2", content="timeout timeout timeout"),
        ],
        config=BM25Config(b=0),
    )
    first, repeated = retriever._indexed_chunks

    first_score = retriever._score_chunk(first, {"timeout"})
    repeated_score = retriever._score_chunk(repeated, {"timeout"})

    assert repeated_score > first_score
    assert repeated_score < 3 * first_score


@pytest.mark.parametrize("query", ["", "   ", "!!!"])
def test_prepare_query_rejects_unsearchable_query(query: str) -> None:
    with pytest.raises(RetrievalError, match="query"):
        _prepare_query(query)


def test_prepare_query_normalizes_and_tokenizes_query() -> None:
    normalized, terms = _prepare_query("  PermissionManager  ")

    assert normalized == "PermissionManager"
    assert {"permissionmanager", "permission", "manager"} <= terms


@pytest.mark.parametrize("top_k", [0, 51, True, 1.5])
def test_validate_top_k_rejects_invalid_values(top_k: int) -> None:
    with pytest.raises(RetrievalError, match="top_k"):
        _validate_top_k(top_k)


def test_retrieve_exposes_query_and_top_k_validation() -> None:
    retriever = KeywordRetriever([make_chunk()])

    with pytest.raises(RetrievalError, match="query"):
        retriever.retrieve("   ")
    with pytest.raises(RetrievalError, match="top_k"):
        retriever.retrieve("upload", top_k=0)


def test_rank_candidates_filters_zero_scores() -> None:
    retriever = KeywordRetriever(
        [
            make_chunk("chunk-upload", content="upload timeout"),
            make_chunk("chunk-event", content="event publish"),
        ]
    )
    candidates = retriever._rank_candidates({"upload"})

    assert [item.chunk.chunk_id for item in candidates] == ["chunk-upload"]
    assert candidates[0].score > 0


def test_build_excerpt_keeps_short_content_unchanged() -> None:
    content = "upload timeout"

    excerpt, start, end = _build_excerpt(
        content,
        {"upload", "timeout"},
        max_chars=100,
    )

    assert excerpt == content
    assert start == 0
    assert end == len(content)


def test_build_excerpt_centers_on_matching_query_term() -> None:
    content = "a" * 200 + "timeout" + "b" * 100

    excerpt, start, end = _build_excerpt(
        content,
        {"timeout"},
        max_chars=60,
    )

    assert len(excerpt) == 60
    assert "timeout" in excerpt
    assert excerpt == content[start:end]


def test_build_excerpt_falls_back_to_first_non_whitespace() -> None:
    content = " " * 100 + "def run(): pass"

    excerpt, start, end = _build_excerpt(
        content,
        {"uploader"},
        max_chars=30,
    )

    assert excerpt.strip()
    assert excerpt == content[start:end]
    assert len(excerpt) <= 30


def test_rank_candidates_uses_stable_tie_break() -> None:
    retriever = KeywordRetriever(
        [
            make_chunk("chunk-z", path="src/b.py", content="target"),
            make_chunk(
                "chunk-b",
                path="src/a.py",
                content="target",
                line_start=2,
                line_end=2,
            ),
            make_chunk("chunk-c", path="src/a.py", content="target"),
            make_chunk("chunk-a", path="src/a.py", content="target"),
        ]
    )

    candidates = retriever._rank_candidates({"target"})

    assert [item.chunk.chunk_id for item in candidates] == [
        "chunk-a",
        "chunk-c",
        "chunk-b",
        "chunk-z",
    ]


def test_retrieve_returns_ranked_evidence() -> None:
    result = KeywordRetriever([make_chunk()]).retrieve("upload")

    assert result.query == "upload"
    assert result.total_candidates == 1
    assert len(result.items) == 1
    assert result.items[0].chunk_id == "chunk-1"
    assert result.items[0].rank == 1
    assert result.items[0].score > 0
    assert result.items[0].source == "workspace"
    assert result.items[0].path == "src/uploader.py"
    assert result.items[0].line_range == LineRange(start=1, end=2)
    assert result.items[0].metadata["retrieval_method"] == "bm25"
    assert result.retrieval_ms >= 0
    assert result.truncated is False


def test_retrieve_returns_empty_result_when_no_chunk_matches() -> None:
    result = KeywordRetriever([make_chunk()]).retrieve("nonexistent")

    assert result.total_candidates == 0
    assert result.items == []
    assert result.truncated is False


def test_retrieve_marks_top_k_result_as_truncated() -> None:
    retriever = KeywordRetriever(
        [
            make_chunk("chunk-1", content="upload first"),
            make_chunk("chunk-2", content="upload second"),
            make_chunk("chunk-3", content="upload third"),
        ]
    )

    result = retriever.retrieve("upload", top_k=2)

    assert result.total_candidates == 3
    assert len(result.items) == 2
    assert [item.rank for item in result.items] == [1, 2]
    assert result.truncated is True


def test_retrieve_builds_bounded_excerpt_without_mutating_chunk_metadata() -> None:
    metadata = {"language": "python"}
    content = "a" * 200 + " timeout " + "b" * 100
    chunk = make_chunk(content=content, metadata=metadata)
    retriever = KeywordRetriever(
        [chunk],
        config=BM25Config(max_excerpt_chars=60),
    )

    result = retriever.retrieve("timeout")
    item = result.items[0]
    start = int(item.metadata["excerpt_start_char"])
    end = int(item.metadata["excerpt_end_char"])

    assert item.excerpt == content[start:end]
    assert len(item.excerpt) == 60
    assert "timeout" in item.excerpt
    assert item.metadata["language"] == "python"
    assert item.metadata["retrieval_method"] == "bm25"
    assert chunk.metadata == {"language": "python"}
    assert metadata == {"language": "python"}
    assert result.truncated is True


def test_retrieve_records_elapsed_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    timestamps = iter([10.0, 10.0125])
    monkeypatch.setattr(retriever_module, "perf_counter", lambda: next(timestamps))

    result = KeywordRetriever([make_chunk()]).retrieve("upload")

    assert result.retrieval_ms == pytest.approx(12.5)


def test_retrieve_is_deterministic_except_for_timing() -> None:
    retriever = KeywordRetriever(
        [
            make_chunk("chunk-z", path="src/z.py", content="target"),
            make_chunk("chunk-a", path="src/a.py", content="target"),
        ]
    )

    results = [retriever.retrieve("target") for _ in range(5)]
    stable_payloads = [
        result.model_dump(exclude={"retrieval_ms"}) for result in results
    ]

    assert all(payload == stable_payloads[0] for payload in stable_payloads)


def test_top_5_baseline_finds_expected_evidence() -> None:
    chunks = [
        make_chunk(
            "C1",
            path="src/uploader.py",
            content=(
                "build_upload_timeout calculates timeout from size_mb "
                "and bandwidth_mb_s"
            ),
        ),
        make_chunk(
            "C2",
            path="tests/test_uploader.py",
            content="test_large_upload_uses_dynamic_timeout",
        ),
        make_chunk(
            "C3",
            path="src/event/bus.py",
            content="EventBus publish subscribe",
        ),
        make_chunk(
            "C4",
            path="logs/task.log",
            content="UploadTimeoutError after 3 seconds",
        ),
        make_chunk(
            "C5",
            path="docs/permissions.md",
            content="PermissionManager validates shell risk",
        ),
    ]
    cases = [
        ("build upload timeout", {"C1"}),
        ("large upload dynamic timeout test", {"C2"}),
        ("event publish subscribe", {"C3"}),
        ("permission manager shell risk", {"C5"}),
        ("UploadTimeoutError 3 seconds", {"C4"}),
    ]
    retriever = KeywordRetriever(chunks)

    hit_count = 0
    for query, expected_chunk_ids in cases:
        result = retriever.retrieve(query, top_k=5)
        actual_chunk_ids = {item.chunk_id for item in result.items}
        hit_count += bool(actual_chunk_ids & expected_chunk_ids)
        assert all(
            item.source and item.path and item.line_range for item in result.items
        )
        assert all(len(item.excerpt) <= 2000 for item in result.items)

    assert hit_count / len(cases) >= 0.8
