from pathlib import Path
from typing import Any

import pytest

from devagent.diagnosis import Evidence, EvidenceKind, MissingEvidence
from devagent.llm import LLMResponse, ToolCall
from devagent.review import (
    CodeReviewInput,
    CodeReviewReport,
    CodeReviewService,
    CodeReviewServiceError,
    CodeReviewServiceErrorCode,
    LocalCodeReviewEvidenceCollector,
    ReviewStatus,
)
from devagent.tools.git_tools import (
    GitChangedFile,
    GitCompareError,
    GitCompareResult,
)
from devagent.tools.read_file_tools import ReadFileError


def make_compare_result(**overrides: object) -> GitCompareResult:
    data: dict[str, object] = {
        "base_ref": "main",
        "head_ref": "feature",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "merge_base": "c" * 40,
        "changed_files": [
            GitChangedFile(status="M", old_path="src/app.py", new_path="src/app.py")
        ],
        "patch": "@@ -1 +1 @@\n-old\n+new\n",
        "hunk_count": 1,
        "truncated": False,
        "original_patch_chars": 25,
        "returned_patch_chars": 25,
    }
    data.update(overrides)
    return GitCompareResult.model_validate(data)


def make_evidence(evidence_id: str = "E1", excerpt: str = "diff evidence") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=EvidenceKind.GIT_DIFF,
        tool_name="git_compare",
        source="b" * 40,
        locator="merge_base=abc;hunks=1",
        excerpt=excerpt,
    )


def make_review_input(root: Path, **overrides: object) -> CodeReviewInput:
    data: dict[str, object] = {
        "review_id": "review-1",
        "base_ref": "main",
        "head_ref": "feature",
        "workspace": str(root),
        "evidence": [make_evidence()],
        "missing_evidence": [],
    }
    data.update(overrides)
    return CodeReviewInput.model_validate(data)


def make_report(review_input: CodeReviewInput, **overrides: object) -> CodeReviewReport:
    data: dict[str, object] = {
        "review_id": review_input.review_id,
        "base_ref": review_input.base_ref,
        "head_ref": review_input.head_ref,
        "status": ReviewStatus.REVIEWED,
        "summary": "未发现可行动问题。",
        "findings": [],
        "evidence": review_input.evidence,
        "missing_evidence": review_input.missing_evidence,
    }
    data.update(overrides)
    return CodeReviewReport.model_validate(data)


class FixedCollector:
    def __init__(self, review_input: CodeReviewInput) -> None:
        self.review_input = review_input
        self.calls: list[dict[str, object]] = []

    def collect(self, **kwargs: object) -> CodeReviewInput:
        self.calls.append(kwargs)
        return self.review_input


class RaisingCollector:
    def collect(self, **kwargs: object) -> CodeReviewInput:
        raise RuntimeError("collector internal detail")


class InvalidCollector:
    def collect(self, **kwargs: object) -> Any:
        return {"review_id": "review-1"}


class FixedLLMClient:
    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.messages: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        self.messages.append(messages)
        return self.response


class SequenceLLMClient:
    def __init__(self, responses: list[LLMResponse | Exception]) -> None:
        self.responses = responses
        self.messages: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        self.messages.append(messages)
        response = self.responses[len(self.messages) - 1]
        if isinstance(response, Exception):
            raise response
        return response


class RaisingLLMClient:
    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        raise RuntimeError("secret-provider-detail")


class RecordingFileReader:
    def __init__(self, content: str = "1: value = 1") -> None:
        self.content = content
        self.calls: list[tuple[str | Path, dict[str, object]]] = []

    def __call__(self, file_path: str | Path, **kwargs: object) -> str:
        self.calls.append((file_path, kwargs))
        return self.content


def make_service(
    *,
    review_input: CodeReviewInput,
    response: LLMResponse | None = None,
) -> tuple[CodeReviewService, FixedCollector, FixedLLMClient]:
    collector = FixedCollector(review_input)
    client = FixedLLMClient(
        response or LLMResponse.final_answer(make_report(review_input).model_dump_json())
    )
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=collector,
        review_id_factory=lambda: "review-1",
    )
    return service, collector, client


