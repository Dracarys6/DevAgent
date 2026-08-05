import threading
from pathlib import Path

from devagent.integrations.github import (
    DeliveryState,
    PublicationStatus,
    SQLiteGitHubReviewPublicationStore,
    SQLiteWebhookDeliveryStore,
)
from devagent.storage import SQLiteDatabase, SQLiteSettings


def make_database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(SQLiteSettings(path=tmp_path / "github.db"))
    database.initialize()
    return database


def test_sqlite_delivery_claim_is_atomic_and_survives_restart(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    store = SQLiteWebhookDeliveryStore(database)
    barrier = threading.Barrier(12)
    results: list[bool] = []
    lock = threading.Lock()

    def claim() -> None:
        barrier.wait()
        result = store.claim("delivery-1")
        with lock:
            results.append(result)

    threads = [threading.Thread(target=claim) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    reopened = SQLiteWebhookDeliveryStore(database)
    assert results.count(True) == 1
    assert results.count(False) == 11
    assert reopened.get_state("delivery-1") == DeliveryState.PROCESSING
    reopened.mark_completed("delivery-1")
    assert reopened.claim("delivery-1") is False


def test_sqlite_delivery_release_only_removes_processing(tmp_path: Path) -> None:
    store = SQLiteWebhookDeliveryStore(make_database(tmp_path))
    store.claim("processing")
    store.claim("completed")
    store.mark_completed("completed")

    store.release("processing")
    store.release("completed")

    assert store.get_state("processing") is None
    assert store.get_state("completed") == DeliveryState.COMPLETED


def test_publication_store_deduplicates_pr_head_and_records_comment_id(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    deliveries = SQLiteWebhookDeliveryStore(database)
    deliveries.claim("delivery-1")
    deliveries.claim("delivery-2")
    store = SQLiteGitHubReviewPublicationStore(database)

    first = store.claim(
        delivery_id="delivery-1",
        repository_full_name="openai/devagent",
        pull_number=42,
        head_sha="b" * 40,
    )
    duplicate = store.claim(
        delivery_id="delivery-2",
        repository_full_name="openai/devagent",
        pull_number=42,
        head_sha="b" * 40,
    )
    completed = store.mark_completed(
        first.publication.publication_id,
        "comment-123",
    )

    assert first.acquired is True
    assert duplicate.acquired is False
    assert completed.status == PublicationStatus.COMPLETED
    assert completed.external_comment_id == "comment-123"


def test_failed_publication_can_be_reclaimed_by_redelivery(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    deliveries = SQLiteWebhookDeliveryStore(database)
    deliveries.claim("delivery-1")
    deliveries.claim("delivery-2")
    store = SQLiteGitHubReviewPublicationStore(database)
    first = store.claim(
        delivery_id="delivery-1",
        repository_full_name="openai/devagent",
        pull_number=42,
        head_sha="b" * 40,
    )
    store.mark_failed(first.publication.publication_id)

    retried = store.claim(
        delivery_id="delivery-2",
        repository_full_name="openai/devagent",
        pull_number=42,
        head_sha="b" * 40,
    )

    assert retried.acquired is True
    assert retried.publication.status == PublicationStatus.PROCESSING
    assert retried.publication.delivery_id == "delivery-2"


def test_failed_publication_does_not_block_delivery_release(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    deliveries = SQLiteWebhookDeliveryStore(database)
    deliveries.claim("delivery-1")
    publications = SQLiteGitHubReviewPublicationStore(database)
    claim = publications.claim(
        delivery_id="delivery-1",
        repository_full_name="openai/devagent",
        pull_number=42,
        head_sha="b" * 40,
    )
    publications.mark_failed(claim.publication.publication_id)

    deliveries.release("delivery-1")

    assert deliveries.get_state("delivery-1") is None
    assert deliveries.claim("delivery-1") is True
    assert publications.get(claim.publication.publication_id).status == (
        PublicationStatus.FAILED
    )
