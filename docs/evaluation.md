# DevAgent Evaluation

## 目标

DevAgent 的 Evaluation 用固定输入、固定标注和确定性指标回答三个问题：

```text
质量：Agent 是否找到正确证据并输出可行动结果
效率：是否减少无关上下文和人工查找步骤
稳定性：工具、报告和指标是否可以重复运行并定位失败 case
```

测试与 Evaluation 的职责不同：

```text
pytest
  验证模型、边界、错误转换和执行流程是否符合代码契约

Evaluation
  验证一组研发任务上的召回、误报、证据、上下文和延迟表现
```

测试通过是 Evaluation 可信运行的前提，不是项目效果指标本身。

## 统一数据分层

RAG Evaluation 使用三层结构：

```text
RAGEvalCase
  人工标注的 query、expected path、expected keywords 和空结果预期

RAGEvalPrediction
  一次真实工具执行产生的 RetrievalResult、answer context、错误和延迟

RAGEvalMetrics / RAGContextMetrics
  对整批 Case 与 Prediction 聚合的质量、上下文和性能指标
```

分层后：

```text
Retriever 改动 -> 重新生成 Prediction
指标公式改动 -> 使用旧 Prediction 重新评分
接入真实 LLM -> 替换 answer_text 的生成方式
失败分析 -> 区分 fixture、工具、检索、上下文和评分问题
```

Code Review Evaluation 采用相同思想，但 Case 中保存固定 review report，指标关注风险召回率、可行动准确率、
clean-case 误报率、evidence 引用和 diff 定位。

## RAG Baseline

### 数据集

固定路径：

```text
eval/cases/rag/baseline_cases.json
eval/cases/rag/workspace/
```

当前规模：

```text
20 cases
18 positive cases
2 negative cases
17 corpus documents
4,923 corpus characters
```

覆盖：

```text
代码与工具
事件、任务和 Trace
权限与命令安全
SSE / WebSocket
CI、日志和 DiagnosisReport
Code Review finding
Memory、Chunk 和 BM25
中文安全文档
无证据负样本
```

### 对比口径

Full-corpus oracle injection：

```text
每个正样本注入所有可索引文档
预期证据一定可用
没有相关性排序和上下文控制
```

BM25 Top-5 evidence injection：

```text
通过真实 KnowledgeRetrieveTool 执行
只注入 RetrievalResult.items 的 excerpt
返回 rank、score、source、path 和 line_range
可能漏召回，因此必须同时检查质量指标
```

Context Reduction 只统计正样本：

```text
1 - 所有正样本 retrieved evidence chars
    / 所有正样本 full corpus chars
```

负样本正确结果天然是空 evidence。如果把它们加入平均，会人为抬高压缩率；负样本由 Empty Result
Accuracy 单独评估。

### 第 8 周 BM25 结果

报告：

```text
eval/reports/rag_baseline.md
```

固定结果：

| Metric | Result | Target |
| --- | ---: | ---: |
| Tool Hit Rate | 100.0% | 100% |
| Top-5 Evidence Hit Rate | 100.0% | >= 80% |
| Answer Keyword Hit Rate | 100.0% | >= 80% |
| Empty Result Accuracy | 100.0% | 100% |
| Evidence Location Completeness | 100.0% | >= 90% |
| Context Reduction Rate | 78.9% | >= 40% |
| Local Retrieval p95 | 7.19 ms | < 800 ms |

上下文对比：

```text
Full-corpus oracle average = 4,923.0 chars / positive case
BM25 Top-5 average         = 1,040.7 chars / positive case
Context Reduction          = 78.9%
```

业务切片：

| Category | Cases | Evidence Hit | Context Reduction |
| --- | ---: | ---: | ---: |
| CI | 1 | 100.0% | 92.3% |
| Log | 1 | 100.0% | 71.9% |
| Diagnosis | 1 | 100.0% | 75.3% |
| Review | 1 | 100.0% | 70.5% |

这些切片证明固定业务问题能找回预期证据，并显著减少 evidence 正文。它们不等于完整 DiagnosisService
或 CodeReviewService 的最终任务成功率。

### 离线 Answer Keyword 的边界

第 8 周确定性 BM25 baseline 不调用在线模型：

```text
answer_text = 按 rank 拼接 EvidenceSnippet.excerpt
```

因此 Answer Keyword Hit Rate 表示：

```text
回答所需关键词是否已经存在于提供给 Agent 的 evidence context
```

它不表示真实 LLM 一定正确理解并使用这些证据。真实 provider 的最终回答质量必须通过独立 smoke 或
端到端 Evaluation 记录。

## Live RAG Agent Evaluation

离线检索指标通过后，使用真实 provider 运行：

