# RAG Optimization And Week 9 Acceptance

- Generated at: `2026-08-04T14:26:16.712603+00:00`
- Revision: `14f112a + working tree`

## Fixed Dataset Comparison

| Strategy | Cases | Hit@5 | Precision@5 | Recall@5 | NDCG@5 | MRR@5 | Empty | Context reduction | p95 | Location |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | 36 | 100.0% | 20.0% | 100.0% | 98.8% | 98.3% | 100.0% | 77.8% | 5.55 ms | 100.0% |
| vector | 36 | 100.0% | 20.0% | 100.0% | 95.1% | 93.3% | 0.0% | 75.1% | 186.23 ms | 100.0% |
| hybrid_rrf | 36 | 100.0% | 20.0% | 100.0% | 98.8% | 98.3% | 0.0% | 73.8% | 236.93 ms | 100.0% |

## Representative Rerank Subset

| Strategy | Cases | Hit@5 | Precision@5 | Recall@5 | NDCG@5 | MRR@5 | Empty | Context reduction | p95 | Location |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid_rrf | 8 | 100.0% | 20.0% | 100.0% | 93.8% | 91.7% | 0.0% | 73.6% | 286.30 ms | 100.0% |
| hybrid_rerank | 8 | 100.0% | 20.0% | 100.0% | 100.0% | 100.0% | 0.0% | 73.6% | 15247.65 ms | 100.0% |

## Business And Live Acceptance

- Domain Hybrid workflows passed: `True` (3/3 referenced knowledge evidence)
- Business context reduction: 45.2%
- Business locator completeness: 100.0%
- Live runs / cases: 2 / 8
- Minimum Tool Call / Grounded Citation / Abstention: 100.0% / 100.0% / 100.0%
- Mean / minimum strict success: 87.5% / 87.5%
- Aggregate end-to-end p95: 24546.14 ms
- Repeated failed cases: `ci-upload-timeout`=1, `log-upload-timeout`=1

## Default Strategy Decision

- Open Agent default: `bm25`
- Domain-anchored default: `hybrid_rrf`
- High-value explicit rerank: `hybrid_rerank`

- 开放式 Agent 先要求负样本拒答、定位完整性、上下文压缩和延迟全部达标。
- 通过硬门槛后再比较 Recall、Hit、NDCG、MRR、Precision 与成本。
- 领域业务由 CI、日志或 Git 工具提供权威锚点，Hybrid 只补充代码上下文。
- Rerank 仅在质量不回退且调用方接受额外延迟时显式启用。

### Rejected As Global Defaults

- `vector`: Empty Result Accuracy 未达到 100%
- `hybrid_rrf`: Empty Result Accuracy 未达到 100%
- `hybrid_rerank`: 只在代表性子集评测，不能作为全局默认; Empty Result Accuracy 未达到 100%; Retrieval p95 未低于 800 ms

## Evaluation Boundaries

- Precision@5、Recall@5 与 NDCG@5 使用路径级人工判断；未标注路径按不相关处理。
- legacy expected_paths 迁移为 grade 3，当前 NDCG 仍不是 chunk 级完整标注。
- Rerank 只在代表性子集评测，不能与 36 条完整集指标伪装成同口径实验。
- 真实 Agent 稳定性是代表集证据，不等同生产 SLA。