def test_local_collector_builds_bounded_diff_and_file_evidence(tmp_path: Path) -> None:
    result = make_compare_result(patch="x" * 5_000)
    reader = RecordingFileReader("1: value = 1\n2: return value")
    collector = LocalCodeReviewEvidenceCollector(
        git_compare_reader=lambda base, head, workspace: result,
        file_reader=reader,
    )

    review_input = collector.collect(
        review_id="review-1",
        base_ref="main",
        head_ref="feature",
        workspace=tmp_path,
    )

    assert [item.evidence_id for item in review_input.evidence] == ["E1", "E2"]
    assert review_input.evidence[0].kind == EvidenceKind.GIT_DIFF
    assert len(review_input.evidence[0].excerpt) == 4_000
    assert review_input.evidence[1].kind == EvidenceKind.CODE
    assert review_input.evidence[1].source == str(tmp_path)
    assert review_input.evidence[1].locator == "path=src/app.py;lines=1-2"
    assert reader.calls == [
        (
            "src/app.py",
            {"start_line": 1, "max_lines": 200, "workspace": tmp_path},
        )
    ]


def test_local_collector_records_truncated_patch(tmp_path: Path) -> None:
    result = make_compare_result(
        truncated=True,
        original_patch_chars=30_000,
        returned_patch_chars=20_000,
    )
    collector = LocalCodeReviewEvidenceCollector(
        git_compare_reader=lambda base, head, workspace: result,
        file_reader=RecordingFileReader(),
    )

    review_input = collector.collect(
        review_id="review-1",
        base_ref="main",
        head_ref="feature",
        workspace=tmp_path,
    )

    assert review_input.evidence[0].locator.endswith("truncated=true")
    assert review_input.missing_evidence[0].needed == "完整的 merge-base diff"
    assert "20000" in review_input.missing_evidence[0].reason
    assert "30000" in review_input.missing_evidence[0].reason


def test_local_collector_degrades_git_compare_error(tmp_path: Path) -> None:
    def fail_compare(base: str, head: str, workspace: str | Path) -> GitCompareResult:
        raise GitCompareError("无法解析 head_ref")

    collector = LocalCodeReviewEvidenceCollector(git_compare_reader=fail_compare)

    review_input = collector.collect(
        review_id="review-1",
        base_ref="main",
        head_ref="feature",
        workspace=tmp_path,
    )

    assert review_input.evidence == []
    assert review_input.missing_evidence[0].suggested_tool == "git_compare"
    assert review_input.missing_evidence[0].reason == "无法解析 head_ref"


def test_local_collector_keeps_diff_when_file_read_fails(tmp_path: Path) -> None:
    def fail_read(file_path: str | Path, **kwargs: object) -> str:
        raise ReadFileError(f"outside workspace: {tmp_path / file_path}")

    collector = LocalCodeReviewEvidenceCollector(
        git_compare_reader=lambda base, head, workspace: make_compare_result(),
        file_reader=fail_read,
    )

    review_input = collector.collect(
        review_id="review-1",
        base_ref="main",
        head_ref="feature",
        workspace=tmp_path,
    )

    assert len(review_input.evidence) == 1
    assert review_input.evidence[0].kind == EvidenceKind.GIT_DIFF
    assert review_input.missing_evidence[0].reason == "无法安全读取变更文件"
    assert str(tmp_path) not in review_input.missing_evidence[0].reason


def test_local_collector_skips_deleted_duplicate_and_excess_files(tmp_path: Path) -> None:
    changed_files = [
        GitChangedFile(status="D", old_path="deleted.py", new_path=None),
        GitChangedFile(status="M", old_path="one.py", new_path="one.py"),
        GitChangedFile(status="M", old_path="one.py", new_path="one.py"),
        *[
            GitChangedFile(status="A", old_path=None, new_path=f"file-{index}.py")
            for index in range(2, 8)
        ],
    ]
    reader = RecordingFileReader()
    collector = LocalCodeReviewEvidenceCollector(
        git_compare_reader=lambda base, head, workspace: make_compare_result(
            changed_files=changed_files
        ),
        file_reader=reader,
    )

    review_input = collector.collect(
        review_id="review-1",
        base_ref="main",
        head_ref="feature",
        workspace=tmp_path,
    )

    assert [call[0] for call in reader.calls] == [
        "one.py",
        "file-2.py",
        "file-3.py",
        "file-4.py",
        "file-5.py",
    ]
    assert len(review_input.evidence) == 6


