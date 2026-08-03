from collections.abc import Sequence

import pytest

from devagent.memory import (
    Chunk,
    ChunkType,
    Document,
    KeywordRetriever,
    RetrievalError,
    RetrievalResult,
)
from devagent.memory.embeddings import EmbeddingVector
from devagent.tools.knowledge_service import (
    CachedHybridRetrieverFactory,
    KnowledgeServiceError,
    WorkspaceKnowledgeService,
)


class CountingEmbeddingProvider:
    provider_name = "counting"

    def __init__(self) -> None:
        self.document_calls = 0

    def embed_documents(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        self.document_calls += 1
        return [(1.0, float(index + 1)) for index, _ in enumerate(texts)]

    def embed_query(self, text: str) -> EmbeddingVector:
        return (1.0, 1.0)


def make_documents() -> list[Document]:
    return [
        Document(
            document_id="doc-uploader",
            source="workspace",
            path="src/uploader.py",
            document_type=ChunkType.CODE,
            content="def build_upload_timeout():\n    return 3\n",
        ),
        Document(
            document_id="doc-notes",
            source="workspace",
            path="docs/notes.md",
            document_type=ChunkType.MARKDOWN,
            content="# Upload timeout design\n",
        ),
    ]


def test_workspace_knowledge_service_uses_injected_factory_once() -> None:
    loader_calls: list[str] = []
    factory_calls: list[tuple[Chunk, ...]] = []

    def load(workspace: str) -> list[Document]:
        loader_calls.append(workspace)
        return make_documents()

    def factory(chunks: Sequence[Chunk]) -> KeywordRetriever:
        snapshot = tuple(chunks)
        factory_calls.append(snapshot)
        return KeywordRetriever(snapshot)

    service = WorkspaceKnowledgeService(
        document_loader=load,
        retriever_factory=factory,
    )

    result = service.retrieve("upload timeout", "workspace", 2)

    assert loader_calls == ["workspace"]
    assert len(factory_calls) == 1
    assert {chunk.path for chunk in factory_calls[0]} == {
        "src/uploader.py",
        "docs/notes.md",
    }
    assert [item.rank for item in result.items] == list(range(1, len(result.items) + 1))


def test_workspace_knowledge_service_defaults_to_keyword_retrieval() -> None:
    service = WorkspaceKnowledgeService(
        document_loader=lambda workspace: make_documents()
    )

    result = service.retrieve("build upload timeout", "workspace", 1)

    assert result.items[0].path == "src/uploader.py"
    assert result.items[0].metadata["retrieval_method"] == "bm25"


def test_workspace_knowledge_service_converts_controlled_retrieval_error() -> None:
    class FailingRetriever:
        def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalResult:
            raise RetrievalError("top_k contract failed")

    service = WorkspaceKnowledgeService(
        document_loader=lambda workspace: make_documents(),
        retriever_factory=lambda chunks: FailingRetriever(),
    )

    with pytest.raises(KnowledgeServiceError, match="top_k contract failed"):
        service.retrieve("upload timeout", "workspace", 2)


def test_workspace_knowledge_service_does_not_hide_programming_errors() -> None:
    def broken_factory(chunks: Sequence[Chunk]) -> KeywordRetriever:
        raise RuntimeError("factory bug")

    service = WorkspaceKnowledgeService(
        document_loader=lambda workspace: make_documents(),
        retriever_factory=broken_factory,
    )

    with pytest.raises(RuntimeError, match="factory bug"):
        service.retrieve("upload timeout", "workspace", 2)


def test_cached_hybrid_factory_reuses_snapshot_and_invalidates_on_content() -> None:
    documents = make_documents()
    provider = CountingEmbeddingProvider()
    factory = CachedHybridRetrieverFactory(embedding_provider=provider)
    service = WorkspaceKnowledgeService(
        document_loader=lambda workspace: documents,
        retriever_factory=factory,
    )

    first = service.retrieve("upload timeout", "workspace", 2)
    second = service.retrieve("upload timeout", "workspace", 2)
    documents = [
        documents[0].model_copy(update={"content": "changed upload timeout"}),
        documents[1],
    ]
    third = service.retrieve("upload timeout", "workspace", 2)

    assert first.items
    assert second.items
    assert third.items
    assert provider.document_calls == 2
