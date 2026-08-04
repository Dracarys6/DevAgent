# RAG Vector Baseline

- Generated at: `2026-08-04T14:13:19.963754+00:00`
- Commit: `14f112a + working tree`
- Provider: `openai-compatible:text-embedding-v4`
- Model: `text-embedding-v4`
- Cases: 36
- Positive / negative: 30 / 6

## Index And Cost

- Documents / chunks: 21 / 21
- Vector dimensions: 1024
- Document embedding API calls: 3
- Query embedding API calls: 36
- Provider-reported input tokens: 2285
- Index build latency: 1365.06 ms

## Retrieval Comparison

| Metric | Vector | BM25 | Target |
| --- | ---: | ---: | ---: |
| Top-5 Evidence Hit Rate | 100.0% | 100.0% | >= 80% |
| Precision@5 | 20.0% | 20.0% | compare |
| Recall@5 | 100.0% | 100.0% | >= 80% |
| NDCG@5 | 95.1% | 98.8% | compare |
| MRR@5 | 93.3% | 98.3% | observe |
| Empty Result Accuracy | 0.0% | 100.0% | observe |
| Evidence Location Completeness | 100.0% | 100.0% | 100% |
| Context Reduction Rate | 75.1% | 77.8% | >= 40% |
| Query p50 | 141.08 ms | 4.91 ms | observe |
| Query p95 | 186.23 ms | 5.79 ms | observe |

## Failure Analysis

- Vector tool failures: None
- Vector miss@5: None
- Vector false-positive non-empty: `negative-payment-billing`, `negative-kubernetes-deployment`, `negative-graphql-federation`, `negative-terraform-aurora`, `negative-swiftui-keychain`, `negative-kafka-rebalance`
- BM25 miss@5: None

## Interpretation

Vector query latency includes the online embedding request and exact cosine scan.
The in-memory exact index isolates embedding quality from ANN approximation and vector database operations.
Nearest-neighbor search always has a closest result, so negative-case failures are expected before threshold calibration.
Provider credentials, base URL, headers, and raw responses are intentionally excluded.
