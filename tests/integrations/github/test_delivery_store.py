import threading

import pytest

from devagent.integrations.github.delivery_store import (
    DeliveryState,
    DeliveryStoreCapacityError,
    InMemoryWebhookDeliveryStore,
)


def test_delivery_store_claim_complete_and_duplicate() -> None:
    store = InMemoryWebhookDeliveryStore(max_entries=2)

    assert store.claim("delivery-1") is True
    assert store.claim("delivery-1") is False
    assert store.get_state("delivery-1") == DeliveryState.PROCESSING

    store.mark_completed("delivery-1")
    store.mark_completed("delivery-1")

    assert store.claim("delivery-1") is False
    assert store.get_state("delivery-1") == DeliveryState.COMPLETED


def test_delivery_store_release_allows_redelivery() -> None:
    store = InMemoryWebhookDeliveryStore()
    store.claim("delivery-1")

    store.release("delivery-1")

    assert store.claim("delivery-1") is True


def test_delivery_store_release_preserves_completed_and_ignores_unknown() -> None:
    store = InMemoryWebhookDeliveryStore()
    store.claim("completed")
    store.mark_completed("completed")

    store.release("completed")
    store.release("unknown")

    assert store.get_state("completed") == DeliveryState.COMPLETED


def test_delivery_store_mark_completed_rejects_unknown() -> None:
    store = InMemoryWebhookDeliveryStore()

    with pytest.raises(KeyError, match="尚未被 claim"):
        store.mark_completed("unknown")


def test_delivery_store_evicts_oldest_completed_entry() -> None:
    store = InMemoryWebhookDeliveryStore(max_entries=2)
    store.claim("oldest")
    store.mark_completed("oldest")
    store.claim("newer")
    store.mark_completed("newer")

    assert store.claim("incoming") is True

    assert store.get_state("oldest") is None
    assert store.get_state("newer") == DeliveryState.COMPLETED
    assert store.get_state("incoming") == DeliveryState.PROCESSING
    assert store.size == 2


def test_delivery_store_does_not_evict_processing_entries() -> None:
    store = InMemoryWebhookDeliveryStore(max_entries=2)
    store.claim("processing-1")
    store.claim("processing-2")

    with pytest.raises(DeliveryStoreCapacityError):
        store.claim("incoming")

    assert store.size == 2


def test_delivery_store_concurrent_claim_has_one_winner() -> None:
    store = InMemoryWebhookDeliveryStore(max_entries=20)
    barrier = threading.Barrier(16)
    results: list[bool] = []
    results_lock = threading.Lock()

    def claim() -> None:
        barrier.wait()
        result = store.claim("same-delivery")
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=claim) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1
    assert results.count(False) == 15
    assert store.size == 1


@pytest.mark.parametrize("delivery_id", ["", "   ", " padded", "x" * 256])
def test_delivery_store_rejects_invalid_delivery_id(delivery_id: str) -> None:
    store = InMemoryWebhookDeliveryStore()

    with pytest.raises(ValueError, match="delivery_id"):
        store.claim(delivery_id)


@pytest.mark.parametrize("max_entries", [0, -1, True])
def test_delivery_store_rejects_invalid_capacity(max_entries: int) -> None:
    with pytest.raises(ValueError, match="max_entries"):
        InMemoryWebhookDeliveryStore(max_entries=max_entries)
