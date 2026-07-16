import json
from pathlib import Path
from typing import Any

import pytest

from devagent.diagnosis import (
    DiagnosisReport,
    DiagnosisService,
    DiagnosisServiceError,
    DiagnosisServiceErrorCode,
    DiagnosisStatus,
    LocalCIEvidenceCollector,
)
from devagent.llm import LLMResponse
from devagent.tools.git_tools import GitDiffError

FIXTURE_DIR = (
    Path(__file__).parents[1] / "fixtures" / "diagnosis_cases"
)
CI_RESULT = json.dumps(
    {
        "pipeline_id": "pipeline-1001",
        "status": "failed",
        "failed_jobs": [{"name": "unit-tests", "status": "failed"}],
        "core_log": "AssertionError: assert 3 >= 12",
    },
    ensure_ascii=False,
)
GIT_DIFF = (
    "diff --git a/uploader.py b/uploader.py\n"
    "+return self.config.min_timeout_seconds"
)


def load_case(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class FixedLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        self.requests.append(messages)
        return LLMResponse.final_answer(self.content)


def make_service(
    fixture_name: str,
    *,
    git_diff_reader=lambda commit_id, workspace: GIT_DIFF,
) -> tuple[DiagnosisService, FixedLLMClient]:
    client = FixedLLMClient(load_case(fixture_name))
    collector = LocalCIEvidenceCollector(
        ci_result_reader=lambda commit_id: CI_RESULT,
        git_diff_reader=git_diff_reader,
    )
    service = DiagnosisService(
        llm_client=client,
        ci_evidence_collector=collector,
        report_id_factory=lambda: "report-ci-001",
    )
    return service, client


def test_ci_diagnosis_runs_three_times_without_state_pollution():
    service, client = make_service("ci_diagnosed.json")

    reports = [
        service.diagnose_ci(
            commit_id="abc123",
            workspace="examples/sample_repo",
        )
        for _ in range(3)
    ]

    assert len(reports) == 3
    assert all(
        report.status == DiagnosisStatus.DIAGNOSED
        for report in reports
    )
    assert all(report == reports[0] for report in reports)
    assert len(client.requests) == 3
    assert all(
        '"evidence_id":"E2"' in messages[1]["content"]
        for messages in client.requests
    )


def test_ci_diagnosis_degrades_when_git_diff_is_missing():
    def failing_git_diff(commit_id: str, workspace: str) -> str:
        raise GitDiffError(f"无法读取 Git commit: {commit_id}")

    service, _ = make_service(
        "ci_insufficient_evidence.json",
        git_diff_reader=failing_git_diff,
    )

    report = service.diagnose_ci(
        commit_id="abc123",
        workspace="examples/sample_repo",
    )

    assert report.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert [item.evidence_id for item in report.evidence] == ["E1"]
    assert report.missing_evidence[0].suggested_tool == "git_diff"


@pytest.mark.parametrize(
    ("fixture_name", "expected_code"),
    [
        ("ci_invalid_reference.json", DiagnosisServiceErrorCode.INVALID_REPORT),
    ],
)
def test_ci_diagnosis_rejects_invalid_fixed_report(
    fixture_name: str,
    expected_code: DiagnosisServiceErrorCode,
):
    service, _ = make_service(fixture_name)

    with pytest.raises(DiagnosisServiceError) as exc_info:
        service.diagnose_ci(commit_id="abc123")

    assert exc_info.value.code == expected_code


def test_diagnosis_fixture_files_have_expected_contract():
    diagnosed = DiagnosisReport.model_validate_json(
        load_case("ci_diagnosed.json")
    )
    insufficient = DiagnosisReport.model_validate_json(
        load_case("ci_insufficient_evidence.json")
    )

    assert diagnosed.status == DiagnosisStatus.DIAGNOSED
    assert insufficient.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
