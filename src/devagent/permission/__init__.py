"""权限管理模块，提供权限请求、决策和策略的相关功能。"""

from devagent.tools.models import RiskLevel

from .factory import PermissionRuntimeComponents, create_permission_runtime
from .manager import InMemoryPermissionManager
from .models import (
    InvalidPermissionTransitionError,
    PermissionDecision,
    PermissionPolicy,
    PermissionRequest,
    PermissionStatus,
)
from .policy_store import (
    InMemoryPermissionPolicyStore,
    PermissionPolicyNotFoundError,
    fingerprint_arguments,
)
from .request_store import (
    InMemoryPermissionRequestStore,
    PermissionRequestNotFoundError,
    PermissionRequestStore,
)
from .sqlite_stores import (
    PermissionPersistenceError,
    SQLitePermissionPolicyStore,
    SQLitePermissionRequestStore,
)

__all__ = [
    "InMemoryPermissionManager",
    "InMemoryPermissionPolicyStore",
    "InMemoryPermissionRequestStore",
    "InvalidPermissionTransitionError",
    "PermissionDecision",
    "PermissionPersistenceError",
    "PermissionPolicy",
    "PermissionPolicyNotFoundError",
    "PermissionRequest",
    "PermissionRequestNotFoundError",
    "PermissionRequestStore",
    "PermissionRuntimeComponents",
    "PermissionStatus",
    "RiskLevel",
    "SQLitePermissionPolicyStore",
    "SQLitePermissionRequestStore",
    "create_permission_runtime",
    "fingerprint_arguments",
]