@pytest.mark.parametrize(
    "bad_reader",
    [lambda file_path, **kwargs: None, lambda file_path, **kwargs: 123],
)
def test_local_collector_rejects_invalid_file_reader_output(
    tmp_path: Path,
    bad_reader: Any,
) -> None:
    collector = LocalCodeReviewEvidenceCollector(
        git_compare_reader=lambda base, head, workspace: make_compare_result(),
        file_reader=bad_reader,
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        collector.collect(
            review_id="review-1",
            base_ref="main",
            head_ref="feature",
            workspace=tmp_path,
        )

    assert exc_info.value.code == CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED


def test_local_collector_rejects_mismatched_compare_refs(tmp_path: Path) -> None:
    collector = LocalCodeReviewEvidenceCollector(
        git_compare_reader=lambda base, head, workspace: make_compare_result(
            head_ref="other"
        )
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        collector.collect(
            review_id="review-1",
            base_ref="main",
            head_ref="feature",
            workspace=tmp_path,
        )

    assert exc_info.value.code == CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED


def test_code_review_service_returns_validated_report_and_messages(tmp_path: Path) -> None:
    review_input = make_review_input(tmp_path)
    service, collector, client = make_service(review_input=review_input)

    report = service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert report == make_report(review_input)
    assert collector.calls == [
        {
            "review_id": "review-1",
            "base_ref": "main",
            "head_ref": "feature",
            "workspace": tmp_path.resolve(),
        }
    ]
    assert len(client.messages) == 1
    assert client.messages[0][0]["role"] == "system"
    assert client.messages[0][0]["content"]
    assert client.messages[0][1]["role"] == "user"
    assert "review-1" in client.messages[0][1]["content"]


def test_code_review_service_short_circuits_without_evidence(tmp_path: Path) -> None:
    missing = MissingEvidence(
        needed="merge-base diff",
        reason="无法解析 head_ref",
        suggested_tool="git_compare",
    )
    review_input = make_review_input(
        tmp_path,
        evidence=[],
        missing_evidence=[missing],
    )
    service, _, client = make_service(review_input=review_input)

    report = service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert report.status == ReviewStatus.INSUFFICIENT_EVIDENCE
    assert report.findings == []
    assert report.missing_evidence == [missing]
    assert client.messages == []


def test_code_review_service_adds_missing_reason_for_empty_collector(tmp_path: Path) -> None:
    review_input = make_review_input(tmp_path, evidence=[], missing_evidence=[])
    service, _, client = make_service(review_input=review_input)

    report = service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert report.status == ReviewStatus.INSUFFICIENT_EVIDENCE
    assert report.missing_evidence[0].reason == "证据采集器未返回可用证据"
    assert client.messages == []


@pytest.mark.parametrize(
    ("base_ref", "head_ref", "workspace_kind"),
    [
        ("", "feature", "directory"),
        (" main", "feature", "directory"),
        ("main", "main", "directory"),
        ("main", "feature", "missing"),
        ("main", "feature", "file"),
    ],
)
def test_code_review_service_rejects_invalid_request_before_dependencies(
    tmp_path: Path,
    base_ref: str,
    head_ref: str,
    workspace_kind: str,
) -> None:
    workspace = tmp_path
    if workspace_kind == "missing":
        workspace = tmp_path / "missing"
    elif workspace_kind == "file":
        workspace = tmp_path / "file.txt"
        workspace.write_text("content", encoding="utf-8")
    review_input = make_review_input(tmp_path)
    service, collector, client = make_service(review_input=review_input)

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref=base_ref, head_ref=head_ref, workspace=workspace)

    assert exc_info.value.code == CodeReviewServiceErrorCode.INVALID_REQUEST
    assert collector.calls == []
    assert client.messages == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("review_id", "other-review"),
        ("base_ref", "develop"),
        ("head_ref", "other-feature"),
        ("workspace", "/tmp/other-workspace"),
    ],
)
def test_code_review_service_rejects_mismatched_collector_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    review_input = make_review_input(tmp_path, **{field: value})
    service, _, client = make_service(review_input=review_input)

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED
    assert client.messages == []