```text
真实问题
  -> AgentRuntime
  -> gpt-5.6-terra / Responses
  -> 模型自主调用 knowledge_retrieve
  -> ToolExecutor / KnowledgeRetrieveTool / BM25
  -> RetrievalResult
  -> 模型生成 RAGAgentAnswer JSON
  -> Pydantic 校验与确定性评分
```

报告：

```text
eval/reports/rag_live_provider.md
eval/reports/rag_live_provider.json
```

8 条代表性 case 覆盖 EventBus、CI、日志、Diagnosis、Review、BM25 和两个负样本。实测：

| Metric | Result |
| --- | ---: |
| Valid Answer Rate | 100.0% |
| knowledge_retrieve Tool Call Rate | 100.0% |
| Tool Success Rate | 100.0% |
| Evidence Hit Rate | 100.0% |
| Answer Keyword Hit Rate | 91.7% |
| Expected Path Citation Rate | 100.0% |
| Grounded Citation Rate | 100.0% |
| Abstention Accuracy | 100.0% |
| Strict End-to-End Success Rate | 87.5% |
| End-to-End p95 | 24.55 s |

唯一严格失败 case 是 `log-upload-timeout`：模型正确说明了“上传在 3 秒后超时”，也引用了
`logs/task.log`，但没有逐字输出标注字段 `elapsed_seconds`，因此精确字符串评分将它判为失败。
报告保留 `missing_answer_keyword=elapsed_seconds`，不修改模型输出或临时放宽 case 来制造 100%。

这个结果同时说明：

```text
离线 Retrieval p95 约 7 ms
真实 Agent 端到端 p95 约 24.55 s
```

模型规划、两轮网络调用和生成才是当前端到端延迟主体。精确关键词也只是可重复代理指标；第 9 周需要
增加同义表达标注、人工抽检或独立 Judge，区分真正错误与评分假阴性。

运行真实评测：

```bash
DEVAGENT_ENABLE_LIVE_EVAL=1 \
  uv run --locked python scripts/run_live_rag_eval.py
```

重新评分已有真实输出，不产生新的 API 调用：

```bash
uv run --locked python scripts/run_live_rag_eval.py \
  --input-json eval/reports/rag_live_provider.json
```

### 为什么真实评测仍不进入默认 pytest

真实调用存在费用、网络波动、provider 限流和模型随机性。默认 pytest 继续使用固定客户端验证 runner
本身，但项目验收必须额外生成真实报告。二者职责不同：

```text
deterministic tests：证明代码契约和评分器稳定
live report：证明真实模型、Runtime、工具和最终答案链路能够工作
```

没有 live report 的用户业务能力只能写“已实现，真实验收待完成”，不能写成完整闭环。

## Live CI Diagnosis Evaluation

固定 CI case 经过以下真实链路：

```text
examples/sample_ci/7229c86.json
  -> get_ci_result
  -> code-only git_diff
  -> DiagnosisInput
  -> DiagnosisReportDraft Prompt
  -> gpt-5.6-terra / Responses
  -> DiagnosisService 绑定权威字段
  -> DiagnosisReport Pydantic 校验
  -> 确定性验收指标
```

报告：

```text
eval/reports/ci_diagnosis_live_summary.md
eval/reports/ci_diagnosis_live_run3.md/json
eval/reports/ci_diagnosis_live_run4.md/json
eval/reports/ci_diagnosis_live_run5.md/json
```

修复后连续三次结果：

| Metric | Result |
| --- | ---: |
| End-to-End Pass Rate | 100.0% (3 / 3) |
| CI + Git Evidence Coverage | 100.0% |
| Grounded Evidence References | 100.0% |
| Expected Keyword Hit Rate | 100.0% |
| Retry-free Runs | 100.0% |
| Average Latency | 17.18 s |
| p95 Latency | 20.97 s |

评测证据只保留 Python 源码和测试 diff，并移除纯注释答案。README 和人工诊断笔记不会进入
Prompt，避免模型直接读取 fixture 的根因说明。

真实 Run 2 曾连续两次返回 `report_mismatch`。这揭示了原契约的职责错误：模型被要求复制
`report_id`、`target`、`scenario` 和完整 `evidence`，服务端再逐字比较。修复后：

```text
模型生成：
status、summary、findings、recommendations、missing_evidence

服务端绑定：
report_id、scenario、target、原始 evidence
```

最终 `DiagnosisReport` 仍会验证所有 evidence 引用。模型引用不存在的 ID 时会得到
`invalid_report`，因此服务端绑定消除的是复制漂移，不是证据约束。

运行一次真实验收：

```bash
DEVAGENT_ENABLE_LIVE_EVAL=1 \
  uv run --locked python scripts/run_live_ci_diagnosis.py \
  --output eval/reports/ci_diagnosis_live_manual.md
```

