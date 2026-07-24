from dataclasses import FrozenInstanceError
import re

import pytest

from devagent.memory import (
    ChunkingConfig,
    ChunkingError,
    ChunkType,
    Document,
    LineRange,
    chunk_document,
)


def make_document(**overrides: object) -> Document:
    data: dict[str, object] = {
        "document_id": "doc-1",
        "source": "workspace",
        "path": "src/sample.py",
        "document_type": ChunkType.CODE,
        "content": "def run():\n    return True\n",
        "metadata": {"language": "python"},
    }
    data.update(overrides)
    return Document.model_validate(data)


def numbered_lines(count: int, *, newline: str = "\n") -> str:
    return "".join(f"line-{index}{newline}" for index in range(1, count + 1))


def test_chunking_config_has_expected_defaults() -> None:
    assert ChunkingConfig() == ChunkingConfig(
        max_lines=80,
        overlap_lines=10,
        max_chars=4_000,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_lines": 0}, "max_lines"),
        ({"max_lines": True}, "max_lines"),
        ({"overlap_lines": -1}, "overlap_lines"),
        ({"max_lines": 3, "overlap_lines": 3}, "overlap_lines"),
        ({"max_lines": 3, "overlap_lines": 4}, "overlap_lines"),
        ({"overlap_lines": False}, "overlap_lines"),
        ({"max_chars": 0}, "max_chars"),
        ({"max_chars": True}, "max_chars"),
    ],
)
def test_chunking_config_rejects_invalid_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ChunkingConfig(**overrides)  # type: ignore[arg-type]


def test_chunking_config_accepts_zero_overlap() -> None:
    assert ChunkingConfig(overlap_lines=0).overlap_lines == 0


def test_chunking_config_is_immutable() -> None:
    config = ChunkingConfig()

    with pytest.raises(FrozenInstanceError):
        config.max_lines = 10  # type: ignore[misc]


def test_short_document_preserves_identity_content_and_metadata() -> None:
    document = make_document(
        content="  def run():\r\n\r\n      return True\r\n",
        metadata={
            "language": "python",
            "chunk_index": "caller-value",
            "chunk_count": "caller-value",
        },
    )
    original_metadata = document.metadata.copy()

    chunks = chunk_document(document)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.document_id == document.document_id
    assert chunk.source == document.source
    assert chunk.path == document.path
    assert chunk.chunk_type == document.document_type
    assert chunk.line_range == LineRange(start=1, end=3)
    assert chunk.content == document.content
    assert chunk.metadata == {
        "language": "python",
        "chunk_index": "1",
        "chunk_count": "1",
    }
    assert document.metadata == original_metadata


@pytest.mark.parametrize(
    ("document_type", "content"),
    [
        (ChunkType.CODE, "def run():\n    pass\n"),
        (ChunkType.MARKDOWN, "# Heading\n\nBody\n"),
        (ChunkType.LOG, "INFO start\nERROR failed\n"),
        (ChunkType.CI_JSON, '{"status":"failed"}\n'),
        (ChunkType.TEXT, "plain text\n"),
    ],
)
def test_chunk_document_supports_each_declared_type(
    document_type: ChunkType,
    content: str,
) -> None:
    chunks = chunk_document(make_document(document_type=document_type, content=content))

    assert [chunk.chunk_type for chunk in chunks] == [document_type]


def test_line_windows_use_one_based_ranges_and_overlap() -> None:
    chunks = chunk_document(
        make_document(content=numbered_lines(7)),
        config=ChunkingConfig(max_lines=3, overlap_lines=1, max_chars=100),
    )

    assert [chunk.line_range for chunk in chunks] == [
        LineRange(start=1, end=3),
        LineRange(start=3, end=5),
        LineRange(start=5, end=7),
    ]
    assert [chunk.content for chunk in chunks] == [
        numbered_lines(3),
        "line-3\nline-4\nline-5\n",
        "line-5\nline-6\nline-7\n",
    ]


def test_line_windows_without_overlap_cover_each_line_once() -> None:
    content = numbered_lines(7)

    chunks = chunk_document(
        make_document(content=content),
        config=ChunkingConfig(max_lines=3, overlap_lines=0, max_chars=100),
    )

    assert [chunk.line_range for chunk in chunks] == [
        LineRange(start=1, end=3),
        LineRange(start=4, end=6),
        LineRange(start=7, end=7),
    ]
    assert "".join(chunk.content for chunk in chunks) == content


def test_document_with_exact_max_lines_creates_one_chunk() -> None:
    chunks = chunk_document(
        make_document(content=numbered_lines(3)),
        config=ChunkingConfig(max_lines=3, overlap_lines=1, max_chars=100),
    )

    assert len(chunks) == 1
    assert chunks[0].line_range == LineRange(start=1, end=3)


def test_oversized_window_prefers_physical_line_boundaries() -> None:
    content = "aa\nbbb\ncccc\n"

    chunks = chunk_document(
        make_document(content=content),
        config=ChunkingConfig(max_lines=10, overlap_lines=0, max_chars=7),
    )

    assert [chunk.content for chunk in chunks] == ["aa\nbbb\n", "cccc\n"]
    assert [chunk.line_range for chunk in chunks] == [
        LineRange(start=1, end=2),
        LineRange(start=3, end=3),
    ]
    assert "".join(chunk.content for chunk in chunks) == content


def test_oversized_single_line_uses_same_line_range_and_unique_ids() -> None:
    chunks = chunk_document(
        make_document(content="aaaaaaa"),
        config=ChunkingConfig(max_lines=10, overlap_lines=0, max_chars=3),
    )

    assert [chunk.content for chunk in chunks] == ["aaa", "aaa", "a"]
    assert [chunk.line_range for chunk in chunks] == [
        LineRange(start=1, end=1),
        LineRange(start=1, end=1),
        LineRange(start=1, end=1),
    ]
    assert len({chunk.chunk_id for chunk in chunks}) == 3


