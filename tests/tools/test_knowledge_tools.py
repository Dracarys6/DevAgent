from pathlib import Path

import pytest

from devagent.memory import ChunkType
from devagent.tools import knowledge_tools
from devagent.tools.knowledge_tools import (
    KnowledgeRetrieveArgs,
    KnowledgeRetrieveError,
    _build_document_id,
    _discover_knowledge_files,
    _load_documents,
    knowledge_retrieve,
    load_workspace_documents,
)


def test_knowledge_retrieve_args_validation() -> None:
    # * 合法参数应保持原值。
    valid_args = KnowledgeRetrieveArgs(
        workspace="valid_workspace", query="valid_query", top_k=5
    )
    assert valid_args.workspace == "valid_workspace"
    assert valid_args.query == "valid_query"
    assert valid_args.top_k == 5

    # * 参数模型必须在工具执行前拒绝非法边界。
    with pytest.raises(ValueError):
        KnowledgeRetrieveArgs(workspace="valid_workspace", query="", top_k=5)

    with pytest.raises(ValueError):
        KnowledgeRetrieveArgs(workspace="valid_workspace", query="valid_query", top_k=0)


def test_discover_knowledge_files_is_sorted_and_filters_content(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "src" / "b.md").write_text("beta", encoding="utf-8")
    (tmp_path / "src" / "a.py").write_text("alpha", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"image")
    (tmp_path / ".venv" / "hidden.py").write_text("hidden", encoding="utf-8")

    knowledge_files = _discover_knowledge_files(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in knowledge_files] == [
        "src/a.py",
        "src/b.md",
    ]


def test_discover_knowledge_files_skips_external_symlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)

    assert _discover_knowledge_files(tmp_path) == []


def test_discover_knowledge_files_rejects_missing_workspace(
    tmp_path: Path,
) -> None:
    with pytest.raises(KnowledgeRetrieveError, match="不存在"):
        _discover_knowledge_files(tmp_path / "missing")


def test_build_document_id_uniqueness() -> None:
    # * 相对路径是稳定文档身份的一部分。
    doc_id1 = _build_document_id("path/to/file1.txt")
    doc_id2 = _build_document_id("path/to/file2.txt")
    assert doc_id1 != doc_id2

    doc_id3 = _build_document_id("path/to/file1.txt")
    assert doc_id1 == doc_id3


