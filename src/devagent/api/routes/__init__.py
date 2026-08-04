"""DevAgent HTTP Router。"""

from .diagnoses import router as diagnoses_router
from .git_commits import router as git_commits_router
from .github_webhooks import router as github_webhooks_router
from .knowledge import router as knowledge_router
from .permissions import router as permissions_router
from .reviews import router as reviews_router
from .stream import router as stream_router
from .tasks import router as tasks_router
from .traces import router as traces_router
from .websocket import router as websocket_router

__all__ = [
    "diagnoses_router",
    "git_commits_router",
    "github_webhooks_router",
    "knowledge_router",
    "permissions_router",
    "reviews_router",
    "stream_router",
    "tasks_router",
    "traces_router",
    "websocket_router",
]