def test_code_review_service_wraps_collector_error(tmp_path: Path) -> None:
    client = FixedLLMClient(LLMResponse.final_answer("{}"))
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=RaisingCollector(),
        review_id_factory=lambda: "review-1",
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED
    assert "internal detail" not in str(exc_info.value)
    assert client.messages == []


def test_code_review_service_rejects_invalid_collector_result(tmp_path: Path) -> None:
    client = FixedLLMClient(LLMResponse.final_answer("{}"))
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=InvalidCollector(),
        review_id_factory=lambda: "review-1",
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED
    assert client.messages == []


def test_code_review_service_rejects_invalid_review_id_factory(tmp_path: Path) -> None:
    client = FixedLLMClient(LLMResponse.final_answer("{}"))
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=FixedCollector(make_review_input(tmp_path)),
        review_id_factory=lambda: "",
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED


def test_code_review_service_wraps_review_id_factory_error(tmp_path: Path) -> None:
    def fail_id_factory() -> str:
        raise RuntimeError("id factory internal detail")

    client = FixedLLMClient(LLMResponse.final_answer("{}"))
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=FixedCollector(make_review_input(tmp_path)),
        review_id_factory=fail_id_factory,
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED
    assert "internal detail" not in str(exc_info.value)


def test_code_review_service_rejects_tool_call_response(tmp_path: Path) -> None:
    review_input = make_review_input(tmp_path)
    response = LLMResponse.tool_calls_response(
        [ToolCall(id="call-1", name="read_file", arguments={})]
    )
    service, _, client = make_service(review_input=review_input, response=response)

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.UNEXPECTED_LLM_RESPONSE
    assert len(client.messages) == 1


