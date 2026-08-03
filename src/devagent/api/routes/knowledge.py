from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from devagent.api.schemas import KnowledgeSearchRequest
from devagent.memory import RetrievalResult
from devagent.tools.knowledge_service import WorkspaceKnowledgeService
from devagent.tools.knowledge_tools import (
    DEFAULT_KNOWLEDGE_SERVICE,
    KnowledgeRetrieveError,
    knowledge_retrieve,
)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


def get_workspace_knowledge_service() -> WorkspaceKnowledgeService:
    return DEFAULT_KNOWLEDGE_SERVICE


@router.post("/search", response_model=RetrievalResult)
def search_workspace_knowledge(
    request: KnowledgeSearchRequest,
    service: Annotated[
        WorkspaceKnowledgeService,
        Depends(get_workspace_knowledge_service),
    ],
) -> RetrievalResult:
    """在受控工作区中返回确定性的 Top-K 证据片段。"""
    try:
        return knowledge_retrieve(
            query=request.query,
            workspace=request.workspace,
            top_k=request.top_k,
            service=service,
        )
    except KnowledgeRetrieveError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "knowledge_retrieve_error", "message": str(exc)},
        ) from exc
    except PermissionError as exc:
        # ! 不向浏览器泄露服务端权限异常中的绝对路径等细节。
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "knowledge_access_denied",
                "message": "工作区或知识文件不可读取",
            },
        ) from exc
