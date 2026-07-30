# Live CI Diagnosis Evaluation

- Generated at: `2026-07-30T14:47:51.241472+00:00`
- DevAgent commit: `33243f6 + working tree`
- Provider: `openai-compatible-live`
- Model: `gpt-5.6-terra`
- API mode: `responses`
- Target: `7229c86`
- Workspace: `examples/sample_repo`
- Latency: 146308.91 ms
- Attempts: 2
- Attempt errors: `report_mismatch`, `report_mismatch`

## Acceptance Metrics

| Metric | Result |
| --- | ---: |
| Diagnosed | False |
| CI + Git Evidence Covered | False |
| Evidence References Grounded | False |
| Root Cause Findings | 0 |
| Recommendations | 0 |
| Expected Keyword Hit Rate | 0.0% (0/2) |
| End-to-End Passed | False |

## Acceptance Boundary

This report was produced by a live LLM provider through DiagnosisService, the real CI fixture reader, and a code-only Git diff.
The fixed case checks structured output, evidence coverage, grounded references, root-cause facts, recommendations, retries, and latency.
It validates this listed case and provider run; it does not claim universal diagnosis accuracy.
