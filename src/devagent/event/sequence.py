from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import InMemorySequenceAllocator


class SequenceAllocatorError(RuntimeError):
    """事件序号无法安全分配。"""


class SequenceTaskNotFoundError(SequenceAllocatorError):
    pass


class SequencePersistenceError(SequenceAllocatorError):
    pass


@runtime_checkable
class SequenceAllocator(Protocol):
    def next(self, task_id: str) -> int: ...


__all__ = [
    "InMemorySequenceAllocator",
    "SequenceAllocator",
    "SequenceAllocatorError",
    "SequencePersistenceError",
    "SequenceTaskNotFoundError",
]
