# Log Diagnosis 真实验收汇总

- 验收日期：2026-07-31
- Provider：`openai-compatible-live`
- Model / API：`gpt-5.6-terra` / `responses`
- 固定目标：`task_001`
- 日志目录：`examples/sample_logs`
- 业务链路：`search_log -> LogDiagnosisInput -> DiagnosisReportDraft -> 服务端权威字段绑定 -> DiagnosisReport -> metrics`

## 验收结论

Log Diagnosis 已通过真实 API 手动调用和显式 live runner 两层验收。模型正确区分首个异常、后续连锁错误
和最终失败症状，并将日志支持的根因候选标为 `likely`，没有把缺少代码证据的推断升级为
`confirmed root_cause`。

| 指标 | 结果 |
| --- | ---: |
| Diagnosed | 100% |
| Log evidence coverage | 100% |
| Evidence 引用闭合 | 100% |
| 首个异常识别 | 100% |
| 连锁错误识别 | 100% |
| Confirmed root cause | 0 |
| 代码证据缺口记录 | 100% |
| Expected keyword hit rate | 100%（3/3） |
| 模型尝试次数 | 1 |
| 端到端延迟 | 34.19 秒 |

标准化报告见 `log_diagnosis_live.md/json`。

## 真实输出判断

- `UploadTimeoutError` 被识别为 `sequence_id=3` 的首个异常。
- `RetryExhaustedError` 被识别为超时后的连锁错误，而不是首个异常。
- `timeout_seconds=3` 与 `expected_seconds=12` 的不匹配被标为 `likely root_cause`。
- `missing_evidence` 明确要求读取代码或配置，并建议 `read_file`。
- Recommendation 引用 `E1`，包含检查配置、读取实现和重新运行任务的验证步骤。

## 验收边界

- 日志证据可以确认时间线和观测事实，不能单独确认 3 秒配置的代码来源。
- 本次只验证固定结构化日志 case，不代表任意日志格式或故障类型上的普遍准确率。
- 报告不保存 API key、token、secret 或本机绝对日志目录。
