"""DevAgent HTTP Router。"""

from .tasks import router as tasks_router
from .permissions import router as permissions_router
from .stream import router as stream_router
from .websocket import router as websocket_router
from .traces import router as traces_router

__all__ = [
    "tasks_router",
    "permissions_router",
    "stream_router",
    "websocket_router",
    "traces_router",
]
