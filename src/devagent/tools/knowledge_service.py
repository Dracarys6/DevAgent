from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Protocol

from devagent.memory import (
    Chunk,
    ChunkingError,
    Document,
    HybridRetrievalError,
    HybridRetriever,
    HybridRetrieverConfig,
    KeywordRetriever,
    RerankingError,
    RetrievalError,
    RetrievalResult,
    Retriever,
    VectorRetrievalError,
    VectorRetriever,
    VectorRetrieverConfig,
    chunk_document,
)
from devagent.memory.embeddings import EmbeddingProvider


class KnowledgeServiceError(RuntimeError):
    """工作区文档无法构建为可信检索结果。"""


class KnowledgeRetrieverFactory(Protocol):
    def __call__(self, chunks: Sequence[Chunk]) -> Retriever: ...


DocumentLoader = Callable[[str | Path], list[Document]]


class CachedHybridRetrieverFactory:
    """按 chunk 内容快照复用进程内 Hybrid 索引。"""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        hybrid_config: HybridRetrieverConfig | None = None,
        vector_config: VectorRetrieverConfig | None = None,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._hybrid_config = hybrid_config
        self._vector_config = vector_config
        self._snapshot_key: tuple[tuple[str, str], ...] | None = None
        self._retriever: Retriever | None = None
        self._lock = RLock()

    def __call__(self, chunks: Sequence[Chunk]) -> Retriever:
        chunk_snapshot = tuple(chunks)
        snapshot_key = tuple(
            (
                chunk.chunk_id,
                sha256(chunk.content.encode("utf-8")).hexdigest(),
            )
            for chunk in chunk_snapshot
        )
        with self._lock:
            if snapshot_key == self._snapshot_key and self._retriever is not None:
                return self._retriever
            retriever = HybridRetriever(
                keyword_retriever=KeywordRetriever(chunk_snapshot),
                vector_retriever=VectorRetriever(
                    chunk_snapshot,
                    embedding_provider=self._embedding_provider,
                    config=self._vector_config,
                ),
                config=self._hybrid_config,
            )
            self._snapshot_key = snapshot_key
            self._retriever = retriever
            return retriever


class WorkspaceKnowledgeService:
    """加载安全工作区文档，并把检索策略留给 composition root 注入。"""

    def __init__(
        self,
        *,
        document_loader: DocumentLoader,
        retriever_factory: KnowledgeRetrieverFactory | None = None,
    ) -> None:
        self._document_loader = document_loader
        self._retriever_factory = retriever_factory or _create_keyword_retriever

    def retrieve(
        self,
        query: str,
        workspace: str | Path,
        top_k: int = 5,
    ) -> RetrievalResult:
        documents = self._document_loader(workspace)
        try:
            chunks = [
                chunk for document in documents for chunk in chunk_document(document)
            ]
            retriever = self._retriever_factory(chunks)
            return retriever.retrieve(query, top_k=top_k)
        except (
            ChunkingError,
            RetrievalError,
            VectorRetrievalError,
            HybridRetrievalError,
            RerankingError,
        ) as exc:
            # * 这些领域异常已在各自边界完成脱敏，保留类型相关的调试信息。
            raise KnowledgeServiceError(str(exc)) from exc


def _create_keyword_retriever(chunks: Sequence[Chunk]) -> Retriever:
    return KeywordRetriever(chunks)
