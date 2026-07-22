import json
import os
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from pydantic import ValidationError

from devagent.integrations.github import (
    DeliveryStoreCapacityError,
    GitHubPullRequestWebhook,
    GitHubReviewTaskManager,
    GitHubSignatureError,
    GitHubWebhookResponse,
    GitHubWebhookStatus,
    InMemoryWebhookDeliveryStore,
    verify_github_signature,
)
from devagent.review import PullRequestLocator, WebhookDeliveryStore

router = APIRouter(
    prefix="/api/v1/integrations/github",
    tags=["github-integrations"],
)

TRIGGER_ACTIONS = frozenset(
    {"opened", "reopened", "synchronize", "ready_for_review"}
)

_delivery_store = InMemoryWebhookDeliveryStore()
_review_task_manager: GitHubReviewTaskManager | None = None


def get_github_webhook_secret() -> str:
    """从服务端环境读取 webhook secret，不接受请求级覆盖。"""
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    secret = os.getenv("DEVAGENT_GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "github_webhook_not_configured",
                "message": "GitHub webhook secret 未配置",
            },
        )
    return secret


def get_delivery_store() -> WebhookDeliveryStore:
    return _delivery_store


def get_github_review_task_manager() -> GitHubReviewTaskManager | None:
    """返回应用装配的任务管理器；测试通过 dependency_overrides 注入 Fake。"""
    return _review_task_manager


@router.post(
    "/webhooks",
    response_model=GitHubWebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Annotated[
        str | None,
        Header(alias="X-Hub-Signature-256"),
    ] = None,
    x_github_event: Annotated[
        str | None,
        Header(alias="X-GitHub-Event"),
    ] = None,
    x_github_delivery: Annotated[
        str | None,
        Header(alias="X-GitHub-Delivery"),
    ] = None,
    secret: str = Depends(get_github_webhook_secret),
    delivery_store: WebhookDeliveryStore = Depends(get_delivery_store),
    task_manager: GitHubReviewTaskManager | None = Depends(
        get_github_review_task_manager
    ),
) -> GitHubWebhookResponse:
    body = await request.body()
    try:
        verify_github_signature(
            body=body,
            signature_header=x_hub_signature_256,
            secret=secret,
        )
    except GitHubSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_github_signature", "message": str(exc)},
        ) from exc

    if x_github_event != "pull_request":
        return GitHubWebhookResponse(
            delivery_id=_ignored_delivery_id(x_github_delivery),
            status=GitHubWebhookStatus.IGNORED,
        )

    payload = _parse_payload(body)
    if payload.action not in TRIGGER_ACTIONS:
        return GitHubWebhookResponse(
            delivery_id=_ignored_delivery_id(x_github_delivery),
            status=GitHubWebhookStatus.IGNORED,
        )

    delivery_id = _require_delivery_id(x_github_delivery)
    if task_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "github_review_not_configured",
                "message": "GitHub 审查任务管理器未配置",
            },
        )

    try:
        claimed = delivery_store.claim(delivery_id)
    except DeliveryStoreCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "github_delivery_store_full",
                "message": "GitHub delivery store 已达到容量上限",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_delivery_id", "message": str(exc)},
        ) from exc

    if not claimed:
        return GitHubWebhookResponse(
            delivery_id=delivery_id,
            status=GitHubWebhookStatus.DUPLICATE,
        )

    try:
        task = task_manager.create_task(
            delivery_id=delivery_id,
            locator=PullRequestLocator(
                platform="github",
                repository=payload.repository.full_name,
                number=payload.pull_request.number,
            ),
        )
        background_tasks.add_task(task_manager.run_task, task.task_id)
    except Exception as exc:
        delivery_store.release(delivery_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "github_review_scheduling_failed",
                "message": "GitHub 审查任务调度失败",
            },
        ) from exc

    return GitHubWebhookResponse(
        delivery_id=delivery_id,
        status=GitHubWebhookStatus.ACCEPTED,
        task_id=task.task_id,
    )


def _parse_payload(body: bytes) -> GitHubPullRequestWebhook:
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_github_payload",
                "message": "GitHub webhook body 不是合法 JSON",
            },
        ) from exc
    try:
        return GitHubPullRequestWebhook.model_validate(decoded)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_github_payload",
                "message": "GitHub pull_request payload 缺少必要字段",
            },
        ) from exc


def _require_delivery_id(delivery_id: str | None) -> str:
    if not delivery_id or not delivery_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "missing_github_delivery",
                "message": "目标 GitHub webhook 缺少 X-GitHub-Delivery",
            },
        )
    if delivery_id != delivery_id.strip() or len(delivery_id) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_delivery_id",
                "message": "X-GitHub-Delivery 格式无效",
            },
        )
    return delivery_id


def _ignored_delivery_id(delivery_id: str | None) -> str:
    if delivery_id and delivery_id.strip() and len(delivery_id) <= 255:
        return delivery_id.strip()
    return "not-applicable"
