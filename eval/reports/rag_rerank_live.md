# RAG Rerank Baseline

- Generated at: `2026-08-03T02:26:18.482034+00:00`
- Commit: `161069e + working tree`
- Embedding: `openai-compatible:text-embedding-v4` / `text-embedding-v4`
- Reranker: `llm:gpt-5.6-terra`
- Cases / candidates: 8 / Top-10

## Quality Comparison

| Metric | Hybrid before | Rerank after | Target |
| --- | ---: | ---: | ---: |
| Hit@5 | 100.0% | 100.0% | >= before |
| MRR@5 | 91.7% | 100.0% | >= before |
| Empty accuracy | 0.0% | 0.0% | >= before |
| Location completeness | 100.0% | 100.0% | 100% |
| Query p95 | 335.78 ms | 17428.55 ms | observe |

## Reliability And Cost

- Reranker requests / repair retries: 8 / 0
- Scored candidates: 80
- Reranker input / output characters: 47359 / 4597
- Transport timeout / SDK retries: 45.0 s / 0
- Fallback cases: 0
- Rerank metadata completeness: 100.0%
- Embedding document / query calls: 3 / 8
- Embedding input tokens: 1989
- Index build latency: 1167.28 ms

## Case Observations

| Case | Before rank | After rank | Status | Error code | Attempts | Rerank latency |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| `github-inline-fallback` | 2 | 1 | success | - | 1 | 7881.52 ms |
| `event-bus-publish` | 1 | 1 | success | - | 1 | 9496.31 ms |
| `ci-upload-timeout` | 1 | 1 | success | - | 1 | 6659.24 ms |
| `log-upload-timeout` | 1 | 1 | success | - | 1 | 7535.78 ms |
| `diagnosis-evidence-binding` | 1 | 1 | success | - | 1 | 17148.25 ms |
| `review-diff-location` | 1 | 1 | success | - | 1 | 6341.75 ms |
| `negative-payment-billing` | - | - | success | - | 1 | 6311.08 ms |
| `negative-kubernetes-deployment` | - | - | success | - | 1 | 7575.26 ms |

## Interpretation

The reranker scores only bounded Hybrid candidates and binds scores back by chunk_id.
Controlled reranker failures preserve the Hybrid order and expose fallback status, error code, and latency in evidence metadata.
The persisted summary excludes queries, excerpts, provider responses, credentials, and private endpoint details.
