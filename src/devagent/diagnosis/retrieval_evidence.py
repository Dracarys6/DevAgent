from collections.abc import Collection

from devagent.memory import EvidenceSnippet, RetrievalResult

from .models import Evidence, EvidenceKind

MAX_EVIDENCE_EXCERPT_CHARS = 4_000


def map_retrieval_evidence(
    result: RetrievalResult,
    *,
    start_index: int,
    max_total_chars: int = MAX_EVIDENCE_EXCERPT_CHARS,
    excluded_chunk_ids: Collection[str] = (),
    preferred_paths: Collection[str] = (),
) -> list[Evidence]:
    """把检索片段绑定为有界业务 Evidence，并按 chunk_id 去重。"""
    if isinstance(start_index, bool) or not isinstance(start_index, int):
        raise TypeError("start_index 必须是整数")
    if start_index < 1:
        raise ValueError("start_index 必须大于或等于 1")
    if isinstance(max_total_chars, bool) or not isinstance(max_total_chars, int):
        raise TypeError("max_total_chars 必须是整数")
    if not 1 <= max_total_chars <= 20_000:
        raise ValueError("max_total_chars 必须位于 1 到 20000")

    evidence: list[Evidence] = []
    remaining_chars = max_total_chars
    seen_chunk_ids = set(excluded_chunk_ids)
    preferred_path_set = set(preferred_paths)
    seen_locations: set[tuple[str, str, int, int]] = set()
    ordered_items = sorted(
        result.items,
        key=lambda item: (item.path not in preferred_path_set, item.rank),
    )
    for item in ordered_items:
        location = (
            item.source,
            item.path,
            item.line_range.start,
            item.line_range.end,
        )
        if item.chunk_id in seen_chunk_ids or location in seen_locations:
            continue
        excerpt = item.excerpt[: min(MAX_EVIDENCE_EXCERPT_CHARS, remaining_chars)]
        if not excerpt.strip():
            continue
        seen_chunk_ids.add(item.chunk_id)
        seen_locations.add(location)
        evidence.append(
            Evidence(
                evidence_id=f"E{start_index + len(evidence)}",
                kind=EvidenceKind.KNOWLEDGE,
                tool_name="knowledge_retrieve",
                source=item.source,
                locator=_build_locator(item),
                excerpt=excerpt,
                metadata=_build_metadata(item, result=result),
            )
        )
        remaining_chars -= len(excerpt)
        if remaining_chars == 0:
            break
    return evidence


def _build_locator(item: EvidenceSnippet) -> str:
    return (
        f"path={item.path};"
        f"lines={item.line_range.start}-{item.line_range.end};"
        f"chunk_id={item.chunk_id};"
        f"rank={item.rank}"
    )


def _build_metadata(
    item: EvidenceSnippet,
    *,
    result: RetrievalResult,
) -> dict[str, str]:
    metadata = {
        "retrieval_rank": str(item.rank),
        "retrieval_score": repr(item.score),
        "retrieval_ms": repr(result.retrieval_ms),
    }
    for key in (
        "retrieval_method",
        "candidate_sources",
        "reranker",
        "rerank_status",
        "rerank_error_code",
        "recall_rank",
        "recall_score",
        "rerank_score",
    ):
        value = item.metadata.get(key)
        if value is not None:
            metadata[key] = value
    return metadata
