# RAG Reranking

## Purpose

Reranking improves the order of a bounded retrieval candidate set without replacing recall. DevAgent uses this pipeline:

```text
query
  -> BM25 + Vector
  -> Hybrid RRF Top-N recall
  -> Reranker score by chunk_id
  -> stable Top-K evidence
```

Hybrid RRF is responsible for recall diversity. The reranker is responsible for finer query-to-evidence relevance. Keeping these stages separate allows either implementation to be tested, replaced, or disabled independently.

## Contracts

`Reranker.score()` receives the query and immutable evidence candidates, then returns one `RerankScore` for every input `chunk_id`. The retrieval layer validates that:

- the response count equals the candidate count;
- every `chunk_id` is unique and exactly matches the input set;
- every score is finite and in `[0, 1]`;
- response array order is never used to bind scores to evidence.

The final stable ordering is:

```text
-rerank_score
recall_rank
path
line_range.start
chunk_id
```

The original Hybrid score and rank remain in `recall_score` and `recall_rank`. This preserves enough information to explain ranking changes.

## Failure Boundary

Provider failures, invalid JSON, schema mismatches, and invalid score sets become controlled `RerankerError` values. With fallback enabled, retrieval preserves the Hybrid order and records:

```text
rerank_status=fallback
rerank_error_code=<sanitized code>
reranker=<provider/model name>
rerank_ms=<elapsed milliseconds>
```

Only controlled reranker failures trigger fallback. Programming errors such as `TypeError` from an implementation bug are not swallowed, because silently treating defects as provider instability would make debugging and monitoring misleading.

Fallback improves availability, but it does not prove reranking worked. Live acceptance therefore fails when any selected case falls back, while the user-facing retrieval path can still return usable Hybrid evidence.

## LLM Adapter

`LLMReranker` uses the project-wide `LLMClient`; provider SDK details do not enter the retrieval core. It sends at most a configured Top-N candidate set and truncates each excerpt before the request.

The model returns a JSON object containing `chunk_id` and relevance score pairs. Invalid structured output receives one bounded repair attempt by default. Transport errors are not automatically repeated inside the adapter because SDK-level retries may already have occurred and blind retries can multiply latency and cost.

The live runner sets an explicit 45-second transport timeout and disables SDK retries. Schema repair remains bounded by `LLMReranker.max_attempts`, while network retry policy stays in the provider client. This separation prevents one logical rerank attempt from hiding several long SDK requests.

The adapter never includes rejected provider output in public exceptions, fallback metadata, or persisted reports.

## Evaluation

The deterministic layer verifies score binding, stable ordering, malformed output repair, fallback behavior, and report sanitization. The explicit live runner exercises real embeddings and a real LLM:

```bash
.venv/bin/python scripts/run_live_rerank_eval.py
```

It requires both `DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL=1` and `DEVAGENT_ENABLE_LIVE_EVAL=1`. The report compares the same Hybrid candidates before and after reranking and records:

- Hit@5 and MRR@5;
- per-case before/after relevant rank;
- model request and repair counts;
- fallback count and metadata completeness;
- retrieval and reranking latency;
- transport timeout, SDK retries, scored candidates, and input/output character counts;
- embedding API calls and input tokens.

Persisted summaries exclude raw queries, evidence excerpts, provider responses, credentials, and private endpoint details.

## Interview Notes

**Why not let the LLM search the full corpus?**

Recall systems are cheaper and better suited to broad candidate generation. Restricting the LLM to Top-N candidates bounds token cost and latency while retaining Hybrid recall diversity.

**Why bind by `chunk_id` instead of response position?**

Model output order is untrusted. Positional binding can silently assign one candidate's score to another; identity binding makes the contract explicit and verifiable.

**Why degrade instead of failing the retrieval request?**

Reranking is an enhancement after a usable recall result already exists. Returning the Hybrid order maintains availability, while explicit fallback telemetry prevents the degradation from becoming invisible.

**Why not catch every exception?**

Broad catches would hide code defects as expected provider failures. The boundary catches only `RerankerError`, which represents failures the adapter has deliberately classified and sanitized.
