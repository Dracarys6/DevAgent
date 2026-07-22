from enum import Enum
import threading
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from devagent.review import (
    CodeReviewReport,
    PullRequestLocator,
    PullRequestSource,
    ReviewPublisher,
    WebhookDeliveryStore,
)


class CodeReviewRunner(Protocol):
    def review(
        self,
        *,
        base_ref: str,
        head_ref: str,
        workspace: str,
    ) -> CodeReviewReport: ...


class GitHubReviewTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GitHubReviewTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    delivery_id: str = Field(min_length=1, max_length=255)
    locator: PullRequestLocator
    status: GitHubReviewTaskStatus
    report_id: str | None = None
    error_message: str | None = None


class GitHubReviewTaskManager:
    """编排一次 GitHub PR 快照、代码审查和建议发布。"""

    def __init__(
        self,
        *,
        source: PullRequestSource,
        service: CodeReviewRunner,
        publisher: ReviewPublisher,
        delivery_store: WebhookDeliveryStore,
    ) -> None:
        self._source = source
        self._service = service
        self._publisher = publisher
        self._delivery_store = delivery_store
        self._tasks: dict[str, GitHubReviewTask] = {}
        self._task_ids_by_delivery: dict[str, str] = {}
        self._lock = threading.Lock()

    def create_task(
        self,
        *,
        delivery_id: str,
        locator: PullRequestLocator,
    ) -> GitHubReviewTask:
        with self._lock:
            if delivery_id in self._task_ids_by_delivery:
                raise ValueError("delivery_id 已创建审查任务")
            task = GitHubReviewTask(
                task_id=str(uuid4()),
                delivery_id=delivery_id,
                locator=locator,
                status=GitHubReviewTaskStatus.PENDING,
            )
            self._tasks[task.task_id] = task
            self._task_ids_by_delivery[delivery_id] = task.task_id
            return task.model_copy(deep=True)

    def get_task(self, task_id: str) -> GitHubReviewTask:
        with self._lock:
            try:
                return self._tasks[task_id].model_copy(deep=True)
            except KeyError as exc:
                raise KeyError("GitHub 审查任务不存在") from exc

    def run_task(self, task_id: str) -> GitHubReviewTask:
        with self._lock:
            try:
                task = self._tasks[task_id]
            except KeyError as exc:
                raise KeyError("GitHub 审查任务不存在") from exc
            if task.status != GitHubReviewTaskStatus.PENDING:
                return task.model_copy(deep=True)
            task.status = GitHubReviewTaskStatus.RUNNING

        try:
            snapshot = self._source.get_pull_request(task.locator)
            report = self._service.review(
                base_ref=snapshot.base_ref,
                head_ref=snapshot.head_ref,
                workspace=snapshot.workspace,
            )
            task.report_id = report.review_id
            self._publisher.publish(pull_request=snapshot, report=report)
            self._delivery_store.mark_completed(task.delivery_id)
        except Exception:
            # ! 外部异常可能包含 token 或响应正文，任务只保存固定脱敏信息。
            self._delivery_store.release(task.delivery_id)
            with self._lock:
                task.status = GitHubReviewTaskStatus.FAILED
                task.error_message = "GitHub Pull Request 审查任务执行失败"
                if self._task_ids_by_delivery.get(task.delivery_id) == task.task_id:
                    # * 失败任务保留审计记录，但释放活动映射以允许 GitHub redelivery。
                    self._task_ids_by_delivery.pop(task.delivery_id)
                return task.model_copy(deep=True)

        with self._lock:
            task.status = GitHubReviewTaskStatus.COMPLETED
            task.error_message = None
            return task.model_copy(deep=True)
