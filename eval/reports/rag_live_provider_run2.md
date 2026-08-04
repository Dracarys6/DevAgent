# Live RAG Agent Evaluation

- Generated at: `2026-08-04T14:17:32.651161+00:00`
- Commit: `14f112a + working tree`
- Provider: `openai-compatible-live`
- Model: `gpt-5.6-terra`
- API mode: `responses`
- Cases: 8

## End-to-End Metrics

| Metric | Result |
| --- | ---: |
| Valid Answer Rate | 100.0% |
| knowledge_retrieve Tool Call Rate | 100.0% |
| Tool Success Rate | 100.0% |
| Evidence Hit Rate | 100.0% |
| Answer Keyword Hit Rate | 83.3% |
| Expected Path Citation Rate | 100.0% |
| Grounded Citation Rate | 100.0% |
| Abstention Accuracy | 100.0% |
| End-to-End Success Rate | 87.5% |
| Average Latency | 13457.70 ms |
| End-to-End p95 | 16906.07 ms |

- Failed cases: `ci-upload-timeout`
- `ci-upload-timeout`: missing_answer_keyword=expected_seconds, missing_answer_keyword=actual_seconds

## Case Results

### event-bus-publish

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `src/event/bus.py`, `src/api/stream.py`, `src/api/websocket.py`, `src/event/store.py`, `src/trace/service.py`
- Cited paths: `src/event/bus.py`
- Insufficient evidence: False
- Latency: 14710.77 ms
- Attempts: 1
- Attempt errors: None

```text
EventBus.publish(event) iterates over the current `self.subscribers` collection and invokes each subscriber with the `AgentEvent`: `subscriber(event)`. The bus documentation states that it publishes each AgentEvent to current subscribers.
```

### ci-upload-timeout

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `ci/failed.json`, `observability/upload_retry.jsonl`, `logs/task.log`, `ci/permission_failure.json`
- Cited paths: `ci/failed.json`, `observability/upload_retry.jsonl`
- Insufficient evidence: False
- Latency: 11960.09 ms
- Attempts: 1
- Attempt errors: None

```text
CI 测试 `test_large_upload_uses_dynamic_timeout` 失败：期望超时时间为 12 秒，实际超时时间为 3 秒。失败原因是动态超时时间低于所需的上传持续时间。
```

### log-upload-timeout

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `logs/task.log`, `observability/upload_retry.jsonl`, `ci/failed.json`, `ci/permission_failure.json`, `src/diagnosis/service.py`
- Cited paths: `logs/task.log`, `observability/upload_retry.jsonl`, `ci/failed.json`
- Insufficient evidence: False
- Latency: 8683.99 ms
- Attempts: 1
- Attempt errors: None

```text
UploadTimeoutError 发生在 upload_id=upload-42：上传耗时 elapsed_seconds=3，带宽 bandwidth=10，日志显示上传大小为 100 MB。相关记录表明，100 MB 上传的实际预期耗时为 12 秒，而动态超时仅设置为 3 秒，因此超时阈值不足，导致上传失败。
```

### diagnosis-evidence-binding

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `src/diagnosis/service.py`, `src/memory/chunker.py`, `src/tools/knowledge_tools.py`, `docs/github_webhook.md`
- Cited paths: `src/diagnosis/service.py`
- Insufficient evidence: False
- Latency: 13048.12 ms
- Attempts: 1
- Attempt errors: None

```text
DiagnosisService.validate_report 校验每个 finding 的 evidence_ids 是否都引用了 DiagnosisReport.evidence 中已知的 Evidence.evidence_id。只要存在未知引用，就会抛出 ValueError："DiagnosisReport contains an unknown evidence reference"。
```

### review-diff-location

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `src/review/service.py`, `docs/github_webhook.md`, `src/memory/chunker.py`, `src/tools/knowledge_tools.py`, `src/diagnosis/service.py`
- Cited paths: `src/review/service.py`
- Insufficient evidence: False
- Latency: 13575.44 ms
- Attempts: 1
- Attempt errors: None

```text
`ReviewFinding` represents a finding anchored to an exact changed diff location. Its `file_path` identifies the changed file, `line_start` identifies the relevant line, and `side` identifies the diff side; `HEAD` denotes a line added or modified by the proposed change. The class also has an optional `line_end` for a range.
```

### bm25-ranking

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `src/memory/retriever.py`, `src/memory/chunker.py`, `src/tools/knowledge_tools.py`, `docs/github_webhook.md`, `src/permission/manager.py`
- Cited paths: `src/memory/retriever.py`
- Insufficient evidence: False
- Latency: 13582.83 ms
- Attempts: 1
- Attempt errors: None

```text
KeywordRetriever deterministically ranks chunks by BM25 keyword relevance. Its score method calculates inverse document frequency from document frequency, then returns term_frequency × inverse_document_frequency. The source comment states that BM25 also combines term frequency, inverse document frequency, and length normalization, although the shown score method explicitly performs only the term-frequency/IDF multiplication.
```

### negative-payment-billing

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: None
- Cited paths: None
- Insufficient evidence: True
- Latency: 15194.25 ms
- Attempts: 1
- Attempt errors: None

```text
缺少与 payment、billing、invoice 或 settlement 相关的证据，无法回答具体项目问题。
```

### negative-kubernetes-deployment

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: None
- Cited paths: None
- Insufficient evidence: True
- Latency: 16906.07 ms
- Attempts: 1
- Attempt errors: None

```text
缺少与 Kubernetes、Helm、Deployment 或 Ingress 相关的证据，无法基于工作区内容回答。
```

## Acceptance Boundary

This report was produced by a live LLM provider through AgentRuntime and the real knowledge_retrieve tool.
Deterministic labels score tool use, expected keywords, citations, abstention, and latency.
It is stronger than a mock baseline but still represents the listed cases, model, provider, and run time rather than universal production accuracy.
