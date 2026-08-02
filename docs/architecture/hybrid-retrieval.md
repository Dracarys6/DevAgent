# Hybrid Retrieval Architecture

## Responsibilities

DevAgent combines lexical and semantic candidates without coupling fusion to either
index implementation:

```text
query
  -> KeywordRetriever -> BM25 candidates
  -> VectorRetriever  -> vector candidates
  -> Reciprocal Rank Fusion
  -> deduplicated, traceable RetrievalResult
```

`HybridRetriever` depends on the minimal `Retriever` protocol. The standalone
`fuse_retrieval_results` function accepts two existing `RetrievalResult` objects so
Evaluation can reuse one BM25 lookup and one paid query embedding across BM25,
Vector, and Hybrid metrics.

## Reciprocal Rank Fusion

BM25 scores and cosine-derived vector scores have different scales and distributions.
Hybrid retrieval therefore uses rank contributions instead of adding raw scores:

```text
rrf_score = keyword_weight / (rrf_k + bm25_rank)
          + vector_weight / (rrf_k + vector_rank)
```

The default configuration is:

```text
candidate_k = 20
rrf_k = 60
keyword_weight = 1.0
vector_weight = 1.0
```

Each source retrieves `candidate_k` candidates before fusion. The final `top_k`
controls evidence payload size independently from recall breadth.

## Identity And Ordering

Candidates are deduplicated by `chunk_id`. When both sources return the same chunk,
their `document_id`, `source`, `path`, and `line_range` must agree. An identity
conflict raises `HybridRetrievalError` instead of binding one score to another
chunk's location.

Final ordering is deterministic:

```text
-rrf_score -> path -> line_range.start -> chunk_id
```

For shared candidates, the BM25 excerpt is retained because it is centered around a
matched query term. Vector provider metadata remains attached where available.

Every fused item records:

```text
retrieval_method=hybrid_rrf
candidate_sources=bm25,vector
bm25_rank / bm25_score
vector_rank / vector_score
rrf_score
```

## Failure And Privacy Boundaries

- Invalid query and `top_k` values become `HybridRetrievalError` before source calls.
- Controlled BM25 or Vector errors become a sanitized `HybridRetrievalError`.
- Source query mismatches and candidate identity conflicts are rejected.
- Persisted Evaluation summaries contain case IDs and aggregate metrics, not queries,
  excerpts, generated answers, credentials, endpoints, headers, or provider responses.

## Day60 Live Baseline

The frozen 36-case corpus was evaluated with equal-weight RRF over 21 chunks and
`text-embedding-v4`:

```text
Top-5 evidence hit rate: 100.0%
MRR@5: 98.3%
Empty result accuracy: 0.0%
Evidence location completeness: 100.0%
Candidate source traceability: 100.0%
Context reduction: 73.8%
Query p95: 195.79 ms
```

Hybrid restored the Vector MRR@5 from 93.3% to the BM25 baseline of 98.3% while
preserving Hit@5. Empty-result accuracy remained 0% because standard RRF merges a
candidate union and Vector search always returns nearest neighbors. Threshold or
source-agreement calibration requires a separate calibration set; it must not be fit
directly to the six frozen negative cases.

## Verification

```bash
.venv/bin/pytest tests/memory/test_hybrid_retriever.py \
  tests/eval/test_hybrid_baseline.py \
  tests/scripts/test_run_hybrid_baseline.py -q

.venv/bin/python scripts/run_hybrid_baseline.py
```
