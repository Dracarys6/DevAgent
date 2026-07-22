from pathlib import Path

import pytest

from devagent.diagnosis import Evidence, EvidenceKind
from devagent.prompts.code_review import build_code_review_prompt
from devagent.review import (
    CodeReviewInput,
    CodeReviewReport,
    DeterministicCodeReviewLLMClient,
    ReviewStatus,
)


def test_fixed_review_llm_copies_identity_and_evidence(tmp_path: Path) -> None:
    review_input = CodeReviewInput(
        review_id="review-smoke",
        base_ref="a" * 40,
        head_ref="b" * 40,
        workspace=str(tmp_path),
        evidence=[
            Evidence(
                evidence_id="E1",
                kind=EvidenceKind.GIT_DIFF,
                tool_name="git_compare",
                source="b" * 40,
                locator="path=src/app.py;line=1",
                excerpt="+ value = 1",
            )
        ],
    )
    client = DeterministicCodeReviewLLMClient()

    response = client.chat(
        [
            {"role": "system", "content": "fixed"},
            {"role": "user", "content": build_code_review_prompt(review_input)},
        ]
    )
    report = CodeReviewReport.model_validate_json(response.content)

    assert report.review_id == "review-smoke"
    assert report.base_ref == "a" * 40
    assert report.head_ref == "b" * 40
    assert report.status == ReviewStatus.REVIEWED
    assert report.findings == []
    assert report.evidence == review_input.evidence
    assert response.metadata["provider"] == "deterministic_review_smoke"


def test_fixed_review_llm_rejects_unrecognized_messages() -> None:
    client = DeterministicCodeReviewLLMClient()

    with pytest.raises(ValueError, match="无法解析"):
        client.chat([{"role": "user", "content": "secret-invalid-prompt"}])
