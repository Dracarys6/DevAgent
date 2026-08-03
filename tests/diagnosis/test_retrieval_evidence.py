import pytest

from devagent.diagnosis import EvidenceKind, map_retrieval_evidence
from devagent.memory import EvidenceSnippet, LineRange, RetrievalResult


def make_result() -> RetrievalResult:
    return RetrievalResult(
        query="upload timeout",
        top_k=2,
        total_candidates=3,
        retrieval_ms=12.5,
        truncated=True,
        items=[
            EvidenceSnippet(
                chunk_id="chunk-1",
                document_id="doc-1",
                source="workspace",
                path="src/uploader.py",
                line_range=LineRange(start=10, end=20),
                excerpt="a" * 80,
                score=0.9,
                rank=1,
                metadata={
                    "retrieval_method": "hybrid_rrf",
                    "candidate_sources": "bm25,vector",
                    "rerank_status": "fallback",
                    "rerank_error_code": "provider_error",
                },
            ),
            EvidenceSnippet(
                chunk_id="chunk-2",
                document_id="doc-2",
                source="workspace",
                path="docs/upload.md",
                line_range=LineRange(start=1, end=5),
                excerpt="b" * 80,
                score=0.8,
                rank=2,
            ),
        ],
    )


def test_map_retrieval_evidence_preserves_identity_and_observation() -> None:
    evidence = map_retrieval_evidence(make_result(), start_index=3)

    assert [item.evidence_id for item in evidence] == ["E3", "E4"]
    assert all(item.kind == EvidenceKind.KNOWLEDGE for item in evidence)
    assert evidence[0].tool_name == "knowledge_retrieve"
    assert evidence[0].source == "workspace"
    assert evidence[0].locator == (
        "path=src/uploader.py;lines=10-20;chunk_id=chunk-1;rank=1"
    )
    assert evidence[0].metadata == {
        "retrieval_rank": "1",
        "retrieval_score": "0.9",
        "retrieval_ms": "12.5",
        "retrieval_method": "hybrid_rrf",
        "candidate_sources": "bm25,vector",
        "rerank_status": "fallback",
        "rerank_error_code": "provider_error",
    }


def test_map_retrieval_evidence_enforces_total_budget_and_exclusion() -> None:
    evidence = map_retrieval_evidence(
        make_result(),
        start_index=7,
        max_total_chars=50,
        excluded_chunk_ids={"chunk-1"},
    )

    assert [item.evidence_id for item in evidence] == ["E7"]
    assert "chunk_id=chunk-2" in evidence[0].locator
    assert len(evidence[0].excerpt) == 50


def test_map_retrieval_evidence_deduplicates_same_source_location() -> None:
    result = make_result()
    duplicate = result.items[1].model_copy(
        update={
            "chunk_id": "chunk-duplicate-location",
            "source": result.items[0].source,
            "path": result.items[0].path,
            "line_range": result.items[0].line_range,
        }
    )
    result = result.model_copy(update={"items": [result.items[0], duplicate]})

    evidence = map_retrieval_evidence(result, start_index=1)

    assert [item.evidence_id for item in evidence] == ["E1"]


def test_map_retrieval_evidence_prioritizes_business_source_without_rewriting_rank() -> (
    None
):
    evidence = map_retrieval_evidence(
        make_result(),
        start_index=1,
        max_total_chars=50,
        preferred_paths={"docs/upload.md"},
    )

    assert "path=docs/upload.md" in evidence[0].locator
    assert "rank=2" in evidence[0].locator


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"start_index": 0}, ValueError),
        ({"start_index": True}, TypeError),
        ({"start_index": 1, "max_total_chars": 0}, ValueError),
    ],
)
def test_map_retrieval_evidence_rejects_invalid_budget(
    kwargs: dict[str, object],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        map_retrieval_evidence(make_result(), **kwargs)
