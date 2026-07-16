import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status

from devagent.api.schemas import CIDiagnosisRequest
from devagent.diagnosis import (
    DiagnosisReport,
    DiagnosisService,
    DiagnosisServiceError,
    DiagnosisServiceErrorCode,
    LocalCIEvidenceCollector,
)
from devagent.llm import LLMClient, OpenAICompatibleLLMClient

router = APIRouter(prefix="/api/v1/diagnoses", tags=["diagnoses"])


def create_diagnosis_llm_client() -> LLMClient:
    """根据服务端环境变量创建诊断专用 LLM 客户端。"""
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    api_key = os.getenv("DEVAGENT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("DEVAGENT_LLM_MODEL")
    base_url = os.getenv("DEVAGENT_LLM_BASE_URL")

    if not api_key:
        raise DiagnosisServiceError(
            code=DiagnosisServiceErrorCode.CONFIGURATION_ERROR,
            message="诊断服务缺少 LLM API Key",
        )
    if not model:
        raise DiagnosisServiceError(
            code=DiagnosisServiceErrorCode.CONFIGURATION_ERROR,
            message="诊断服务缺少 LLM 模型名称",
        )

    return OpenAICompatibleLLMClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        response_format={"type": "json_object"},
    )


def get_diagnosis_service() -> DiagnosisService:
    try:
        llm_client = create_diagnosis_llm_client()
    except DiagnosisServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code.value, "message": exc.message},
        ) from exc

    return DiagnosisService(
        llm_client=llm_client,
        ci_evidence_collector=LocalCIEvidenceCollector(),
    )


@router.post("/ci", response_model=DiagnosisReport)
def diagnose_ci(
    request: CIDiagnosisRequest,
    service: DiagnosisService = Depends(get_diagnosis_service),
) -> DiagnosisReport:
    try:
        return service.diagnose_ci(
            commit_id=request.commit_id,
            workspace=request.workspace,
        )
    except DiagnosisServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code.value, "message": exc.message},
        ) from exc