def test_oversized_line_keeps_trailing_newline_without_blank_chunk() -> None:
    chunks = chunk_document(
        make_document(content="abcd\n"),
        config=ChunkingConfig(max_lines=10, overlap_lines=0, max_chars=4),
    )

    assert "".join(chunk.content for chunk in chunks) == "abcd\n"
    assert all(chunk.content.strip() for chunk in chunks)
    assert all(len(chunk.content) <= 4 for chunk in chunks)
    assert all(chunk.line_range == LineRange(start=1, end=1) for chunk in chunks)


def test_impossible_blank_fragment_returns_sanitized_chunking_error() -> None:
    document = make_document(path="src/tiny.txt", content="a\n")

    with pytest.raises(ChunkingError) as error:
        chunk_document(
            document,
            config=ChunkingConfig(max_lines=1, overlap_lines=0, max_chars=1),
        )

    assert "src/tiny.txt" in str(error.value)
    assert "a\n" not in str(error.value)


def test_every_chunk_respects_line_and_character_limits() -> None:
    chunks = chunk_document(
        make_document(content=numbered_lines(20)),
        config=ChunkingConfig(max_lines=4, overlap_lines=1, max_chars=20),
    )

    assert all(len(chunk.content) <= 20 for chunk in chunks)
    assert all(
        chunk.line_range.end - chunk.line_range.start + 1 <= 4 for chunk in chunks
    )


def test_crlf_and_missing_final_newline_are_preserved() -> None:
    content = "first\r\nsecond\r\nthird"

    chunks = chunk_document(
        make_document(content=content),
        config=ChunkingConfig(max_lines=2, overlap_lines=0, max_chars=100),
    )

    assert "".join(chunk.content for chunk in chunks) == content
    assert chunks[-1].content == "third"


@pytest.mark.parametrize(
    "content",
    [
        '{"status":"failed"}',
        '[{"job":"tests"},{"job":"lint"}]',
        '{\n  "status": "failed",\n  "jobs": []\n}\n',
    ],
)
def test_ci_json_accepts_valid_original_content(content: str) -> None:
    chunks = chunk_document(
        make_document(
            path="ci/run.json",
            document_type=ChunkType.CI_JSON,
            content=content,
        ),
        config=ChunkingConfig(max_lines=2, overlap_lines=0, max_chars=100),
    )

    assert "".join(chunk.content for chunk in chunks) == content


def test_ci_json_rejects_invalid_content_without_leaking_body() -> None:
    secret_content = '{"token":"super-secret-token"'
    document = make_document(
        path="ci/run.json",
        document_type=ChunkType.CI_JSON,
        content=secret_content,
    )

    with pytest.raises(ChunkingError) as error:
        chunk_document(document)

    assert "ci/run.json" in str(error.value)
    assert "super-secret-token" not in str(error.value)


def test_chunk_ids_are_stable_unique_and_well_formed() -> None:
    document = make_document(content=numbered_lines(7))
    config = ChunkingConfig(max_lines=3, overlap_lines=1, max_chars=100)

    first = chunk_document(document, config=config)
    second = chunk_document(document, config=config)

    first_ids = [chunk.chunk_id for chunk in first]
    assert first_ids == [chunk.chunk_id for chunk in second]
    assert len(first_ids) == len(set(first_ids))
    assert all(re.fullmatch(r"chk_[0-9a-f]{24}", chunk_id) for chunk_id in first_ids)


def test_chunk_id_matches_fixed_cross_process_baseline() -> None:
    document = make_document(
        document_id="doc-stable",
        path="src/stable.py",
        content="alpha\nbeta\n",
        metadata={},
    )

    chunk = chunk_document(
        document,
        config=ChunkingConfig(max_lines=2, overlap_lines=0, max_chars=100),
    )[0]

    assert chunk.chunk_id == "chk_2f23b8520950ef12d683488e"


def test_chunk_id_changes_with_content_path_and_window() -> None:
    base = make_document(content=numbered_lines(4))
    config = ChunkingConfig(max_lines=2, overlap_lines=0, max_chars=100)
    base_id = chunk_document(base, config=config)[0].chunk_id

    changed_content_id = chunk_document(
        make_document(content="changed\n" + numbered_lines(3)),
        config=config,
    )[0].chunk_id
    changed_path_id = chunk_document(
        make_document(path="src/other.py", content=numbered_lines(4)),
        config=config,
    )[0].chunk_id
    changed_window_id = chunk_document(
        base,
        config=ChunkingConfig(max_lines=3, overlap_lines=0, max_chars=100),
    )[0].chunk_id

    assert len({base_id, changed_content_id, changed_path_id, changed_window_id}) == 4


def test_chunk_metadata_records_one_based_index_and_total_count() -> None:
    chunks = chunk_document(
        make_document(content=numbered_lines(5), metadata={"language": "python"}),
        config=ChunkingConfig(max_lines=2, overlap_lines=0, max_chars=100),
    )

    assert [chunk.metadata for chunk in chunks] == [
        {"language": "python", "chunk_index": "1", "chunk_count": "3"},
        {"language": "python", "chunk_index": "2", "chunk_count": "3"},
        {"language": "python", "chunk_index": "3", "chunk_count": "3"},
    ]


def test_unicode_content_produces_stable_id() -> None:
    document = make_document(
        path="logs/agent.log",
        document_type=ChunkType.LOG,
        content="开始执行\n权限校验失败\n",
    )

    first = chunk_document(document)
    second = chunk_document(document)

    assert first[0].chunk_id == second[0].chunk_id
