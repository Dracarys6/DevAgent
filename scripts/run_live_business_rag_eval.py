import json
import os
import subprocess
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from devagent.diagnosis import (
    EvidenceKind,
    LocalCIEvidenceCollector,
    LocalLogEvidenceCollector,
)
from devagent.eval import (
    BusinessRAGCase,
    create_live_review_collector,
    evaluate_business_rag,
    load_live_embedding_settings,
    render_business_rag_report,
    run_live_ci_diagnosis,
    run_live_code_review,
    run_live_log_diagnosis,
)
from devagent.llm import create_openai_llm_client
from devagent.memory import OpenAIEmbeddingConfig, OpenAIEmbeddingProvider
from devagent.review import LocalCodeReviewEvidenceCollector
from devagent.tools.knowledge_service import (
    CachedHybridRetrieverFactory,
    WorkspaceKnowledgeService,
)
from devagent.tools.knowledge_tools import load_workspace_documents

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_WORKSPACE = PROJECT_ROOT / "examples" / "sample_repo"
SAMPLE_LOG_DIR = PROJECT_ROOT / "examples" / "sample_logs"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "reports" / "rag_business_live.md"
CI_TARGET = "7229c86"
LOG_TARGET = "task_001"
REVIEW_BASE_REF = "7229c86^"
REVIEW_HEAD_REF = "7229c86"


