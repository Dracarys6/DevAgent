# Vector Retrieval Architecture

## Responsibilities

DevAgent separates external text embedding from local evidence retrieval:

```text
Chunk.content
  -> EmbeddingProvider
  -> validated immutable vectors
  -> VectorRetriever cosine ranking
  -> local Chunk metadata binding
  -> EvidenceSnippet / RetrievalResult
```

`EmbeddingProvider` owns only text-to-vector conversion. It does not receive `Chunk`
objects or produce evidence models. `VectorRetriever` keeps `source`, `path`,
`line_range`, `document_id`, and `chunk_id` authoritative inside DevAgent and binds
them after ranking.

This boundary supports fixed-vector tests, provider replacement, and future index
implementations without changing Agent, Tool, or Evaluation result contracts.

## Provider Contract

An embedding provider exposes:

```python
provider_name: str
embed_documents(texts: Sequence[str]) -> list[EmbeddingVector]
embed_query(text: str) -> EmbeddingVector
```

Document and query methods remain separate because retrieval models may use different
prefixes or encoding paths. Document calls are batch-oriented; query calls are
latency-sensitive.

`OpenAIEmbeddingProvider` adapts the OpenAI-compatible `embeddings.create` API. It
splits document inputs into configured batches, validates that response indexes are
unique and cover every batch position, restores input order, and omits the optional
`dimensions` request field unless it is explicitly configured. The API base URL must
be the provider root such as `/v1`; the SDK appends `/embeddings` itself.

Provider output is validated before indexing or search:

```text
non-empty numeric vector
finite values only
non-zero norm
one vector per document
consistent document dimensions
query dimension equal to index dimension
```

Vectors are copied to immutable tuples and normalized once. A provider adapter must
convert network, authentication, rate-limit, and response errors into
`EmbeddingProviderError` without including credentials or raw sensitive responses.

## Retriever Contract

`VectorRetriever` builds an in-memory index from a stable Chunk snapshot. Search uses
cosine similarity and returns the existing `RetrievalResult` model.

Raw cosine similarity is in `[-1, 1]`. `EvidenceSnippet.score` requires a non-negative
value, so vector results use:

```text
score = (cosine_similarity + 1) / 2
```

The raw cosine value remains available as string metadata. This mapping does not make
BM25 and vector scores directly additive; hybrid retrieval must use an explicit fusion
strategy.

Equal similarities use a stable tie-break:

```text
path -> line_range.start -> chunk_id
```

An empty corpus returns an empty result without calling the provider. Invalid vectors,
dimension drift, duplicate chunk IDs, invalid query arguments, and controlled provider
failures become `VectorRetrievalError`. Unexpected programming errors are not caught as
provider failures.

## Security And Operations

- Send only required text to an external embedding provider.
- Keep repository paths and evidence identity local.
- Record the provider name in result metadata for traceability.
- Treat provider or model changes as an index compatibility event.
- Rebuild document vectors when the embedding space changes, even if dimensions match.
- Calibrate similarity thresholds with fixed positive and negative cases instead of an
  arbitrary production constant.
- Configure provider batch limits explicitly. The Day59 live provider accepts at most
  10 inputs per request, while other OpenAI-compatible providers may allow different
  limits.

## Day59 Live Baseline

The frozen 36-case corpus was evaluated with `text-embedding-v4` using 21 documents
and 21 chunks. The exact in-memory vector index produced:

```text
Top-5 evidence hit rate: 100.0%
MRR@5: 93.3%
Empty result accuracy: 0.0%
Evidence location completeness: 100.0%
Context reduction: 75.1%
Query p95: 317.61 ms
```

The zero empty-result accuracy is expected for an unthresholded nearest-neighbor
baseline: every query has a closest vector even when no evidence is relevant. It is a
measured calibration problem, not evidence that a vector database is required.

The vector candidates are combined with BM25 through the RRF design documented in
[`hybrid-retrieval.md`](hybrid-retrieval.md). Hybrid fusion reuses the same
`RetrievalResult` and evidence identity contracts.

## Verification

Deterministic fixtures validate exact cosine ordering, score mapping, stable ties,
metadata preservation, malformed vectors, empty corpora, and provider failures:

```bash
.venv/bin/pytest tests/memory/test_embeddings.py \
  tests/memory/test_vector_retriever.py \
  tests/memory/test_openai_embeddings.py -q

DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL=1 \
  .venv/bin/python scripts/run_vector_baseline.py
```
