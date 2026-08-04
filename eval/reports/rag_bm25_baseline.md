# RAG Evaluation Baseline

- Generated at: `2026-08-04T14:13:01.638883+00:00`
- Commit: `14f112a + working tree`
- Cases: 36
- Positive / negative: 30 / 6
- Corpus documents: 21

## Quality And Performance

| Metric | Result | Target |
| --- | ---: | ---: |
| Tool Hit Rate | 100.0% | 100% |
| Top-5 Evidence Hit Rate | 100.0% | >= 80% |
| Precision@5 | 20.0% | compare |
| Recall@5 | 100.0% | >= 80% |
| NDCG@5 | 98.8% | compare |
| MRR@5 | 98.3% | baseline |
| Answer Keyword Hit Rate | 100.0% | >= 80% |
| Empty Result Accuracy | 100.0% | 100% |
| Evidence Location Completeness | 100.0% | >= 90% |
| Context Reduction Rate | 77.8% | >= 40% |
| Retrieval p95 | 5.55 ms | < 800 ms |

## Context Efficiency

| Strategy | Average chars / positive case | Evidence availability |
| --- | ---: | ---: |
| Full-corpus oracle injection | 7959.0 | 100.0% oracle |
| BM25 Top-5 evidence injection | 1764.6 | 100.0% |

- Full context total: 238770
- Retrieved context total: 52938
- Maximum retrieved context for one case: 2817

## Business Slices

| Category | Cases | Evidence Hit | Average retrieved chars | Context reduction |
| --- | ---: | ---: | ---: | ---: |
| ci | 4 | 100.0% | 1927.8 | 75.8% |
| log | 4 | 100.0% | 1981.8 | 75.1% |
| diagnosis | 1 | 100.0% | 1933.0 | 75.7% |
| review | 1 | 100.0% | 2168.0 | 72.8% |

## Failure Analysis

- `tool_failure`: None
- `miss_at_5`: None
- `false_positive_non_empty`: None
- `incomplete_location`: None
- `answer_keyword_miss`: None

## Interpretation And Boundaries

This deterministic local baseline compares full-corpus oracle availability with BM25 Top-5 evidence injection.
Hit@5 measures whether any relevant path is retrieved; Precision@5 and Recall@5 measure evidence density and coverage; NDCG@5 uses graded relevance; MRR@5 measures how early the first relevant result appears.
Current fixtures are path-level judgments. Unlisted paths are treated as irrelevant, and legacy expected_paths migrate to relevance grade 3; chunk-level relevance still requires finer annotations.
The report measures retrieval evidence quality, context efficiency, and local tool latency; it does not measure live-LLM answer accuracy or provider network latency.
Negative cases are scored with Empty Result Accuracy and are excluded from Context Reduction Rate.
