# RAG Evaluation Baseline

- Generated at: `2026-07-30T13:16:54.712335+00:00`
- Commit: `d84e3a4 + working tree`
- Cases: 20
- Positive / negative: 18 / 2
- Corpus documents: 17

## Quality And Performance

| Metric | Result | Target |
| --- | ---: | ---: |
| Tool Hit Rate | 100.0% | 100% |
| Top-5 Evidence Hit Rate | 100.0% | >= 80% |
| Answer Keyword Hit Rate | 100.0% | >= 80% |
| Empty Result Accuracy | 100.0% | 100% |
| Evidence Location Completeness | 100.0% | >= 90% |
| Context Reduction Rate | 78.9% | >= 40% |
| Retrieval p95 | 7.19 ms | < 800 ms |

## Context Efficiency

| Strategy | Average chars / positive case | Evidence availability |
| --- | ---: | ---: |
| Full-corpus oracle injection | 4923.0 | 100.0% oracle |
| BM25 Top-5 evidence injection | 1040.7 | 100.0% |

- Full context total: 88614
- Retrieved context total: 18732
- Maximum retrieved context for one case: 1545

## Business Slices

| Category | Cases | Evidence Hit | Average retrieved chars | Context reduction |
| --- | ---: | ---: | ---: | ---: |
| ci | 1 | 100.0% | 378.0 | 92.3% |
| log | 1 | 100.0% | 1383.0 | 71.9% |
| diagnosis | 1 | 100.0% | 1216.0 | 75.3% |
| review | 1 | 100.0% | 1451.0 | 70.5% |

## Failure Analysis

- Failed tool cases: None
- Missed evidence cases: None
- Missing answer keywords: None
- Incorrect non-empty negative cases: None

## Interpretation And Boundaries

This deterministic local baseline compares full-corpus oracle availability with BM25 Top-5 evidence injection.
It measures retrieval evidence quality, context efficiency, and local tool latency; it does not measure live-LLM answer accuracy or provider network latency.
Negative cases are scored with Empty Result Accuracy and are excluded from Context Reduction Rate.
