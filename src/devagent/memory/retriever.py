import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite, log
from time import perf_counter

from .models import Chunk, EvidenceSnippet, RetrievalResult

# * 提取代码标识符、数字和连续中文。
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]+")

# * 把 camelCase、PascalCase 和缩写标识符拆成自然语言子词。
CAMEL_PATTERN = re.compile(
    r"""
    [A-Z]+(?=[A-Z][a-z]|$)
    |
    [A-Z]?[a-z]+
    |
    \d+
    """,
    re.VERBOSE,
)


def _split_camel(token: str) -> list[str]:
    return CAMEL_PATTERN.findall(token)


def _tokenize(text: str) -> list[str]:
    result: list[str] = []
    for raw_token in TOKEN_PATTERN.findall(text):
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", raw_token):
            expanded = [raw_token]
            expanded.extend(
                raw_token[index : index + 2] for index in range(len(raw_token) - 1)
            )
        else:
            expanded = [raw_token.casefold()]
            for snake_part in raw_token.split("_"):
                expanded.extend(part.casefold() for part in _split_camel(snake_part))
        # * 单次标识符展开去重，但保留文本中重复出现的词频。
        result.extend(dict.fromkeys(token for token in expanded if token))
    return result


class RetrievalError(ValueError):
    """查询或索引不满足检索契约。"""


@dataclass(frozen=True)
class BM25Config:
    k1: float = 1.5  # * 词频饱和速度
    b: float = 0.75  # * 文档长度归一化强度
    max_excerpt_chars: int = 2000  # * 单条 EvidenceSnippet 的最大字符数

    def __post_init__(self) -> None:
        if isinstance(self.k1, bool) or not isinstance(self.k1, (int, float)):
            raise TypeError("k1 必须是数值")
        if isinstance(self.b, bool) or not isinstance(self.b, (int, float)):
            raise TypeError("b 必须是数值")
        if isinstance(self.max_excerpt_chars, bool) or not isinstance(
            self.max_excerpt_chars, int
        ):
            raise TypeError("max_excerpt_chars 必须是整数")
        if not isfinite(self.k1) or not isfinite(self.b):
            raise ValueError("k1 和 b 必须是有限数值")
        if self.k1 <= 0:
            raise ValueError("k1 必须大于 0")
        if not (0 <= self.b <= 1):
            raise ValueError("b 必须位于 0 到 1")
        if not 1 <= self.max_excerpt_chars <= 2000:
            raise ValueError("max_excerpt_chars 必须位于 1 到 2000")


@dataclass(frozen=True)
class _IndexedChunk:
    chunk: Chunk
    tokens: tuple[str, ...]
    term_frequencies: Counter[str]


@dataclass(frozen=True)
class _ScoredChunk:
    chunk: Chunk
    score: float