def main() -> None:
    parser = ArgumentParser(
        description="显式调用真实 Embedding 与 LLM provider 验收业务 RAG 链路"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args()

    llm_settings = _load_live_llm_settings()
    embedding_settings = load_live_embedding_settings(PROJECT_ROOT)
    embedding_client = OpenAI(
        api_key=embedding_settings.api_key,
        base_url=embedding_settings.base_url,
        timeout=30.0,
        max_retries=1,
    )
    embedding_provider = OpenAIEmbeddingProvider(
        client=embedding_client,
        config=OpenAIEmbeddingConfig(
            model=embedding_settings.model,
            batch_size=embedding_settings.batch_size,
            dimensions=embedding_settings.dimensions,
        ),
    )
    knowledge_service = WorkspaceKnowledgeService(
        document_loader=load_workspace_documents,
        retriever_factory=CachedHybridRetrieverFactory(
            embedding_provider=embedding_provider,
        ),
    )

    def client_factory():
        return create_openai_llm_client(
            api_key=llm_settings["api_key"],
            model=llm_settings["model"],
            base_url=llm_settings["base_url"],
            api_mode=llm_settings["api_mode"],
            response_format={"type": "json_object"},
            reasoning_effort=llm_settings["reasoning_effort"],
            max_tokens=8_192,
        )

    ci_run = run_live_ci_diagnosis(
        llm_client_factory=client_factory,
        commit_id=CI_TARGET,
        workspace=str(SAMPLE_WORKSPACE),
        workspace_label="examples/sample_repo",
        provider="openai-compatible-live",
        model=llm_settings["model"],
        api_mode=llm_settings["api_mode"],
        expected_keywords=["build_upload_timeout", "min_timeout_seconds"],
        ci_evidence_collector=LocalCIEvidenceCollector(
            knowledge_retriever=knowledge_service.retrieve
        ),
        max_attempts=args.max_attempts,
    )
    log_run = run_live_log_diagnosis(
        llm_client_factory=client_factory,
        task_id=LOG_TARGET,
        data_dir=SAMPLE_LOG_DIR,
        data_dir_label="examples/sample_logs",
        workspace=SAMPLE_WORKSPACE,
        provider="openai-compatible-live",
        model=llm_settings["model"],
        api_mode=llm_settings["api_mode"],
        expected_keywords=["UploadTimeoutError", "RetryExhaustedError", "3 秒"],
        log_evidence_collector=LocalLogEvidenceCollector(
            knowledge_retriever=knowledge_service.retrieve
        ),
        max_attempts=args.max_attempts,
    )
    review_run = run_live_code_review(
        llm_client_factory=client_factory,
        base_ref=REVIEW_BASE_REF,
        head_ref=REVIEW_HEAD_REF,
        workspace=SAMPLE_WORKSPACE,
        workspace_label="examples/sample_repo",
        provider="openai-compatible-live",
        model=llm_settings["model"],
        api_mode=llm_settings["api_mode"],
        expected_finding=_expected_review_finding(),
        evidence_collector=create_live_review_collector(
            knowledge_retriever=knowledge_service.retrieve
        ),
        max_attempts=args.max_attempts,
    )

    if ci_run.report is None or log_run.report is None or review_run.report is None:
        context_run = None
    else:
        workspace_chars = sum(
            len(document.content)
            for document in load_workspace_documents(SAMPLE_WORKSPACE)
        )
        legacy_review = LocalCodeReviewEvidenceCollector().collect(
            review_id="context-baseline",
            base_ref=REVIEW_BASE_REF,
            head_ref=REVIEW_HEAD_REF,
            workspace=SAMPLE_WORKSPACE,
        )
        context_run = evaluate_business_rag(
            [
                _diagnosis_context_case(
                    "ci-upload-timeout",
                    "ci_failure",
                    ci_run.report.evidence,
                    ci_run.report.missing_evidence,
                    workspace_chars,
                ),
                _diagnosis_context_case(
                    "log-upload-timeout",
                    "log_failure",
                    log_run.report.evidence,
                    log_run.report.missing_evidence,
                    workspace_chars,
                ),
                BusinessRAGCase(
                    case_id="review-upload-timeout",
                    scenario="code_review",
                    baseline_context_chars=sum(
                        len(item.excerpt) for item in legacy_review.evidence
                    ),
                    evidence=review_run.report.evidence,
                    missing_evidence=review_run.report.missing_evidence,
                ),
            ]
        )

    generated_at = datetime.now(UTC).isoformat()
    revision = _current_revision()
    summary = _build_summary(
        generated_at=generated_at,
        revision=revision,
        llm_settings=llm_settings,
        embedding_model=embedding_settings.model,
        ci_run=ci_run,
        log_run=log_run,
        review_run=review_run,
        context_run=context_run,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _render_report(summary, context_run=context_run),
        encoding="utf-8",
    )
    json_output = output.with_suffix(".json")
    json_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Live Business RAG report 已生成: {output}")
    print(f"Live Business RAG summary 已生成: {json_output}")
    print(
        "业务 RAG 端到端验收: "
        f"{'PASS' if summary['passed'] else 'FAIL'}；"
        f"上下文减少 {summary['context']['average_reduction_rate'] * 100:.1f}%；"
        f"Hybrid 索引策略 cached_snapshot"
    )
    if not summary["passed"]:
        raise SystemExit(1)


def _diagnosis_context_case(
    case_id: str,
    scenario: str,
    evidence: list,
    missing_evidence: list,
    workspace_chars: int,
) -> BusinessRAGCase:
    domain_chars = sum(
        len(item.excerpt) for item in evidence if item.kind != EvidenceKind.KNOWLEDGE
    )
    return BusinessRAGCase(
        case_id=case_id,
        scenario=scenario,
        baseline_context_chars=domain_chars + workspace_chars,
        evidence=evidence,
        missing_evidence=missing_evidence,
    )


def _build_summary(
    *,
    generated_at: str,
    revision: str,
    llm_settings: dict[str, str | None],
    embedding_model: str,
    ci_run,
    log_run,
    review_run,
    context_run,
) -> dict[str, Any]:
    workflow_runs = {
        "ci_failure": ci_run,
        "log_failure": log_run,
        "code_review": review_run,
    }
    workflow_summary: dict[str, dict[str, Any]] = {}
    knowledge_reference_cases = 0
    for name, run in workflow_runs.items():
        report = run.report
        knowledge_ids = (
            {
                item.evidence_id
                for item in report.evidence
                if item.kind == EvidenceKind.KNOWLEDGE
            }
            if report is not None
            else set()
        )
        referenced_ids = _referenced_evidence_ids(report)
        knowledge_referenced = bool(knowledge_ids & referenced_ids)
        knowledge_reference_cases += knowledge_referenced
        workflow_summary[name] = {
            "passed": run.metrics.passed,
            "metrics": run.metrics.model_dump(mode="json"),
            "latency_ms": run.latency_ms,
            "attempt_count": run.attempt_count,
            "attempt_errors": run.attempt_errors,
            "knowledge_evidence_count": len(knowledge_ids),
            "knowledge_referenced": knowledge_referenced,
            "evidence_reference_grounded": run.metrics.evidence_references_grounded,
        }
    context = (
        {
            "passed": context_run.metrics.passed,
            "average_reduction_rate": (
                context_run.metrics.average_context_reduction_rate
            ),
            "locator_completeness_rate": (
                context_run.metrics.retrieval_locator_completeness_rate
            ),
            "domain_flow_availability_rate": (
                context_run.metrics.domain_flow_availability_rate
            ),
            "duplicate_location_count": context_run.metrics.duplicate_location_count,
            "cases": [case.model_dump(mode="json") for case in context_run.cases],
        }
        if context_run is not None
        else {
            "passed": False,
            "average_reduction_rate": 0.0,
            "locator_completeness_rate": 0.0,
            "domain_flow_availability_rate": 0.0,
            "duplicate_location_count": 0,
            "cases": [],
        }
    )
    passed = all(
        item["passed"]
        and item["knowledge_evidence_count"] > 0
        and item["evidence_reference_grounded"]
        for item in workflow_summary.values()
    ) and bool(context["passed"] and knowledge_reference_cases > 0)
    return {
        "generated_at": generated_at,
        "revision": revision,
        "provider": "openai-compatible-live",
        "model": llm_settings["model"],
        "api_mode": llm_settings["api_mode"],
        "embedding_model": embedding_model,
        "retrieval_strategy": "hybrid_rrf_cached_snapshot",
        "workflows": workflow_summary,
        "knowledge_reference_case_count": knowledge_reference_cases,
        "context": context,
        "passed": passed,
    }


def _referenced_evidence_ids(report) -> set[str]:
    if report is None:
        return set()
    references = {
        evidence_id
        for finding in report.findings
        for evidence_id in finding.evidence_ids
    }
    for recommendation in getattr(report, "recommendations", []):
        references.update(recommendation.evidence_ids)
    return references


def _render_report(summary: dict[str, Any], *, context_run) -> str:
    lines = [
        "# Live Business RAG Evaluation",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- DevAgent revision: `{summary['revision']}`",
        f"- LLM: `{summary['provider']}:{summary['model']}`",
        f"- Embedding model: `{summary['embedding_model']}`",
        f"- Retrieval strategy: `{summary['retrieval_strategy']}`",
        "",
        "## Workflows",
        "",
        "| Workflow | Passed | Latency ms | Attempts | Knowledge | Referenced |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, workflow in summary["workflows"].items():
        lines.append(
            f"| {name} | {workflow['passed']} | "
            f"{workflow['latency_ms']:.2f} | {workflow['attempt_count']} | "
            f"{workflow['knowledge_evidence_count']} | "
            f"{workflow['knowledge_referenced']} |"
        )
    lines.extend(
        [
            "",
            f"Overall passed: **{summary['passed']}**",
            "",
        ]
    )
    if context_run is not None:
        lines.append(
            render_business_rag_report(
                context_run,
                generated_at=summary["generated_at"],
                revision=summary["revision"],
            )
        )
    return "\n".join(lines)


def _load_live_llm_settings() -> dict[str, str | None]:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
    if os.getenv("DEVAGENT_ENABLE_LIVE_EVAL") != "1":
        raise SystemExit("真实模型评测未启用；请设置 DEVAGENT_ENABLE_LIVE_EVAL=1")
    api_key = os.getenv("DEVAGENT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("DEVAGENT_LLM_MODEL")
    if not api_key:
        raise SystemExit("真实模型评测缺少 DEVAGENT_LLM_API_KEY")
    if not model:
        raise SystemExit("真实模型评测缺少 DEVAGENT_LLM_MODEL")
    return {
        "api_key": api_key,
        "model": model,
        "base_url": os.getenv("DEVAGENT_LLM_BASE_URL") or None,
        "api_mode": os.getenv("DEVAGENT_LLM_API_MODE", "chat_completions"),
        "reasoning_effort": os.getenv("DEVAGENT_LLM_REASONING_EFFORT") or None,
    }


def _expected_review_finding():
    from devagent.eval import LiveReviewExpectedFinding
    from devagent.review import ReviewCategory, ReviewLineSide, ReviewSeverity

    return LiveReviewExpectedFinding(
        category=ReviewCategory.CORRECTNESS,
        severities=[
            ReviewSeverity.MEDIUM,
            ReviewSeverity.HIGH,
            ReviewSeverity.CRITICAL,
        ],
        file_path="src/sample_app/uploader.py",
        line=24,
        side=ReviewLineSide.HEAD,
        keywords=["build_upload_timeout", "min_timeout_seconds"],
    )


def _current_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return f"{result.stdout.strip()} + working tree"


if __name__ == "__main__":
    main()
