# Live CI Diagnosis Evaluation

- Generated at: `2026-07-30T14:51:12.500091+00:00`
- DevAgent commit: `33243f6 + working tree`
- Provider: `openai-compatible-live`
- Model: `gpt-5.6-terra`
- API mode: `responses`
- Target: `7229c86`
- Workspace: `examples/sample_repo`
- Latency: 15688.04 ms
- Attempts: 1
- Attempt errors: None

## Acceptance Metrics

| Metric | Result |
| --- | ---: |
| Diagnosed | True |
| CI + Git Evidence Covered | True |
| Evidence References Grounded | True |
| Root Cause Findings | 1 |
| Recommendations | 1 |
| Expected Keyword Hit Rate | 100.0% (2/2) |
| End-to-End Passed | True |

## Diagnosis Result

- Report ID: `64da38a0-d2e6-442f-a941-ae563dd62722`
- Status: `diagnosed`
- Evidence: `E1`, `E2`

### Summary

unit-tests 因 tests/test_uploader.py::test_large_upload_uses_dynamic_timeout 失败：对 size_mb=80、bandwidth_mb_s=10 的调用返回 3，而测试要求结果至少为 12。现有 build_upload_timeout 无论输入均返回 config.min_timeout_seconds，未使用 estimate_upload_timeout 或 safety_factor。

### Findings

- `symptom` / `confirmed` [E1]: tests/test_uploader.py::test_large_upload_uses_dynamic_timeout 失败，断言显示 build_upload_timeout(size_mb=80, bandwidth_mb_s=10) 的结果为 3，但测试要求结果至少为 12。
- `root_cause` / `confirmed` [E2]: UploadManager.build_upload_timeout 当前直接返回 self.config.min_timeout_seconds；因此对大上传参数也返回默认值 3，未根据 size_mb、bandwidth_mb_s、estimate_upload_timeout 或 safety_factor 计算动态超时。
- `related_change` / `confirmed` [E2]: 同一提交新增了 estimate_upload_timeout 和 UploadConfig.safety_factor，但 build_upload_timeout 未引用它们。

### Recommendations

- [E1, E2] 修改 UploadManager.build_upload_timeout，使其基于 estimate_upload_timeout(size_mb, bandwidth_mb_s) 和 self.config.safety_factor 计算动态超时，并确保返回值不低于 self.config.min_timeout_seconds。 Reason: 当前实现固定返回最小超时，导致大上传场景返回 3；测试对 80/10 的场景要求至少为 12，而 estimate_upload_timeout 的结果为 8，结合 safety_factor=1.5 可得到 12。

## Acceptance Boundary

This report was produced by a live LLM provider through DiagnosisService, the real CI fixture reader, and a code-only Git diff.
The fixed case checks structured output, evidence coverage, grounded references, root-cause facts, recommendations, retries, and latency.
It validates this listed case and provider run; it does not claim universal diagnosis accuracy.
