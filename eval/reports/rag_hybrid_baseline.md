# RAG Hybrid Baseline

- Generated at: `2026-08-02T14:42:35.347122+00:00`
- Commit: `96d60ef + working tree`
- Provider / model: `openai-compatible:text-embedding-v4` / `text-embedding-v4`
- Cases: 36
- Documents / chunks: 21 / 21

## Fusion Configuration

- Strategy: Reciprocal Rank Fusion
- Candidate K / RRF K: 20 / 60
- BM25 / Vector weight: 1 / 1
- Candidate source traceability: 100.0%

## Quality And Performance

| Metric | Hybrid RRF | BM25 | Vector | Target |
| --- | ---: | ---: | ---: | ---: |
| Top-5 Evidence Hit Rate | 100.0% | 100.0% | 100.0% | >= BM25 |
| MRR@5 | 98.3% | 98.3% | 93.3% | observe |
| Empty Result Accuracy | 0.0% | 100.0% | 0.0% | observe |
| Evidence Location Completeness | 100.0% | 100.0% | 100.0% | 100% |
| Context Reduction | 73.8% | 77.8% | 75.1% | >= 40% |
| Query p50 | 149.70 ms | 0.09 ms | 149.54 ms | observe |
| Query p95 | 195.79 ms | 0.25 ms | 195.67 ms | < 800 ms |

## Provider And Index Cost

- Vector dimensions: 1024
- Document embedding calls: 3
- Query embedding calls: 36
- Provider-reported input tokens: 2285
- Index build latency: 1520.87 ms

## Failure Analysis

- Hybrid tool failures: None
- Hybrid miss@5: None
- Hybrid false-positive non-empty: `negative-payment-billing`, `negative-kubernetes-deployment`, `negative-graphql-federation`, `negative-terraform-aurora`, `negative-swiftui-keychain`, `negative-kafka-rebalance`

## Interpretation

Hybrid RRF is an uncalibrated candidate union baseline; it does not prove absolute relevance.
Each query performs one BM25 lookup and one online query embedding, then reuses both results for all three strategy metrics.
Raw queries, excerpts, answers, credentials, base URLs, headers, and provider responses are excluded from the persisted summary.
