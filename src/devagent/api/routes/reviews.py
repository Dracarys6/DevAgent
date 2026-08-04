import os
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status

from devagent.api.schemas import CodeReviewRequest
from devagent.llm import LLMClient, create_openai_llm_client
from devagent.review.models import CodeReviewReport
from devagent.review.service import (
    CodeReviewService,
    CodeReviewServiceError,
    CodeReviewServiceErrorCode,
    LocalCodeReviewEvidenceCollector,
)

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])
CODE_REVIEW_MAX_TOKENS = 8_192


def create_review_llm_client() -> LLMClient:
    """根据服务端环境变量创建代码评审专用 LLM 客户端。"""
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    api_key = os.getenv("DEVAGENT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("DEVAGENT_LLM_MODEL")
    base_url = os.getenv("DEVAGENT_LLM_BASE_URL")
    api_mode = os.getenv("DEVAGENT_LLM_API_MODE", "chat_completions")
    reasoning_effort = os.getenv("DEVAGENT_LLM_REASONING_EFFORT") or None

    if not api_key:
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.CONFIGURATION_ERROR,
            message="代码评审服务缺少 LLM API Key",
        )
    if not model:
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.CONFIGURATION_ERROR,
            message="代码评审服务缺少 LLM 模型名称",
        )

    try:
        return create_openai_llm_client(
            api_key=api_key,
            model=model,
            base_url=base_url,
            api_mode=api_mode,
            reasoning_effort=reasoning_effort,
            response_format={"type": "json_object"},
            max_tokens=CODE_REVIEW_MAX_TOKENS,
        )
    except ValueError as exc:
        raise CodeReviewServiceError(
            code=CodeReviewServiceErrorCode.CONFIGURATION_ERROR,
            message=f"代码评审服务 LLM 配置无效: {exc}",
        ) from exc


def get_code_review_service() -> CodeReviewService:
    try:
        llm_client = create_review_llm_client()
    except CodeReviewServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code.value, "message": exc.message},
        ) from exc
    return CodeReviewService(
        llm_client=llm_client, evidence_collector=LocalCodeReviewEvidenceCollector()
    )


@router.post("/code", response_model=CodeReviewReport)
def review_code(
    request: CodeReviewRequest,
    service: Annotated[CodeReviewService, Depends(get_code_review_service)],
) -> CodeReviewReport:
    try:
        return service.review(
            base_ref=request.base_ref,
            head_ref=request.head_ref,
            workspace=request.workspace,
        )
    except CodeReviewServiceError as exc:
        raise HTTPException(
            status_code=_service_error_status(exc.code),
            detail={"code": exc.code.value, "message": exc.message},
        ) from exc


def _service_error_status(error_code: CodeReviewServiceErrorCode) -> int:
    if error_code == CodeReviewServiceErrorCode.INVALID_REQUEST:
        return status.HTTP_400_BAD_REQUEST
    if error_code == CodeReviewServiceErrorCode.CONFIGURATION_ERROR:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return status.HTTP_502_BAD_GATEWAY
