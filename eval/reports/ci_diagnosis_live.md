# Live CI Diagnosis Evaluation

- Generated at: `2026-07-30T14:44:02.082703+00:00`
- DevAgent commit: `33243f6 + working tree`
- Provider: `openai-compatible-live`
- Model: `gpt-5.6-terra`
- API mode: `responses`
- Target: `7229c86`
- Workspace: `examples/sample_repo`
- Latency: 57009.11 ms
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

- Report ID: `861e58f6-f8b6-4dda-813a-d9791f668787`
- Status: `diagnosed`
- Evidence: `E1`, `E2`

### Summary

CI 中的 unit-tests 失败于 tests/test_uploader.py::test_large_upload_uses_dynamic_timeout：在 size_mb=80、bandwidth_mb_s=10 时，build_upload_timeout 返回 3，而测试要求结果至少为 12。提交中的实现显示该方法当前始终返回 min_timeout_seconds，未使用 size_mb、bandwidth_mb_s 或 safety_factor；这与失败测试所验证的动态超时行为不一致。

### Findings

- `symptom` / `confirmed` [E1]: unit-tests 失败，失败测试为 tests/test_uploader.py::test_large_upload_uses_dynamic_timeout；断言显示 timeout 的实际值为 3，但要求至少为 12。
- `root_cause` / `likely` [E1, E2]: build_upload_timeout 当前直接返回 self.config.min_timeout_seconds。对于默认配置和失败测试输入，这会返回 3；该实现未使用 size_mb、bandwidth_mb_s 或 safety_factor，因此很可能导致动态超时测试失败。
- `related_change` / `confirmed` [E2]: 本次提交新增了 UploadConfig、estimate_upload_timeout 和 UploadManager；其中 estimate_upload_timeout 会根据 size_mb / bandwidth_mb_s 计算值，但 build_upload_timeout 未调用该函数。

### Recommendations

- [E1, E2] 修改 build_upload_timeout，使其依据 size_mb 和 bandwidth_mb_s 计算上传耗时，并结合 safety_factor 与 min_timeout_seconds 返回满足最小超时约束的结果。 Reason: 失败测试要求大文件上传使用动态超时，而当前实现始终返回 min_timeout_seconds。现有 estimate_upload_timeout 已提供基于输入参数的耗时计算，UploadConfig 也定义了 safety_factor。

## Acceptance Boundary

This report was produced by a live LLM provider through DiagnosisService, the real CI fixture reader, and a code-only Git diff.
The fixed case checks structured output, evidence coverage, grounded references, root-cause facts, recommendations, retries, and latency.
It validates this listed case and provider run; it does not claim universal diagnosis accuracy.
