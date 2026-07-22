import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from devagent.api.app import app
from devagent.api.routes.github_webhooks import (
    get_delivery_store,
    get_github_review_task_manager,
    get_github_webhook_secret,
    receive_github_webhook,
)
from devagent.integrations.github import InMemoryWebhookDeliveryStore

WEBHOOK_SECRET = "fixed-webhook-secret"
WEBHOOK_URL = "/api/v1/integrations/github/webhooks"


def make_payload(action: str = "opened") -> dict:
    return {
        "action": action,
        "repository": {"full_name": "openai/devagent"},
        "pull_request": {
            "number": 42,
            "draft": False,
            "base": {"ref": "main", "sha": "a" * 40},
            "head": {"ref": "feature/payment", "sha": "b" * 40},
        },
        "installation": {"id": 123},
    }


def encode_payload(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def make_headers(
    body: bytes,
    *,
    event: str = "pull_request",
    delivery_id: str | None = "delivery-1",
) -> dict[str, str]:
    headers = {
        "X-Hub-Signature-256": sign(body),
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }
    if delivery_id is not None:
        headers["X-GitHub-Delivery"] = delivery_id
    return headers


class RecordingDeliveryStore(InMemoryWebhookDeliveryStore):
    def __init__(self, max_entries: int = 1000) -> None:
        super().__init__(max_entries=max_entries)
        self.claim_calls: list[str] = []
        self.release_calls: list[str] = []

    def claim(self, delivery_id: str) -> bool:
        self.claim_calls.append(delivery_id)
        return super().claim(delivery_id)

    def release(self, delivery_id: str) -> None:
        self.release_calls.append(delivery_id)
        super().release(delivery_id)


class RecordingTaskManager:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.create_calls: list[dict[str, object]] = []
        self.run_calls: list[str] = []

    def create_task(self, **kwargs: object):
        self.create_calls.append(kwargs)
        if self.fail_create:
            raise RuntimeError("token=secret-scheduling-detail")
        return SimpleNamespace(task_id=f"github-task-{len(self.create_calls)}")

    def run_task(self, task_id: str) -> None:
        self.run_calls.append(task_id)


@pytest.fixture
def github_api():
    store = RecordingDeliveryStore()
    manager = RecordingTaskManager()
    app.dependency_overrides[get_github_webhook_secret] = lambda: WEBHOOK_SECRET
    app.dependency_overrides[get_delivery_store] = lambda: store
    app.dependency_overrides[get_github_review_task_manager] = lambda: manager
    with TestClient(app) as client:
        yield client, store, manager
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "action",
    ["opened", "reopened", "synchronize", "ready_for_review"],
)
def test_target_actions_return_accepted_and_schedule_one_task(
    github_api,
    action: str,
) -> None:
    client, store, manager = github_api
    body = encode_payload(make_payload(action))

    response = client.post(WEBHOOK_URL, content=body, headers=make_headers(body))

    assert response.status_code == 202
    assert response.json() == {
        "delivery_id": "delivery-1",
        "status": "accepted",
        "task_id": "github-task-1",
    }
    assert store.claim_calls == ["delivery-1"]
    assert len(manager.create_calls) == 1
    locator = manager.create_calls[0]["locator"]
    assert locator.platform == "github"
    assert locator.repository == "openai/devagent"
    assert locator.number == 42
    assert manager.run_calls == ["github-task-1"]


def test_duplicate_delivery_does_not_create_second_task(github_api) -> None:
    client, _, manager = github_api
    body = encode_payload(make_payload())
    headers = make_headers(body)

    first = client.post(WEBHOOK_URL, content=body, headers=headers)
    second = client.post(WEBHOOK_URL, content=body, headers=headers)

    assert first.json()["status"] == "accepted"
    assert second.status_code == 202
    assert second.json() == {
        "delivery_id": "delivery-1",
        "status": "duplicate",
        "task_id": None,
    }
    assert len(manager.create_calls) == 1


def test_non_target_action_and_non_pull_request_event_are_ignored(github_api) -> None:
    client, store, manager = github_api
    closed_body = encode_payload(make_payload("closed"))

    closed = client.post(
        WEBHOOK_URL,
        content=closed_body,
        headers=make_headers(closed_body),
    )
    ping_body = b"not-json-and-must-not-be-parsed"
    ping = client.post(
        WEBHOOK_URL,
        content=ping_body,
        headers=make_headers(ping_body, event="ping", delivery_id=None),
    )

    assert closed.status_code == 202
    assert closed.json()["status"] == "ignored"
    assert ping.status_code == 202
    assert ping.json() == {
        "delivery_id": "not-applicable",
        "status": "ignored",
        "task_id": None,
    }
    assert store.claim_calls == []
    assert manager.create_calls == []


