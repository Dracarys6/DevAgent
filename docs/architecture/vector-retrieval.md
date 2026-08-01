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

## Verification

Deterministic fixtures validate exact cosine ordering, score mapping, stable ties,
metadata preservation, malformed vectors, empty corpora, and provider failures:

```bash
.venv/bin/pytest tests/memory/test_embeddings.py \
  tests/memory/test_vector_retriever.py -q
```
