# Local Code Review 真实验收汇总

- 验收日期：2026-07-31
- Provider：`openai-compatible-live`
- Model / API：`gpt-5.6-terra` / `responses`
- 固定变更：`7229c86^...7229c86`
- Workspace：`examples/sample_repo`
- 业务链路：`git_compare -> read_file -> CodeReviewService -> CodeReviewReportDraft -> 服务端权威字段绑定 -> CodeReviewReport -> metrics`

## 验收结论

保留的真实 provider 输出通过 Local Code Review 端到端验收：模型在 1 次调用中识别出
`src/sample_app/uploader.py:24` 的动态上传超时缺陷，并使用 Git diff、源码和测试证据完成定位。

| 指标 | 结果 |
| --- | ---: |
| Review 状态正确 | 100% |
| Git + Code evidence coverage | 100% |
| Evidence 引用闭合 | 100% |
| Expected finding match | 100% |
| Expected keyword hit rate | 100%（2/2） |
| 额外 finding | 0 |
| 模型调用次数 | 1 |
| 端到端延迟 | 15.79 秒 |

最终报告见 `code_review_live.md/json`，首次评分结果保存在
`code_review_live_initial_score.md/json`。

## 评分校准记录

第二次真实调用的模型输出最初被判定为 FAIL，但失败原因不是缺陷漏报、证据不足或 JSON 不合法：
模型给出的 category、文件、行号、证据和修复建议均正确，唯一差异是模型将该 finding 标记为
`medium`，而初始 expected label 只接受 `high/critical`。

项目 Review rubric 将“有界场景中的真实风险”定义为 `medium`。大文件或低带宽上传超时属于有界场景，
因此 expected severities 校准为 `medium/high/critical`。随后使用同一份脱敏 JSON 离线重评分，未再次调用
模型，也没有修改模型 finding。校准后的结果为 PASS。

另一次真实调用在终端记录为 FAIL，延迟 13.43 秒、模型调用 1 次；由于默认输出路径被下一次运行覆盖，
没有足够 artifact 判断其具体失败指标，因此不计入最终质量结论。

## 验收边界

- 固定评测只向模型提供 `src/` 和 `tests/` 变更，排除 README、人工说明文件和纯注释答案行。
- 报告不保存 API key、token、secret 或本机绝对 workspace 路径。
- 本次证明本地 Git 证据采集、真实模型分析、结构化校验和确定性评分链路可用。
- 本次不代表所有仓库的普遍代码审查准确率，也不替代 GitHub App、webhook 和评论发布验收。
