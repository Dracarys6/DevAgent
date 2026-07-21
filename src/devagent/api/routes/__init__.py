"""DevAgent HTTP Router。"""

from .tasks import router as tasks_router
from .permissions import router as permissions_router
from .stream import router as stream_router
from .websocket import router as websocket_router
from .traces import router as traces_router
from .diagnoses import router as diagnoses_router
from .reviews import router as reviews_router
from .git_commits import router as git_commits_router

__all__ = [
    "tasks_router",
    "permissions_router",
    "stream_router",
    "websocket_router",
    "traces_router",
    "diagnoses_router",
    "reviews_router",
    "git_commits_router",
]
