from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes.diagnoses import (
    create_diagnosis_llm_client,
    get_diagnosis_service,
)
from devagent.diagnosis import (
    Confidence,
    DiagnosisReport,
    DiagnosisScenario,
    DiagnosisServiceError,
    DiagnosisServiceErrorCode,
    DiagnosisStatus,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
)

client = TestClient(app)


def make_report() -> DiagnosisReport:
    evidence = Evidence(
        evidence_id="E1",
        kind=EvidenceKind.CI_RESULT,
        tool_name="get_ci_result",
        source="pipeline-1001",
        locator="commit_id=abc123",
        excerpt='{"status":"failed"}',
    )
    return DiagnosisReport(
        report_id="report-ci-001",
        target="abc123",
        status=DiagnosisStatus.DIAGNOSED,
        summary="CI 测试失败。",
        findings=[
            Finding(
                kind=FindingKind.SYMPTOM,
                statement="单元测试失败。",
                confidence=Confidence.CONFIRMED,
                evidence_ids=["E1"],
            )
        ],
        evidence=[evidence],
    )


def make_log_report() -> DiagnosisReport:
    evidence = Evidence(
        evidence_id="E1",
        kind=EvidenceKind.LOG,
        tool_name="search_log",
        source="task_001",
        locator="first_anomaly_sequence_id=3",
        excerpt='{"message":"UploadTimeoutError"}',
    )
    return DiagnosisReport(
        report_id="report-log-001",
        scenario=DiagnosisScenario.LOG_FAILURE,
        target="task_001",
        status=DiagnosisStatus.DIAGNOSED,
        summary="首个异常是 UploadTimeoutError。",
        findings=[
            Finding(
                kind=FindingKind.SYMPTOM,
                statement="上传首先发生超时。",
                confidence=Confidence.CONFIRMED,
                evidence_ids=["E1"],
            )
        ],
        evidence=[evidence],
    )


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_diagnose_ci_returns_validated_report():
    class StubService:
        def diagnose_ci(self, *, commit_id: str, workspace: str) -> DiagnosisReport:
            assert commit_id == "abc123"
            assert workspace == "examples/sample_repo"
            return make_report()

    app.dependency_overrides[get_diagnosis_service] = lambda: StubService()

    response = client.post(
        "/api/v1/diagnoses/ci",
        json={
            "commit_id": "abc123",
            "workspace": "examples/sample_repo",
        },
    )

    assert response.status_code == 200
    assert DiagnosisReport.model_validate(response.json()) == make_report()


@pytest.mark.parametrize(
    "commit_id",
    ["short", "not-hex-value", "a" * 65],
)
def test_diagnose_ci_rejects_invalid_commit_id(commit_id: str):
    response = client.post(
        "/api/v1/diagnoses/ci",
        json={"commit_id": commit_id},
    )

    assert response.status_code == 422


