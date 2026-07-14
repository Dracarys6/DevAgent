import json

from devagent.diagnosis import (
    DiagnosisInput,
    Evidence,
    EvidenceKind,
    MissingEvidence,
)
from devagent.prompts import CI_DIAGNOSIS_SYSTEM_PROMPT, build_ci_diagnosis_prompt


def make_diagnosis_input() -> DiagnosisInput:
    return DiagnosisInput(
        report_id="report_abc123",
        commit_id="abc123",
        evidence=[
            Evidence(
                evidence_id="E1",
                kind=EvidenceKind.CI_RESULT,
                tool_name="get_ci_result",
                source="pipeline-1001",
                locator="tests/test_uploader.py::test_large_upload_uses_dynamic_timeout",
                excerpt="AssertionError: assert 3 >= 12",
            )
        ],
        missing_evidence=[
            MissingEvidence(
                needed="commit abc123 的真实 Git diff",
                reason="需要确认本次提交是否引入 timeout 行为。",
                suggested_tool="git_diff",
            )
        ],
    )


def extract_prompt_payload(prompt: str) -> str:
    prefix = "CI diagnosis input:\n"
    suffix = "\nReturn only a DiagnosisReport JSON object."
    assert prompt.startswith(prefix)
    assert prompt.endswith(suffix)
    return prompt.removeprefix(prefix).removesuffix(suffix)


def test_ci_diagnosis_system_prompt_requires_evidence_contract():
    assert "evidence_ids" in CI_DIAGNOSIS_SYSTEM_PROMPT
    assert "INPUT Evidence" in CI_DIAGNOSIS_SYSTEM_PROMPT
    assert "insufficient_evidence" in CI_DIAGNOSIS_SYSTEM_PROMPT
    assert "首个异常" in CI_DIAGNOSIS_SYSTEM_PROMPT
    assert "不要 Markdown 围栏" in CI_DIAGNOSIS_SYSTEM_PROMPT


def test_build_ci_diagnosis_prompt_embeds_compact_input_json():
    payload = extract_prompt_payload(build_ci_diagnosis_prompt(make_diagnosis_input()))

    assert '"evidence_id":"E1"' in payload
    assert '"kind":"ci_result"' in payload
    assert '": "' not in payload


def test_build_ci_diagnosis_prompt_keeps_evidence_locator():
    prompt = build_ci_diagnosis_prompt(make_diagnosis_input())

    assert "tests/test_uploader.py::test_large_upload_uses_dynamic_timeout" in prompt


def test_build_ci_diagnosis_prompt_includes_missing_evidence():
    prompt = build_ci_diagnosis_prompt(make_diagnosis_input())

    assert "commit abc123 的真实 Git diff" in prompt
    assert '"suggested_tool":"git_diff"' in prompt


def test_prompt_payload_can_be_parsed_as_json():
    payload = extract_prompt_payload(build_ci_diagnosis_prompt(make_diagnosis_input()))
    parsed = json.loads(payload)

    assert parsed["report_id"] == "report_abc123"
    assert parsed["commit_id"] == "abc123"
    assert parsed["evidence"][0]["evidence_id"] == "E1"
