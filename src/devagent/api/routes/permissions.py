from fastapi import APIRouter, BackgroundTasks, HTTPException

from devagent.api.schemas import (
    PermissionRequestListResponse,
    PermissionRequestResponse,
    PermissionResolveRequest,
)
from devagent.permission import (
    InvalidPermissionTransitionError,
    PermissionRequest,
    PermissionRequestNotFoundError,
)

from .tasks import permission_manager, task_manager

router = APIRouter(prefix="/api/v1/permissions", tags=["permissions"])


@router.get("/pending", response_model=PermissionRequestListResponse)
def get_pending_requests() -> PermissionRequestListResponse:
    """查询所有处于 pending 状态的权限请求。"""
    pending_requests = permission_manager.list_pending()
    return PermissionRequestListResponse(
        requests=[_request_to_response(request) for request in pending_requests]
    )


def _request_to_response(request: PermissionRequest) -> PermissionRequestResponse:
    return PermissionRequestResponse(**request.model_dump())


@router.get("/{request_id}", response_model=PermissionRequestResponse)
def get_request(request_id: str) -> PermissionRequestResponse:
    try:
        request = permission_manager.get_request(request_id=request_id)
    except PermissionRequestNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    return _request_to_response(request)


@router.post("/{request_id}/resolve", response_model=PermissionRequestResponse)
def resolve_request(
    request_id: str,
    request: PermissionResolveRequest,
    background_tasks: BackgroundTasks,
) -> PermissionRequestResponse:
    try:
        resolved_request = permission_manager.resolve(
            request_id=request_id,
            decision=request.decision,
            decision_reason=request.decision_reason,
        )
        if task_manager.can_resume_permission(request_id):
            background_tasks.add_task(task_manager.resume_task, request_id)
    except PermissionRequestNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except InvalidPermissionTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    return _request_to_response(resolved_request)