@pytest.mark.parametrize("content", ["", "   "])
def test_code_review_service_rejects_empty_response(
    tmp_path: Path,
    content: str,
) -> None:
    review_input = make_review_input(tmp_path)
    service, _, _ = make_service(
        review_input=review_input,
        response=LLMResponse.final_answer(content),
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.EMPTY_LLM_RESPONSE


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"review_id":"review-1"}',
        (
            '{"review_id":"review-1","base_ref":"main","head_ref":"feature",'
            '"status":"reviewed","summary":"bad reference","findings":['
            '{"finding_id":"R1","severity":"high","category":"correctness",'
            '"title":"title","description":"description","file_path":"app.py",'
            '"line_start":1,"side":"head","evidence_ids":["E2"],'
            '"suggestion":"fix","verification_steps":["test"]}],'
            '"evidence":[],"missing_evidence":[]}'
        ),
    ],
)
def test_code_review_service_rejects_invalid_report(
    tmp_path: Path,
    content: str,
) -> None:
    review_input = make_review_input(tmp_path)
    service, _, _ = make_service(
        review_input=review_input,
        response=LLMResponse.final_answer(content),
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.INVALID_REPORT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("review_id", "other-review"),
        ("base_ref", "develop"),
        ("head_ref", "other-feature"),
        ("evidence", [make_evidence(excerpt="modified evidence")]),
    ],
)
def test_code_review_service_rejects_report_mismatch(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    review_input = make_review_input(tmp_path)
    report = make_report(review_input, **{field: value})
    service, _, _ = make_service(
        review_input=review_input,
        response=LLMResponse.final_answer(report.model_dump_json()),
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.REPORT_MISMATCH


def test_code_review_service_wraps_llm_error_without_leaking_details(
    tmp_path: Path,
) -> None:
    review_input = make_review_input(tmp_path)
    service = CodeReviewService(
        llm_client=RaisingLLMClient(),
        evidence_collector=FixedCollector(review_input),
        review_id_factory=lambda: "review-1",
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.LLM_CALL_FAILED
    assert "secret-provider-detail" not in str(exc_info.value)


def test_code_review_service_retries_invalid_report_with_validation_feedback(
    tmp_path: Path,
) -> None:
    review_input = make_review_input(tmp_path)
    client = SequenceLLMClient(
        [
            LLMResponse.final_answer('{"review_id":"review-1"}'),
            LLMResponse.final_answer(make_report(review_input).model_dump_json()),
        ]
    )
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=FixedCollector(review_input),
        review_id_factory=lambda: "review-1",
    )

    report = service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert report == make_report(review_input)
    assert len(client.messages) == 2
    assert len(client.messages[0]) == 2
    repair_prompt = client.messages[1][-1]["content"]
    assert "invalid_report" in repair_prompt
    assert "base_ref" in repair_prompt
    assert "第 2 次生成尝试" in repair_prompt


def test_code_review_service_reports_token_truncation_during_retry(
    tmp_path: Path,
) -> None:
    review_input = make_review_input(tmp_path)
    client = SequenceLLMClient(
        [
            LLMResponse.final_answer(
                '{"review_id":"review-1"',
                metadata={"finish_reason": "length"},
            ),
            LLMResponse.final_answer(make_report(review_input).model_dump_json()),
        ]
    )
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=FixedCollector(review_input),
        review_id_factory=lambda: "review-1",
    )

    service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert "token 上限被截断" in client.messages[1][-1]["content"]


def test_code_review_service_retries_empty_and_mismatched_reports(
    tmp_path: Path,
) -> None:
    review_input = make_review_input(tmp_path)
    mismatched_report = make_report(review_input, review_id="wrong-review")
    client = SequenceLLMClient(
        [
            LLMResponse.final_answer(""),
            LLMResponse.final_answer(mismatched_report.model_dump_json()),
            LLMResponse.final_answer(make_report(review_input).model_dump_json()),
        ]
    )
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=FixedCollector(review_input),
        review_id_factory=lambda: "review-1",
    )

    report = service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert report.review_id == "review-1"
    assert len(client.messages) == 3
    assert "empty_llm_response" in client.messages[1][-1]["content"]
    assert "report_mismatch" in client.messages[2][-1]["content"]
    assert "review_id 必须与 INPUT.review_id 完全一致" in (
        client.messages[2][-1]["content"]
    )


def test_code_review_service_stops_after_configured_report_attempts(
    tmp_path: Path,
) -> None:
    review_input = make_review_input(tmp_path)
    client = SequenceLLMClient(
        [LLMResponse.final_answer("not-json") for _ in range(3)]
    )
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=FixedCollector(review_input),
        review_id_factory=lambda: "review-1",
        max_report_attempts=3,
    )

    with pytest.raises(CodeReviewServiceError) as exc_info:
        service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert exc_info.value.code == CodeReviewServiceErrorCode.INVALID_REPORT
    assert len(client.messages) == 3


def test_code_review_service_repair_prompt_does_not_repeat_raw_output(
    tmp_path: Path,
) -> None:
    review_input = make_review_input(tmp_path)
    client = SequenceLLMClient(
        [
            LLMResponse.final_answer("secret-invalid-output"),
            LLMResponse.final_answer(make_report(review_input).model_dump_json()),
        ]
    )
    service = CodeReviewService(
        llm_client=client,
        evidence_collector=FixedCollector(review_input),
        review_id_factory=lambda: "review-1",
    )

    service.review(base_ref="main", head_ref="feature", workspace=tmp_path)

    assert "secret-invalid-output" not in client.messages[1][-1]["content"]


@pytest.mark.parametrize("max_report_attempts", [0, 6, True])
def test_code_review_service_rejects_invalid_report_attempt_limit(
    tmp_path: Path,
    max_report_attempts: int,
) -> None:
    review_input = make_review_input(tmp_path)

    with pytest.raises(ValueError, match="max_report_attempts"):
        CodeReviewService(
            llm_client=FixedLLMClient(LLMResponse.final_answer("{}")),
            evidence_collector=FixedCollector(review_input),
            max_report_attempts=max_report_attempts,
        )
