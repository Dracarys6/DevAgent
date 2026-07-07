"""DevAgent HTTP Router。"""

from .tasks import router as tasks_router
from .permissions import router as permissions_router
from .stream import router as stream_router

__all__ = ["tasks_router", "permissions_router", "stream_router"]