该命令可能产生模型费用，不进入默认 pytest。固定单 case 的连续成功也不能代表任意仓库上的诊断
准确率；后续应扩充不同失败类型，并记录 token 与成本。

## ContextManager Baseline

Day55 的 ContextManager 指标和 RAG Context Reduction 是两个不同口径。

RAG report：

```text
统计 evidence 正文相对 full corpus 的减少
```

ContextManager report：

```text
统计完整 LLM request messages 相对 canonical history 的减少
包含 role、tool_calls、arguments、ToolResult 和 metadata
```

固定长历史结果：

```text
28,345 -> 3,584 characters
Context Reduction Rate = 87.36%
system prompt retention = 100%
original task retention = 100%
latest block retention = 100%
assistant/tool pairing completeness = 100%
knowledge evidence location completeness = 100%
```

压缩视图只用于当前 LLM 请求；AgentRuntime 继续保存完整 canonical messages，用于 Debug、Trace、审计、
回放和重新压缩。

## Code Review Baseline

固定路径：

```text
eval/cases/code_review/baseline_cases.json
eval/reports/code_review_baseline.md
```

主要指标：

| Metric | Result | Target |
| --- | ---: | ---: |
| HIGH / CRITICAL recall | 85.7% | >= 85% |
| Actionable finding precision | 85.7% | >= 70% |
| Clean-case false-positive rate | 0.0% | <= 20% |
| Evidence reference completeness | 100.0% | 100% |
| Diff location rate | 100.0% | 100% |
| Average context reduction | 50.0% | >= 40% |

Review baseline 使用固定结构化报告验证评分流程，不调用真实 provider。GitHub App 的真实 PR webhook、
installation token 和评论回写属于单独的显式 smoke test。

## 运行方法

运行 RAG Evaluation：

```bash
uv run --locked pytest tests/eval/test_runner.py tests/eval/test_rag_report.py -q
```

运行真实 RAG Agent Evaluation：

```bash
DEVAGENT_ENABLE_LIVE_EVAL=1 \
  uv run --locked python scripts/run_live_rag_eval.py
```

生成 RAG baseline：

```bash
uv run --locked python scripts/generate_rag_baseline.py
```

生成 Code Review baseline：

```bash
uv run --locked python scripts/generate_review_baseline.py
```

运行 Evaluation 模块：

```bash
uv run --locked pytest tests/eval -q
```

运行全量回归：

```bash
uv run --locked pytest -q
```

## 失败分析

RAG 报告保留：

```text
failed_tool_case_ids
missed_evidence_case_ids
missing_answer_keywords
incorrect_non_empty_case_ids
```

诊断顺序：

```text
Tool Hit 下降
  -> 检查注册、参数、ToolResult 和 workspace

Evidence Hit 下降
  -> 检查召回、排序、expected path 和 top_k

Evidence Hit 高但 Keyword Hit 下降
  -> 检查 Chunk、excerpt 截断和 expected keyword

Empty Result Accuracy 下降
  -> 检查无关内容误召回和查询分词

Context Reduction 高但质量下降
  -> 检查 evidence 是否被删除或过度截断，不能只庆祝压缩率

p95 上升
  -> 分离文件发现、切片、索引、检索和工具协议耗时
```

## 第 9 周对比规则

BM25、Vector、Hybrid 和 Hybrid + Rerank 必须使用：

```text
同一固定 corpus
同一 eval cases
同一 top_k
同一 expected paths / keywords
同一 percentile 定义
同一 Context Reduction 公式
```

新增指标：

```text
MRR@5
失败类型分布
候选来源
rerank latency
降级率
```

策略选择不能只按最高命中率决定。需要联合比较：

```text
Evidence Hit / MRR
Context Reduction
p95 latency
资源与 provider 成本
失败降级能力
业务高价值 case 的实际提升
```

## 解释边界

当前自动化 baseline 只代表：

```text
固定本地小型 corpus
固定人工标注 cases
确定性 BM25 和工具协议
本机离线检索耗时
```

不应表述为：

```text
生产仓库准确率 100%
最终 LLM 回答准确率 100%
所有环境 p95 都是 7.19 ms
BM25 已经是最终最佳策略
```

准确的项目表达是：

> 我先用 20 条固定研发问题建立 BM25 基线。在保持 Top-5 预期证据命中率 100% 的情况下，
> evidence 正文相对整库注入减少 78.9%，固定本地工具链 p95 为约 10 ms。这个结果用于回归和
> 后续策略对比，不代表生产准确率；下一阶段会在同一数据集上扩充难例并比较向量、混合召回和重排。
