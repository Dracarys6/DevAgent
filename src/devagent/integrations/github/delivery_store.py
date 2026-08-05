import sqlite3
import threading
from collections import OrderedDict
from datetime import UTC, datetime
from enum import Enum

from devagent.storage import SQLiteDatabase

DELIVERY_MAX_ENTRIES = 1000


class DeliveryState(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"


class DeliveryStoreCapacityError(RuntimeError):
    pass


class InMemoryWebhookDeliveryStore:
    def __init__(self, max_entries: int = DELIVERY_MAX_ENTRIES) -> None:
        if isinstance(max_entries, bool) or max_entries < 1:
            raise ValueError("max_entries 必须大于或等于 1")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, DeliveryState] = OrderedDict()
        self._lock = threading.Lock()

    def claim(self, delivery_id: str) -> bool:
        normalized_id = _validate_delivery_id(delivery_id)
        with self._lock:
            if normalized_id in self._entries:
                return False
            if len(self._entries) >= self._max_entries:
                self._evict_oldest_completed()
            if len(self._entries) >= self._max_entries:
                raise DeliveryStoreCapacityError("Delivery store 已达到容量上限")
            # * 检查、容量处理与写入必须处于同一个临界区，保证 claim 原子化。
            self._entries[normalized_id] = DeliveryState.PROCESSING
            return True

    def mark_completed(self, delivery_id: str) -> None:
        normalized_id = _validate_delivery_id(delivery_id)
        with self._lock:
            if normalized_id not in self._entries:
                raise KeyError("delivery_id 尚未被 claim")
            self._entries[normalized_id] = DeliveryState.COMPLETED

    def release(self, delivery_id: str) -> None:
        normalized_id = _validate_delivery_id(delivery_id)
        with self._lock:
            if self._entries.get(normalized_id) == DeliveryState.PROCESSING:
                self._entries.pop(normalized_id)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def get_state(self, delivery_id: str) -> DeliveryState | None:
        normalized_id = _validate_delivery_id(delivery_id)
        with self._lock:
            return self._entries.get(normalized_id)

    def _evict_oldest_completed(self) -> None:
        for delivery_id, state in self._entries.items():
            if state == DeliveryState.COMPLETED:
                self._entries.pop(delivery_id)
                return


class SQLiteWebhookDeliveryStore:
    """通过 delivery_id 主键提供跨进程原子 claim。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def claim(self, delivery_id: str) -> bool:
        normalized_id = _validate_delivery_id(delivery_id)
        now = datetime.now(UTC).isoformat()
        try:
            with self._database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO webhook_deliveries(
                        delivery_id, state, claimed_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(delivery_id) DO NOTHING
                    """,
                    (normalized_id, DeliveryState.PROCESSING.value, now, now),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise RuntimeError("claim GitHub delivery 失败") from exc

    def mark_completed(self, delivery_id: str) -> None:
        normalized_id = _validate_delivery_id(delivery_id)
        now = datetime.now(UTC).isoformat()
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE webhook_deliveries
                SET state = ?, completed_at = ?, updated_at = ?
                WHERE delivery_id = ?
                """,
                (DeliveryState.COMPLETED.value, now, now, normalized_id),
            )
            if cursor.rowcount == 0:
                raise KeyError("delivery_id 尚未被 claim")

    def release(self, delivery_id: str) -> None:
        normalized_id = _validate_delivery_id(delivery_id)
        with self._database.transaction() as connection:
            connection.execute(
                """
                DELETE FROM webhook_deliveries
                WHERE delivery_id = ? AND state = ?
                """,
                (normalized_id, DeliveryState.PROCESSING.value),
            )

    @property
    def size(self) -> int:
        connection = self._database.connect()
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM webhook_deliveries"
                ).fetchone()[0]
            )
        finally:
            connection.close()

    def get_state(self, delivery_id: str) -> DeliveryState | None:
        normalized_id = _validate_delivery_id(delivery_id)
        connection = self._database.connect()
        try:
            row = connection.execute(
                "SELECT state FROM webhook_deliveries WHERE delivery_id = ?",
                (normalized_id,),
            ).fetchone()
        finally:
            connection.close()
        return DeliveryState(row["state"]) if row else None


def _validate_delivery_id(delivery_id: str) -> str:
    if not isinstance(delivery_id, str) or not delivery_id.strip():
        raise ValueError("delivery_id 不能为空")
    if delivery_id != delivery_id.strip():
        raise ValueError("delivery_id 不能包含首尾空白")
    if len(delivery_id) > 255:
        raise ValueError("delivery_id 不能超过 255 个字符")
    return delivery_id