def test_load_documents_rejects_missing_file(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing_file.txt"

    with pytest.raises(KnowledgeRetrieveError):
        _load_documents(tmp_path, [missing_file])


def test_load_documents_accepts_valid_file(tmp_path: Path) -> None:
    valid_file = tmp_path / "sample.txt"
    valid_file.write_text("This is a valid file.", encoding="utf-8")

    documents = _load_documents(tmp_path, [valid_file])
    assert len(documents) == 1
    assert documents[0].path == valid_file.relative_to(tmp_path).as_posix()
    assert documents[0].content == "This is a valid file."


def test_load_workspace_documents_reuses_discovery_and_loading(
    tmp_path: Path,
) -> None:
    (tmp_path / "b.md").write_text("markdown", encoding="utf-8")
    (tmp_path / "a.py").write_text("python", encoding="utf-8")
    (tmp_path / "ignored.bin").write_bytes(b"binary")

    documents = load_workspace_documents(tmp_path)

    assert [document.path for document in documents] == ["a.py", "b.md"]
    assert [document.content for document in documents] == ["python", "markdown"]


def test_load_documents_preserves_document_metadata(tmp_path: Path) -> None:
    path = tmp_path / "src" / "app.py"
    path.parent.mkdir()
    path.write_text("def run():\n    pass", encoding="utf-8")

    document = _load_documents(tmp_path, [path])[0]

    assert document.source == "workspace"
    assert document.path == "src/app.py"
    assert document.document_type == ChunkType.CODE
    assert document.metadata["file_suffix"] == ".py"
    assert document.document_id == _build_document_id("src/app.py")


def test_load_documents_skips_blank_files(tmp_path: Path) -> None:
    path = tmp_path / "blank.txt"
    path.write_text("   \n\t   ", encoding="utf-8")

    assert _load_documents(tmp_path, [path]) == []


def test_load_documents_rejects_external_path(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(KnowledgeRetrieveError, match="工作区之外"):
        _load_documents(tmp_path, [outside])


def test_load_documents_rejects_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(KnowledgeRetrieveError, match="UTF-8"):
        _load_documents(tmp_path, [path])


def test_load_documents_rejects_oversized_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "large.txt"
    path.write_text("abcdef", encoding="utf-8")
    monkeypatch.setattr(knowledge_tools, "MAX_KNOWLEDGE_FILE_CHARS", 5)

    with pytest.raises(KnowledgeRetrieveError, match="文件字符数"):
        _load_documents(tmp_path, [path])


def test_load_documents_rejects_oversized_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("abcd", encoding="utf-8")
    second.write_text("efgh", encoding="utf-8")
    monkeypatch.setattr(knowledge_tools, "MAX_TOTAL_KNOWLEDGE_CHARS", 7)

    with pytest.raises(KnowledgeRetrieveError, match="总字符数"):
        _load_documents(tmp_path, [first, second])


def test_knowledge_retrieve_returns_ranked_workspace_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "logs").mkdir()

    (tmp_path / "src" / "uploader.py").write_text(
        "def build_upload_timeout(size_mb, bandwidth_mb_s):\n"
        "    return size_mb / bandwidth_mb_s\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_uploader.py").write_text(
        "def test_large_upload_uses_dynamic_timeout(): pass\n",
        encoding="utf-8",
    )
    (tmp_path / "logs" / "task.log").write_text(
        "UploadTimeoutError after 3 seconds\n",
        encoding="utf-8",
    )

    result = knowledge_retrieve("upload timeout", tmp_path, top_k=3)

    assert 1 <= len(result.items) <= 3
    assert "src/uploader.py" in {item.path for item in result.items}
    assert all(item.source == "workspace" for item in result.items)
    assert all(item.score > 0 for item in result.items)
    assert [item.rank for item in result.items] == list(range(1, len(result.items) + 1))


def test_knowledge_retrieve_returns_empty_result_without_match(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.txt").write_text("hello world", encoding="utf-8")

    result = knowledge_retrieve("permission manager", tmp_path)

    assert result.total_candidates == 0
    assert result.items == []
    assert result.truncated is False


def test_knowledge_retrieve_accepts_empty_workspace(tmp_path: Path) -> None:
    result = knowledge_retrieve("upload timeout", tmp_path)

    assert result.items == []
    assert result.total_candidates == 0


def test_knowledge_retrieve_converts_chunking_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "broken.json").write_text("{invalid", encoding="utf-8")

    with pytest.raises(KnowledgeRetrieveError, match="CI JSON"):
        knowledge_retrieve("pipeline failure", tmp_path)


def _write_workspace_fixture(root: Path) -> None:
    files = {
        "src/uploader.py": (
            "build_upload_timeout calculates timeout from size_mb and bandwidth_mb_s"
        ),
        "tests/test_uploader.py": "test_large_upload_uses_dynamic_timeout",
        "src/event/bus.py": "EventBus publish subscribe",
        "docs/permissions.md": "PermissionManager validates shell risk",
        "logs/task.log": "UploadTimeoutError after 3 seconds",
    }

    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_knowledge_retrieve_top_5_workspace_baseline(
    tmp_path: Path,
) -> None:
    _write_workspace_fixture(tmp_path)
    cases = [
        ("build upload timeout", {"src/uploader.py"}),
        ("large upload dynamic timeout test", {"tests/test_uploader.py"}),
        ("event bus publish subscribe", {"src/event/bus.py"}),
        ("permission manager shell risk", {"docs/permissions.md"}),
        ("UploadTimeoutError seconds", {"logs/task.log"}),
    ]

    hit_count = 0
    for query, expected_paths in cases:
        result = knowledge_retrieve(query, tmp_path, top_k=5)
        actual_paths = {item.path for item in result.items}
        hit_count += bool(actual_paths & expected_paths)

        assert all(item.source == "workspace" for item in result.items)
        assert all(item.line_range.start >= 1 for item in result.items)
        assert all(item.score > 0 for item in result.items)

    assert hit_count / len(cases) >= 0.8


def test_knowledge_retrieve_returns_bounded_context(
    tmp_path: Path,
) -> None:
    path = tmp_path / "src" / "uploader.py"
    path.parent.mkdir(parents=True)
    content = (
        "unrelated context line\n" * 600
        + "\ndef build_upload_timeout():\n"
        + "    return timeout\n"
    )
    path.write_text(content, encoding="utf-8")

    result = knowledge_retrieve("build upload timeout", tmp_path, top_k=1)
    returned_chars = sum(len(item.excerpt) for item in result.items)
    context_reduction = 1 - returned_chars / len(content)

    assert len(result.items) == 1
    assert "build_upload_timeout" in result.items[0].excerpt
    assert len(result.items[0].excerpt) <= 2000
    assert result.items[0].path == "src/uploader.py"
    assert context_reduction >= 0.4


def test_knowledge_retrieve_excludes_unsafe_and_ignored_files(
    tmp_path: Path,
) -> None:
    ignored = tmp_path / ".venv" / "secret.py"
    ignored.parent.mkdir()
    ignored.write_text("private_token", encoding="utf-8")

    binary = tmp_path / "secret.bin"
    binary.write_bytes(b"private_token")

    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("private_token", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)

    result = knowledge_retrieve("private_token", tmp_path)

    assert result.items == []
    assert result.total_candidates == 0


def test_discover_knowledge_files_enforces_file_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "first.py").write_text("first", encoding="utf-8")
    (tmp_path / "second.py").write_text("second", encoding="utf-8")
    monkeypatch.setattr(knowledge_tools, "MAX_KNOWLEDGE_FILES", 1)

    with pytest.raises(KnowledgeRetrieveError, match="文件数量"):
        _discover_knowledge_files(tmp_path)
