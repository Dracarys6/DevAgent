# Live RAG Agent Evaluation

- Generated at: `2026-07-30T14:06:17.367200+00:00`
- Commit: `4839764 + working tree`
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
| Answer Keyword Hit Rate | 91.7% |
| Expected Path Citation Rate | 100.0% |
| Grounded Citation Rate | 100.0% |
| Abstention Accuracy | 100.0% |
| End-to-End Success Rate | 87.5% |
| Average Latency | 15235.72 ms |
| End-to-End p95 | 24546.14 ms |

- Failed cases: `log-upload-timeout`
- `log-upload-timeout`: missing_answer_keyword=elapsed_seconds

## Case Results

### event-bus-publish

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `src/event/bus.py`, `src/api/stream.py`, `src/api/websocket.py`, `src/event/store.py`, `src/trace/service.py`
- Cited paths: `src/event/bus.py`
- Insufficient evidence: False
- Latency: 23544.07 ms
- Attempts: 1
- Attempt errors: None

```text
EventBus.publish(event) synchronously iterates over the current subscribers and invokes each subscriber with the AgentEvent: `for subscriber in self.subscribers: subscriber(event)`.
```

### ci-upload-timeout

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `ci/failed.json`, `logs/task.log`
- Cited paths: `ci/failed.json`, `logs/task.log`
- Insufficient evidence: False
- Latency: 7758.32 ms
- Attempts: 1
- Attempt errors: None

```text
CI test_large_upload_uses_dynamic_timeout failed: expected_seconds=12, actual_seconds=3. The dynamic timeout was lower than the required upload duration, causing an UploadTimeoutError after 3 seconds.
```

### log-upload-timeout

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `logs/task.log`, `ci/failed.json`, `src/diagnosis/service.py`, `src/trace/service.py`, `src/event/store.py`
- Cited paths: `logs/task.log`, `ci/failed.json`
- Insufficient evidence: False
- Latency: 24546.14 ms
- Attempts: 1
- Attempt errors: None

```text
上传 upload-42 在带宽为 10 时于启动后 3 秒发生 UploadTimeoutError。失败测试表明动态超时实际设置为 3 秒，但该大文件上传预期需要 12 秒；因此根因是动态超时低于所需上传时长。
```

### diagnosis-evidence-binding

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `src/diagnosis/service.py`, `src/memory/chunker.py`, `src/tools/knowledge_tools.py`
- Cited paths: `src/diagnosis/service.py`
- Insufficient evidence: False
- Latency: 11457.42 ms
- Attempts: 1
- Attempt errors: None

```text
DiagnosisService.validate_report builds the set of known evidence IDs from report.evidence, then verifies that every ID in each finding.evidence_ids belongs to that set. If any finding references an unknown ID, it raises ValueError("DiagnosisReport contains an unknown evidence reference").
```

### review-diff-location

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `src/review/service.py`, `src/memory/chunker.py`, `src/tools/knowledge_tools.py`, `src/diagnosis/service.py`
- Cited paths: `src/review/service.py`
- Insufficient evidence: False
- Latency: 12651.79 ms
- Attempts: 1
- Attempt errors: None

```text
ReviewFinding represents a finding tied to an exact changed-diff location. Its fields are file_path (string), line_start (integer), line_end (optional integer), and side (string). A side value of HEAD identifies a line added or modified by the proposed change.
```

### bm25-ranking

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: `src/memory/retriever.py`, `src/memory/chunker.py`
- Cited paths: `src/memory/retriever.py`
- Insufficient evidence: False
- Latency: 12431.35 ms
- Attempts: 1
- Attempt errors: None

```text
KeywordRetriever uses deterministic BM25 keyword relevance. Its score multiplies term frequency by inverse document frequency; BM25 also includes length normalization.
```

### negative-payment-billing

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: None
- Cited paths: None
- Insufficient evidence: True
- Latency: 9775.91 ms
- Attempts: 1
- Attempt errors: None

```text
缺少与 payment、billing、invoice 或 settlement 相关的证据，无法回答具体问题。
```

### negative-kubernetes-deployment

- Run status: `success`
- Tool called / success: True / True
- Retrieved paths: None
- Cited paths: None
- Insufficient evidence: True
- Latency: 19720.79 ms
- Attempts: 1
- Attempt errors: None

```text
缺少证据：工作区中没有检索到与 Kubernetes、Helm、Deployment 或 Ingress 相关的 EvidenceSnippet，无法基于项目资料回答。
```

## Acceptance Boundary

This report was produced by a live LLM provider through AgentRuntime and the real knowledge_retrieve tool.
Deterministic labels score tool use, expected keywords, citations, abstention, and latency.
It is stronger than a mock baseline but still represents the listed cases, model, provider, and run time rather than universal production accuracy.
