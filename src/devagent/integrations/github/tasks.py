import threading
from dataclasses import dataclass
from enum import Enum
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

from .publication_store import GitHubReviewPublicationStore, PublicationStatus


class CodeReviewRunner(Protocol):
    def review(
        self,
        *,
        base_ref: str,
        head_ref: str,
        workspace: str,
    ) -> CodeReviewReport: ...


@dataclass(frozen=True)
class GitHubReviewPorts:
    source: PullRequestSource
    publisher: ReviewPublisher


class GitHubReviewPortFactory(Protocol):
    def create(self, installation_id: int) -> GitHubReviewPorts: ...


class FixedGitHubReviewPortFactory:
    """保留 Day48 Fake 和本地测试所需的固定 ports。"""

    def __init__(
        self,
        *,
        source: PullRequestSource,
        publisher: ReviewPublisher,
    ) -> None:
        self._ports = GitHubReviewPorts(source=source, publisher=publisher)

    def create(self, installation_id: int) -> GitHubReviewPorts:
        if isinstance(installation_id, bool) or installation_id < 1:
            raise ValueError("installation_id 必须大于或等于 1")
        return self._ports


class GitHubReviewTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GitHubReviewTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    delivery_id: str = Field(min_length=1, max_length=255)
    installation_id: int = Field(ge=1)
    locator: PullRequestLocator
    status: GitHubReviewTaskStatus
    report_id: str | None = None
    error_message: str | None = None


class GitHubReviewTaskManager:
    """编排一次 GitHub PR 快照、代码审查和建议发布。"""

    def __init__(
        self,
        *,
        service: CodeReviewRunner,
        delivery_store: WebhookDeliveryStore,
        port_factory: GitHubReviewPortFactory | None = None,
        source: PullRequestSource | None = None,
        publisher: ReviewPublisher | None = None,
        publication_store: GitHubReviewPublicationStore | None = None,
    ) -> None:
        if port_factory is None:
            if source is None or publisher is None:
                raise ValueError("必须提供 port_factory 或完整的 source / publisher")
            port_factory = FixedGitHubReviewPortFactory(
                source=source,
                publisher=publisher,
            )
        elif source is not None or publisher is not None:
            raise ValueError("port_factory 不能与 source / publisher 同时提供")
        self._port_factory = port_factory
        self._service = service
        self._delivery_store = delivery_store
        self._publication_store = publication_store
        self._tasks: dict[str, GitHubReviewTask] = {}
        self._task_ids_by_delivery: dict[str, str] = {}
        self._lock = threading.Lock()

    def create_task(
        self,
        *,
        delivery_id: str,
        installation_id: int,
        locator: PullRequestLocator,
    ) -> GitHubReviewTask:
        with self._lock:
            if delivery_id in self._task_ids_by_delivery:
                raise ValueError("delivery_id 已创建审查任务")
            task = GitHubReviewTask(
                task_id=str(uuid4()),
                delivery_id=delivery_id,
                installation_id=installation_id,
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
            ports = self._port_factory.create(task.installation_id)
            snapshot = ports.source.get_pull_request(task.locator)
            report = self._service.review(
                base_ref=snapshot.base_ref,
                head_ref=snapshot.head_ref,
                workspace=snapshot.workspace,
            )
            task.report_id = report.review_id
            publication = None
            if self._publication_store is not None:
                claim = self._publication_store.claim(
                    delivery_id=task.delivery_id,
                    repository_full_name=snapshot.locator.repository,
                    pull_number=snapshot.locator.number,
                    head_sha=snapshot.head_sha,
                )
                publication = claim.publication
                if not claim.acquired:
                    if publication.status == PublicationStatus.COMPLETED:
                        self._delivery_store.mark_completed(task.delivery_id)
                        with self._lock:
                            task.status = GitHubReviewTaskStatus.COMPLETED
                            task.error_message = None
                            return task.model_copy(deep=True)
                    raise RuntimeError("GitHub review publication 正在处理中")
            try:
                publish_result = ports.publisher.publish(
                    pull_request=snapshot,
                    report=report,
                )
            except Exception:
                if publication is not None and self._publication_store is not None:
                    self._publication_store.mark_failed(publication.publication_id)
                raise
            if publication is not None and self._publication_store is not None:
                self._publication_store.mark_completed(
                    publication.publication_id,
                    publish_result.external_comment_id,
                )
            self._delivery_store.mark_completed(task.delivery_id)
        except Exception:  # noqa: BLE001
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
