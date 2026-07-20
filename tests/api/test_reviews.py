from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes.reviews import (
    create_review_llm_client,
    get_code_review_service,
)
from devagent.diagnosis import Evidence, EvidenceKind, MissingEvidence
from devagent.review import (
    CodeReviewReport,
    CodeReviewServiceError,
    CodeReviewServiceErrorCode,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)

client = TestClient(app)


def make_report(
    *,
    status: ReviewStatus = ReviewStatus.REVIEWED,
) -> CodeReviewReport:
    if status == ReviewStatus.INSUFFICIENT_EVIDENCE:
        return CodeReviewReport(
            review_id="review-001",
            base_ref="main",
            head_ref="feature/payment",
            status=status,
            summary="缺少可用的代码差异。",
            findings=[],
            evidence=[],
            missing_evidence=[
                MissingEvidence(
                    needed="merge-base diff",
                    reason="无法解析目标分支",
                    suggested_tool="git_compare",
                )
            ],
        )

    evidence = Evidence(
        evidence_id="E1",
        kind=EvidenceKind.GIT_DIFF,
        tool_name="git_compare",
        source="b" * 40,
        locator="path=src/payment.py;line=18;side=head",
        excerpt="+ timeout = max(3, expected_seconds)",
    )
    return CodeReviewReport(
        review_id="review-001",
        base_ref="main",
        head_ref="feature/payment",
        status=status,
        summary="发现一个大文件上传超时风险。",
        findings=[
            ReviewFinding(
                finding_id="R1",
                severity=ReviewSeverity.HIGH,
                category=ReviewCategory.CORRECTNESS,
                title="上传超时下限覆盖动态计算",
                description="大文件上传仍可能在传输完成前超时。",
                file_path="src/payment.py",
                line_start=18,
                side=ReviewLineSide.HEAD,
                evidence_ids=["E1"],
                suggestion="保留按文件大小计算出的动态超时。",
                verification_steps=["运行大文件上传参数化测试"],
            )
        ],
        evidence=[evidence],
    )


class StubReviewService:
    def __init__(self, report: CodeReviewReport) -> None:
        self.report = report
        self.calls: list[dict[str, Any]] = []

    def review(self, **kwargs: Any) -> CodeReviewReport:
        self.calls.append(kwargs)
        return self.report


class FailingReviewService:
    def __init__(self, error_code: CodeReviewServiceErrorCode) -> None:
        self.error_code = error_code

    def review(self, **kwargs: Any) -> CodeReviewReport:
        raise CodeReviewServiceError(
            code=self.error_code,
            message="固定脱敏错误",
        )


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_review_code_returns_complete_report() -> None:
    report = make_report()
    service = StubReviewService(report)
    app.dependency_overrides[get_code_review_service] = lambda: service

    response = client.post(
        "/api/v1/reviews/code",
        json={
            "base_ref": "main",
            "head_ref": "feature/payment",
            "workspace": "examples/sample_repo",
        },
    )

    assert response.status_code == 200
    assert CodeReviewReport.model_validate(response.json()) == report
    assert service.calls == [
        {
            "base_ref": "main",
            "head_ref": "feature/payment",
            "workspace": "examples/sample_repo",
        }
    ]