def test_invalid_signature_is_rejected_before_payload_and_dependencies(github_api) -> None:
    client, store, manager = github_api
    body = b"not-json-secret-payload"
    headers = make_headers(body)
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64

    response = client.post(WEBHOOK_URL, content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_github_signature"
    assert WEBHOOK_SECRET not in response.text
    assert body.decode() not in response.text
    assert store.claim_calls == []
    assert manager.create_calls == []


def test_signed_invalid_json_returns_400(github_api) -> None:
    client, store, manager = github_api
    body = b"not-json"

    response = client.post(WEBHOOK_URL, content=body, headers=make_headers(body))

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_github_payload"
    assert store.claim_calls == []
    assert manager.create_calls == []


def test_target_action_requires_delivery_header(github_api) -> None:
    client, store, manager = github_api
    body = encode_payload(make_payload())

    response = client.post(
        WEBHOOK_URL,
        content=body,
        headers=make_headers(body, delivery_id=None),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "missing_github_delivery"
    assert store.claim_calls == []
    assert manager.create_calls == []


def test_target_payload_missing_required_fields_returns_422(github_api) -> None:
    client, store, manager = github_api
    payload = make_payload()
    payload.pop("installation")
    body = encode_payload(payload)

    response = client.post(WEBHOOK_URL, content=body, headers=make_headers(body))

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_github_payload"
    assert store.claim_calls == []
    assert manager.create_calls == []


def test_delivery_store_capacity_returns_503() -> None:
    store = RecordingDeliveryStore(max_entries=1)
    store.claim("processing-delivery")
    manager = RecordingTaskManager()
    app.dependency_overrides[get_github_webhook_secret] = lambda: WEBHOOK_SECRET
    app.dependency_overrides[get_delivery_store] = lambda: store
    app.dependency_overrides[get_github_review_task_manager] = lambda: manager
    body = encode_payload(make_payload())

    with TestClient(app) as client:
        response = client.post(
            WEBHOOK_URL,
            content=body,
            headers=make_headers(body, delivery_id="incoming"),
        )
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "github_delivery_store_full"
    assert manager.create_calls == []


def test_missing_task_manager_returns_503_without_claiming_delivery() -> None:
    store = RecordingDeliveryStore()
    app.dependency_overrides[get_github_webhook_secret] = lambda: WEBHOOK_SECRET
    app.dependency_overrides[get_delivery_store] = lambda: store
    app.dependency_overrides[get_github_review_task_manager] = lambda: None
    body = encode_payload(make_payload())

    with TestClient(app) as client:
        response = client.post(WEBHOOK_URL, content=body, headers=make_headers(body))
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "github_review_not_configured"
    assert store.claim_calls == []


def test_task_creation_failure_releases_delivery_and_sanitizes_error() -> None:
    store = RecordingDeliveryStore()
    manager = RecordingTaskManager(fail_create=True)
    app.dependency_overrides[get_github_webhook_secret] = lambda: WEBHOOK_SECRET
    app.dependency_overrides[get_delivery_store] = lambda: store
    app.dependency_overrides[get_github_review_task_manager] = lambda: manager
    body = encode_payload(make_payload())

    with TestClient(app) as client:
        response = client.post(WEBHOOK_URL, content=body, headers=make_headers(body))
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "github_review_scheduling_failed"
    assert "secret-scheduling-detail" not in response.text
    assert store.release_calls == ["delivery-1"]
    assert store.claim("delivery-1") is True


def test_route_registers_background_task_before_review_execution() -> None:
    body = encode_payload(make_payload())
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": WEBHOOK_URL,
            "raw_path": WEBHOOK_URL.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        },
        receive,
    )
    background_tasks = BackgroundTasks()
    store = RecordingDeliveryStore()
    manager = RecordingTaskManager()

    result = asyncio.run(
        receive_github_webhook(
            request=request,
            background_tasks=background_tasks,
            x_hub_signature_256=sign(body),
            x_github_event="pull_request",
            x_github_delivery="delivery-direct",
            secret=WEBHOOK_SECRET,
            delivery_store=store,
            task_manager=manager,
        )
    )

    assert result.status.value == "accepted"
    assert manager.run_calls == []
    assert len(background_tasks.tasks) == 1

    asyncio.run(background_tasks())

    assert manager.run_calls == ["github-task-1"]


def test_missing_webhook_secret_maps_to_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "devagent.api.routes.github_webhooks.load_dotenv",
        lambda **kwargs: None,
    )
    monkeypatch.delenv("DEVAGENT_GITHUB_WEBHOOK_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        get_github_webhook_secret()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "github_webhook_not_configured"


def test_openapi_contains_github_webhook_202_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"][WEBHOOK_URL]["post"]
    assert operation["responses"]["202"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/GitHubWebhookResponse"}
