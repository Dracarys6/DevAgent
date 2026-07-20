from .models import (
    CodeReviewInput,
    CodeReviewReport,
    ReviewCategory,
    ReviewFinding,
    ReviewLineSide,
    ReviewSeverity,
    ReviewStatus,
)
from .ports import (
    PullRequestLocator,
    PullRequestSnapshot,
    PullRequestSource,
    ReviewPublisher,
    ReviewPublishResult,
    WebhookDeliveryStore,
)

__all__ = [
    "CodeReviewInput",
    "CodeReviewReport",
    "ReviewCategory",
    "ReviewFinding",
    "ReviewLineSide",
    "ReviewSeverity",
    "ReviewStatus",
    "PullRequestLocator",
    "PullRequestSnapshot",
    "PullRequestSource",
    "ReviewPublisher",
    "ReviewPublishResult",
    "WebhookDeliveryStore",
    "CodeReviewEvidenceCollector",
    "CodeReviewService",
    "CodeReviewServiceError",
    "CodeReviewServiceErrorCode",
    "LocalCodeReviewEvidenceCollector",
    "ReviewIdFactory",
]


def __getattr__(name: str):
    """按需加载服务类型，避免审查模型与 Prompt 包之间形成循环导入。"""
    service_exports = {
        "CodeReviewEvidenceCollector",
        "CodeReviewService",
        "CodeReviewServiceError",
        "CodeReviewServiceErrorCode",
        "LocalCodeReviewEvidenceCollector",
        "ReviewIdFactory",
    }
    if name not in service_exports:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import service

    return getattr(service, name)