class KeywordRetriever:
    """
    基于关键词的检索器。
    """

    def __init__(
        self, chunks: Sequence[Chunk], *, config: BM25Config | None = None
    ) -> None:
        self.config = config or BM25Config()
        chunk_snapshot = tuple(chunks)

        chunk_ids = [chunk.chunk_id for chunk in chunk_snapshot]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise RetrievalError("chunk_id 必须唯一")

        indexed_chunks: list[_IndexedChunk] = []
        document_frequencies: Counter[str] = Counter()
        total_token_count = 0

        for chunk in chunk_snapshot:
            index_text = f"{chunk.path}\n{chunk.content}"
            tokens = tuple(_tokenize(index_text))
            term_frequencies = Counter(tokens)
            indexed_chunks.append(
                _IndexedChunk(
                    chunk=chunk, tokens=tokens, term_frequencies=term_frequencies
                )
            )
            document_frequencies.update(set(tokens))
            total_token_count += len(tokens)

        self._indexed_chunks = tuple(indexed_chunks)
        self._document_frequencies = document_frequencies
        self._average_document_length = (
            total_token_count / len(chunk_snapshot) if chunk_snapshot else 0.0
        )

    def _score_chunk(
        self, indexed_chunk: _IndexedChunk, query_terms: set[str]
    ) -> float:
        if not query_terms or not indexed_chunk.tokens:
            return 0.0

        document_count = len(self._indexed_chunks)
        if document_count == 0 or self._average_document_length == 0:
            return 0.0

        document_length = len(indexed_chunk.tokens)
        length_normalization = self.config.k1 * (
            1
            - self.config.b
            + self.config.b * document_length / self._average_document_length
        )

        score = 0.0
        for term in sorted(query_terms):
            term_frequency = indexed_chunk.term_frequencies.get(term, 0)
            if term_frequency == 0:
                continue

            document_frequency = self._document_frequencies[term]
            inverse_document_frequency = log(
                1
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            score += (
                inverse_document_frequency
                * (term_frequency * (self.config.k1 + 1))
                / (term_frequency + length_normalization)
            )

        return score

    def _rank_candidates(self, query_terms: set[str]) -> list[_ScoredChunk]:
        candidates: list[_ScoredChunk] = []

        for indexed_chunk in self._indexed_chunks:
            score = self._score_chunk(indexed_chunk, query_terms)
            if score > 0:
                candidates.append(_ScoredChunk(chunk=indexed_chunk.chunk, score=score))
        return sorted(
            candidates,
            key=lambda item: (
                -item.score,
                item.chunk.path,
                item.chunk.line_range.start,
                item.chunk.chunk_id,
            ),
        )

    def retrieve(self, query: str, *, top_k: int = 5) -> RetrievalResult:
        started = perf_counter()

        normalized_query, query_terms = _prepare_query(query)
        _validate_top_k(top_k)

        candidates = self._rank_candidates(query_terms)
        selected = candidates[:top_k]

        snippets: list[EvidenceSnippet] = []
        excerpt_was_truncated = False

        for rank, candidate in enumerate(selected, start=1):
            chunk = candidate.chunk
            excerpt, start_char, end_char = _build_excerpt(
                chunk.content, query_terms, max_chars=self.config.max_excerpt_chars
            )
            excerpt_was_truncated |= len(excerpt) < len(chunk.content)

            snippets.append(
                EvidenceSnippet(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    source=chunk.source,
                    path=chunk.path,
                    line_range=chunk.line_range,
                    excerpt=excerpt,
                    score=candidate.score,
                    rank=rank,
                    metadata={
                        **chunk.metadata,
                        "retrieval_method": "bm25",
                        "excerpt_start_char": str(start_char),
                        "excerpt_end_char": str(end_char),
                    },
                )
            )
        return RetrievalResult(
            query=normalized_query,
            top_k=top_k,
            total_candidates=len(candidates),
            items=snippets,
            retrieval_ms=(perf_counter() - started) * 1000,
            truncated=len(candidates) > len(selected) or excerpt_was_truncated,
        )


def _prepare_query(query: str) -> tuple[str, set[str]]:
    if not isinstance(query, str):
        raise RetrievalError("query 必须是字符串")
    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalError("query 不能为空")
    if len(normalized_query) > 2000:
        raise RetrievalError("query 长度不能超过 2000 字符")

    query_terms = set(_tokenize(normalized_query))
    if not query_terms:
        raise RetrievalError("query 必须包含可检索关键词")

    return normalized_query, query_terms


def _validate_top_k(top_k: int) -> None:
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise RetrievalError("top_k 必须是整数")
    if not 1 <= top_k <= 50:
        raise RetrievalError("top_k 必须位于 1 到 50")


def _build_excerpt(
    content: str, query_tokens: set[str], *, max_chars: int
) -> tuple[str, int, int]:
    if len(content) <= max_chars:
        return content, 0, len(content)

    folded_content = content.casefold()
    positions: list[int] = []

    for token in sorted(query_tokens):
        position = folded_content.find(token.casefold())
        if position >= 0:
            positions.append(position)

    if positions:
        anchor = min(positions)
    else:
        first_non_whitespace = re.search(r"\S", content)
        anchor = first_non_whitespace.start() if first_non_whitespace else 0

    # * 保留约三分之一前文和三分之二后文。
    start = max(0, anchor - max_chars // 3)
    end = min(len(content), start + max_chars)
    start = max(0, end - max_chars)

    return content[start:end], start, end
