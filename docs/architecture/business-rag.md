# Business RAG Evidence Pipeline

## Purpose

DevAgent combines authoritative domain evidence with bounded workspace retrieval. RAG
does not replace CI, log, or Git tools:

```text
get_ci_result / search_log / git_compare
  -> validated identity, status, timeline, and patch facts
  -> derive a bounded retrieval query
  -> WorkspaceKnowledgeService
  -> BM25 or injected Hybrid retriever
  -> bounded knowledge Evidence
  -> diagnosis or review prompt
```

Domain tools remain authoritative because similarity search cannot guarantee a commit
ID, task ID, event ordering, merge base, or complete test status. Retrieval supplies
related code, configuration, tests, and documentation that may not be present in the
domain result.

## Dependency Direction

`WorkspaceKnowledgeService` owns safe document loading and chunk creation. A
`KnowledgeRetrieverFactory` chooses the retrieval implementation outside the business
service. The default remains BM25 for compatibility and predictable empty-result
behavior.

Production or live evaluation can inject `CachedHybridRetrieverFactory`. It builds
BM25 and vector indexes for a chunk snapshot, fuses candidates with RRF, and reuses the
index while chunk IDs and content hashes remain unchanged. A changed snapshot rebuilds
the index. Query results are not cached.

The general Agent tool does not switch globally to Hybrid yet. The Day60 fixed set
showed Hybrid Hit@5 of 100% but empty-result accuracy of 0%, so uncalibrated Hybrid is
appropriate for domain-anchored business queries, not as the universal default for
open-ended Agent retrieval.

## Evidence Contract

Retrieved snippets are mapped to `EvidenceKind.KNOWLEDGE` with server-bound fields:

```text
source
path
line range
chunk ID
original retrieval rank
bounded excerpt
retrieval method, score, latency, and fallback metadata
```

The mapping removes duplicate `source + path + line range` locations. CI and log
retrieval use a total retrieval excerpt budget of 900 characters. Log assembly gives
the first anomaly's source path priority without rewriting the original retrieval
rank. Review uses a 3,000-character Git diff budget and a 900-character retrieval
budget.

## Degradation

Embedding, Hybrid, or Rerank failures must not discard authoritative evidence:

```text
retrieval failure
  -> retain CI result, structured log, or Git diff
  -> append MissingEvidence(suggested_tool=knowledge_retrieve)
  -> continue diagnosis or review
```

Review additionally falls back to bounded direct file reads. Error details from an
embedding provider are not copied into user-facing missing-evidence reasons.

## Evaluation

The deterministic business metric compares:

```text
baseline = authoritative domain evidence + full indexable workspace text
optimized = actual bounded domain and retrieval Evidence excerpts
```

Review uses its previous Git-diff-plus-file-read collector as the baseline. Acceptance
requires:

```text
average context reduction >= 40%
retrieval locator completeness = 100%
domain flow availability = 100%
duplicate retrieval locations = 0
```

`scripts/run_live_business_rag_eval.py` is separately protected by both
`DEVAGENT_ENABLE_LIVE_EVAL=1` and
`DEVAGENT_ENABLE_LIVE_EMBEDDING_EVAL=1`. It runs CI diagnosis, log diagnosis, and local
code review through real providers, records latency and retries, verifies grounded
references, and writes a sanitized summary without API keys, base URLs, prompts, or
repository excerpts.
