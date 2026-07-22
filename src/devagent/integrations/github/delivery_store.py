from collections import OrderedDict
from enum import Enum
import threading

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
                raise DeliveryStoreCapacityError(
                    "Delivery store 已达到容量上限"
                )
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


def _validate_delivery_id(delivery_id: str) -> str:
    if not isinstance(delivery_id, str) or not delivery_id.strip():
        raise ValueError("delivery_id 不能为空")
    if delivery_id != delivery_id.strip():
        raise ValueError("delivery_id 不能包含首尾空白")
    if len(delivery_id) > 255:
        raise ValueError("delivery_id 不能超过 255 个字符")
    return delivery_id
