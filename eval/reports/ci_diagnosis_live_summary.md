# Live CI Diagnosis Acceptance Summary

- Generated at: `2026-07-30`
- Provider: `openai-compatible-live`
- Model / API: `gpt-5.6-terra / Responses`
- Target: `7229c86`
- Workspace: `examples/sample_repo`
- Consecutive post-fix runs: `3`
- Consecutive post-fix pass rate: `100.0%`
- Average post-fix latency: `17.18 s`
- Post-fix p95 latency: `20.97 s`

## Acceptance Results

| Run | Phase | Result | Attempts | Latency | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| Run 1 | exploratory | PASS | 1 | 57.01 s | First standardized live report |
| Run 2 | pre-fix | FAIL | 2 | 146.31 s | Both attempts failed with `report_mismatch` |
| Run 3 | post-fix | PASS | 1 | 15.69 s | Consecutive acceptance 1/3 |
| Run 4 | post-fix | PASS | 1 | 20.97 s | Consecutive acceptance 2/3 |
| Run 5 | post-fix | PASS | 1 | 14.88 s | Consecutive acceptance 3/3 |

Every successful post-fix report:

- returned `diagnosed`;
- included the authoritative `ci_result` and code-only `git_diff` evidence;
- grounded all finding and recommendation references in `E1` / `E2`;
- contained at least one root-cause finding and one recommendation;
- mentioned both `build_upload_timeout` and `min_timeout_seconds`;
- passed Pydantic validation without retry.

## Failure-Driven Fix

Run 2 proved that asking the model to copy `report_id`, `target`, `scenario`, and
the complete evidence payload was unstable. Both model calls returned valid JSON,
but one or more copied authoritative fields differed from the service input.

The contract now separates ownership:

```text
LLM-owned analysis:
status, summary, findings, recommendations, missing_evidence

Service-owned authority:
report_id, scenario, target, original evidence
```

`DiagnosisService` validates the model-owned `DiagnosisReportDraft`, binds the
service-owned fields, and then validates the final `DiagnosisReport`. Unknown
evidence references are still rejected. This removes copy drift without weakening
evidence integrity.

## Evidence Boundary

The fixed case uses:

```text
examples/sample_ci/7229c86.json
examples/sample_repo at commit 7229c86
```

The Git evidence is restricted to Python source and test changes. README files,
diagnosis notes, and comment-only lines that directly reveal the fixture answer
are excluded, so the model must infer the root cause from executable code and the
failed assertion.

This acceptance demonstrates one fixed CI diagnosis case on the listed model and
provider. It does not establish universal diagnosis accuracy or production latency.