def test_review_code_returns_insufficient_evidence_as_success() -> None:
    report = make_report(status=ReviewStatus.INSUFFICIENT_EVIDENCE)
    service = StubReviewService(report)
    app.dependency_overrides[get_code_review_service] = lambda: service

    response = client.post(
        "/api/v1/reviews/code",
        json={"base_ref": "main", "head_ref": "feature/payment"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["missing_evidence"]


@pytest.mark.parametrize(
    "payload",
    [
        {"head_ref": "feature/payment"},
        {"base_ref": "main"},
        {"base_ref": "", "head_ref": "feature/payment"},
        {"base_ref": " main", "head_ref": "feature/payment"},
        {"base_ref": "main", "head_ref": "feature/payment "},
        {"base_ref": "main", "head_ref": "main"},
        {"base_ref": "main", "head_ref": "feature/payment", "workspace": ""},
        {"base_ref": "main", "head_ref": "feature/payment", "unknown": True},
        {"base_ref": "x" * 256, "head_ref": "feature/payment"},
        {"base_ref": "main", "head_ref": "feature/payment", "workspace": "x" * 2001},
    ],
)
def test_review_code_rejects_invalid_payload_before_service(
    payload: dict[str, object],
) -> None:
    service = StubReviewService(make_report())
    app.dependency_overrides[get_code_review_service] = lambda: service

    response = client.post("/api/v1/reviews/code", json=payload)

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        (CodeReviewServiceErrorCode.INVALID_REQUEST, 400),
        (CodeReviewServiceErrorCode.EVIDENCE_COLLECTION_FAILED, 502),
        (CodeReviewServiceErrorCode.LLM_CALL_FAILED, 502),
        (CodeReviewServiceErrorCode.UNEXPECTED_LLM_RESPONSE, 502),
        (CodeReviewServiceErrorCode.EMPTY_LLM_RESPONSE, 502),
        (CodeReviewServiceErrorCode.INVALID_REPORT, 502),
        (CodeReviewServiceErrorCode.REPORT_MISMATCH, 502),
        (CodeReviewServiceErrorCode.CONFIGURATION_ERROR, 503),
    ],
)
def test_review_code_maps_structured_service_error(
    error_code: CodeReviewServiceErrorCode,
    expected_status: int,
) -> None:
    app.dependency_overrides[get_code_review_service] = lambda: FailingReviewService(
        error_code
    )

    response = client.post(
        "/api/v1/reviews/code",
        json={"base_ref": "main", "head_ref": "feature/payment"},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == {
        "code": error_code.value,
        "message": "固定脱敏错误",
    }


def test_create_review_llm_client_enables_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}

    class FakeOpenAICompatibleLLMClient:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

    monkeypatch.setattr("devagent.api.routes.reviews.load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(
        "devagent.api.routes.reviews.OpenAICompatibleLLMClient",
        FakeOpenAICompatibleLLMClient,
    )
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "review-key")
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "review-model")
    monkeypatch.setenv("DEVAGENT_LLM_BASE_URL", "https://example.test/v1")

    create_review_llm_client()

    assert created == {
        "api_key": "review-key",
        "model": "review-model",
        "base_url": "https://example.test/v1",
        "response_format": {"type": "json_object"},
    }


def test_create_review_llm_client_falls_back_to_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}

    class FakeOpenAICompatibleLLMClient:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

    monkeypatch.setattr("devagent.api.routes.reviews.load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(
        "devagent.api.routes.reviews.OpenAICompatibleLLMClient",
        FakeOpenAICompatibleLLMClient,
    )
    monkeypatch.delenv("DEVAGENT_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "review-model")
    monkeypatch.delenv("DEVAGENT_LLM_BASE_URL", raising=False)

    create_review_llm_client()

    assert created["api_key"] == "fallback-key"
    assert created["base_url"] is None


@pytest.mark.parametrize("missing", ["api_key", "model"])
def test_get_code_review_service_maps_missing_config_to_503(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    monkeypatch.setattr("devagent.api.routes.reviews.load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "secret-review-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "review-model")
    if missing == "api_key":
        monkeypatch.delenv("DEVAGENT_LLM_API_KEY", raising=False)
    else:
        monkeypatch.delenv("DEVAGENT_LLM_MODEL", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        get_code_review_service()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "configuration_error"
    assert "secret-review-key" not in str(exc_info.value.detail)


def test_openapi_contains_code_review_contract() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/api/v1/reviews/code"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CodeReviewRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/CodeReviewReport"}


def test_openapi_code_review_example_contains_only_business_fields() -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"][
        "CodeReviewRequest"
    ]

    assert schema["examples"][0] == {
        "base_ref": "main",
        "head_ref": "feature/payment",
        "workspace": "examples/sample_repo",
    }
    assert set(schema["properties"]) == {"base_ref", "head_ref", "workspace"}