def test_diagnose_ci_maps_service_error_to_bad_gateway():
    class FailingService:
        def diagnose_ci(self, *, commit_id: str, workspace: str) -> DiagnosisReport:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.INVALID_REPORT,
                message="模型返回的诊断报告不符合契约",
            )

    app.dependency_overrides[get_diagnosis_service] = lambda: FailingService()

    response = client.post(
        "/api/v1/diagnoses/ci",
        json={"commit_id": "abc123"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_report"


def test_diagnose_log_returns_validated_report():
    class StubService:
        def diagnose_log(
            self, *, task_id: str, data_dir: str, workspace: str
        ) -> DiagnosisReport:
            assert task_id == "task_001"
            assert data_dir == "examples/sample_logs"
            assert workspace == "."
            return make_log_report()

    app.dependency_overrides[get_diagnosis_service] = lambda: StubService()

    response = client.post(
        "/api/v1/diagnoses/log",
        json={"task_id": "task_001", "data_dir": "examples/sample_logs"},
    )

    assert response.status_code == 200
    assert DiagnosisReport.model_validate(response.json()) == make_log_report()


@pytest.mark.parametrize("task_id", ["", "task/001", " task_001", "a" * 129])
def test_diagnose_log_rejects_invalid_task_id(task_id: str):
    response = client.post(
        "/api/v1/diagnoses/log",
        json={"task_id": task_id},
    )

    assert response.status_code == 422


def test_diagnose_log_maps_service_error_to_bad_gateway():
    class FailingService:
        def diagnose_log(
            self, *, task_id: str, data_dir: str, workspace: str
        ) -> DiagnosisReport:
            raise DiagnosisServiceError(
                code=DiagnosisServiceErrorCode.EVIDENCE_COLLECTION_FAILED,
                message="日志工具返回了无法标准化的数据",
            )

    app.dependency_overrides[get_diagnosis_service] = lambda: FailingService()

    response = client.post(
        "/api/v1/diagnoses/log",
        json={"task_id": "task_001"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "evidence_collection_failed"


def test_openapi_schema_contains_ci_diagnosis_path():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/diagnoses/ci" in response.json()["paths"]
    assert "/api/v1/diagnoses/log" in response.json()["paths"]


def test_create_diagnosis_llm_client_enables_json_output(
    monkeypatch,
):
    created: dict[str, object] = {}

    class FakeOpenAICompatibleLLMClient:
        def __init__(self, **kwargs) -> None:
            created.update(kwargs)

    monkeypatch.setattr(
        "devagent.api.routes.diagnoses.load_dotenv",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "devagent.api.routes.diagnoses.create_openai_llm_client",
        lambda **kwargs: FakeOpenAICompatibleLLMClient(**kwargs),
    )
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("DEVAGENT_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEVAGENT_LLM_API_MODE", "chat_completions")
    monkeypatch.delenv("DEVAGENT_LLM_REASONING_EFFORT", raising=False)

    create_diagnosis_llm_client()

    assert created["response_format"] == {"type": "json_object"}
    assert created["api_mode"] == "chat_completions"
    assert created["reasoning_effort"] is None


def test_create_diagnosis_llm_client_rejects_missing_api_key(monkeypatch):
    monkeypatch.setattr(
        "devagent.api.routes.diagnoses.load_dotenv",
        lambda **kwargs: None,
    )
    monkeypatch.delenv("DEVAGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "deepseek-v4-pro")

    with pytest.raises(DiagnosisServiceError) as exc_info:
        create_diagnosis_llm_client()

    assert exc_info.value.code == DiagnosisServiceErrorCode.CONFIGURATION_ERROR


def test_create_diagnosis_llm_client_rejects_invalid_api_mode(monkeypatch):
    monkeypatch.setattr(
        "devagent.api.routes.diagnoses.load_dotenv",
        lambda **kwargs: None,
    )
    monkeypatch.setenv("DEVAGENT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("DEVAGENT_LLM_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("DEVAGENT_LLM_API_MODE", "invalid")

    with pytest.raises(DiagnosisServiceError) as exc_info:
        create_diagnosis_llm_client()

    assert exc_info.value.code == DiagnosisServiceErrorCode.CONFIGURATION_ERROR
    assert "API 模式" in exc_info.value.message


def test_openapi_ci_diagnosis_example_uses_valid_commit_id():
    response = client.get("/openapi.json")

    schema = response.json()["components"]["schemas"]["CIDiagnosisRequest"]
    example = schema["examples"][0]

    assert example == {
        "commit_id": "7229c86",
        "workspace": "examples/sample_repo",
    }


def test_openapi_log_diagnosis_example_uses_real_fixture():
    response = client.get("/openapi.json")

    schema = response.json()["components"]["schemas"]["LogDiagnosisRequest"]

    assert schema["examples"][0] == {
        "task_id": "task_001",
        "data_dir": "examples/sample_logs",
        "workspace": "examples/sample_repo",
    }
