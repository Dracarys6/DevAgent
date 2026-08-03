# Live Business RAG Evaluation

- Generated at: `2026-08-03T03:36:40.489768+00:00`
- DevAgent revision: `22c6d36 + working tree`
- LLM: `openai-compatible-live:gpt-5.6-terra`
- Embedding model: `text-embedding-v4`
- Retrieval strategy: `hybrid_rrf_cached_snapshot`

## Workflows

| Workflow | Passed | Latency ms | Attempts | Knowledge | Referenced |
| --- | ---: | ---: | ---: | ---: | ---: |
| ci_failure | True | 12726.59 | 1 | 2 | True |
| log_failure | True | 19057.76 | 1 | 2 | True |
| code_review | True | 13991.47 | 1 | 2 | True |

Overall passed: **True**

# Business RAG Evaluation

- Generated at: `2026-08-03T03:36:40.489768+00:00`
- DevAgent revision: `22c6d36 + working tree`
- Baseline: domain evidence + all indexable workspace document text
- Optimized: actual bounded domain and retrieved Evidence excerpts

## Metrics

| Metric | Result |
| --- | ---: |
| Cases | 3 |
| Retrieval Evidence | 6 |
| Average Context Reduction | 45.2% |
| Retrieval Locator Completeness | 100.0% |
| Domain Flow Availability | 100.0% |
| Duplicate Locations | 0 |
| Fallback Cases | 0 |
| Passed | True |

## Cases

| Case | Scenario | Baseline | Optimized | Reduction | Retrieved |
| --- | --- | ---: | ---: | ---: | ---: |
| ci-upload-timeout | ci_failure | 5998 | 3947 | 34.2% | 2 |
| log-upload-timeout | log_failure | 4518 | 2467 | 45.4% | 2 |
| review-upload-timeout | code_review | 6789 | 2982 | 56.1% | 2 |

This deterministic report measures evidence context and metadata. Generated-answer quality requires the separate live-provider business run.
