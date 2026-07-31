import os
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status

from devagent.api.schemas import CIDiagnosisRequest, LogDiagnosisRequest
from devagent.diagnosis.models import DiagnosisReport
from devagent.diagnosis.service import (
    DiagnosisService,
    DiagnosisServiceError,
    DiagnosisServiceErrorCode,
    LocalCIEvidenceCollector,
    LocalLogEvidenceCollector,
)
from devagent.llm import LLMClient, create_openai_llm_client

router = APIRouter(prefix="/api/v1/diagnoses", tags=["diagnoses"])


def create_diagnosis_llm_client() -> LLMClient:
    """根据服务端环境变量创建诊断专用 LLM 客户端。"""
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    api_key = os.getenv("DEVAGENT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("DEVAGENT_LLM_MODEL")
    base_url = os.getenv("DEVAGENT_LLM_BASE_URL")
    api_mode = os.getenv("DEVAGENT_LLM_API_MODE", "chat_completions")
    reasoning_effort = os.getenv("DEVAGENT_LLM_REASONING_EFFORT") or None

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

    try:
        return create_openai_llm_client(
            api_key=api_key,
            model=model,
            base_url=base_url,
            api_mode=api_mode,
            reasoning_effort=reasoning_effort,
            response_format={"type": "json_object"},
        )
    except ValueError as exc:
        raise DiagnosisServiceError(
            code=DiagnosisServiceErrorCode.CONFIGURATION_ERROR,
            message=f"诊断服务 LLM 配置无效: {exc}",
        ) from exc


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
        log_evidence_collector=LocalLogEvidenceCollector(),
    )


@router.post("/ci", response_model=DiagnosisReport)
def diagnose_ci(
    request: CIDiagnosisRequest,
    service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
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


@router.post("/log", response_model=DiagnosisReport)
def diagnose_log(
    request: LogDiagnosisRequest,
    service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
) -> DiagnosisReport:
    try:
        return service.diagnose_log(
            task_id=request.task_id,
            data_dir=request.data_dir,
        )
    except DiagnosisServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code.value, "message": exc.message},
        ) from exc
