from pathlib import Path

from fastapi.testclient import TestClient

from devagent.api.app import app
from devagent.api.routes.knowledge import get_workspace_knowledge_service
from devagent.memory import RetrievalResult

client = TestClient(app)


def test_knowledge_search_returns_ranked_workspace_evidence(tmp_path: Path) -> None:
    (tmp_path / "webhook.md").write_text(
        "# GitHub Webhook\n\n使用 HMAC SHA-256 校验 webhook 签名。\n",
        encoding="utf-8",
    )
    (tmp_path / "unrelated.txt").write_text(
        "任务状态通过 SSE 推送给浏览器。\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/knowledge/search",
        json={
            "query": "webhook HMAC 签名",
            "workspace": str(tmp_path),
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "webhook HMAC 签名"
    assert body["top_k"] == 3
    assert body["total_candidates"] >= 1
    assert body["items"][0]["rank"] == 1
    assert body["items"][0]["path"] == "webhook.md"
    assert "HMAC SHA-256" in body["items"][0]["excerpt"]
    assert body["items"][0]["metadata"]["retrieval_method"] == "bm25"
    assert body["retrieval_ms"] >= 0


def test_knowledge_search_uses_dependency_injected_strategy() -> None:
    class FixedKnowledgeService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def retrieve(
            self,
            query: str,
            workspace: str,
            top_k: int,
        ) -> RetrievalResult:
            self.calls.append((query, workspace, top_k))
            return RetrievalResult(
                query=query,
                top_k=top_k,
                total_candidates=0,
                retrieval_ms=0.5,
            )

    service = FixedKnowledgeService()
    app.dependency_overrides[get_workspace_knowledge_service] = lambda: service
    try:
        response = client.post(
            "/api/v1/knowledge/search",
            json={"query": "hybrid", "workspace": "workspace", "top_k": 4},
        )
    finally:
        app.dependency_overrides.pop(get_workspace_knowledge_service, None)

    assert response.status_code == 200
    assert service.calls == [("hybrid", "workspace", 4)]


def test_knowledge_search_returns_empty_items_when_query_has_no_match(
    tmp_path: Path,
) -> None:
    (tmp_path / "runtime.md").write_text(
        "Agent runtime 使用 typed message。\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/knowledge/search",
        json={
            "query": "不存在的量子数据库",
            "workspace": str(tmp_path),
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()["total_candidates"] == 0
    assert response.json()["items"] == []


def test_knowledge_search_returns_structured_error_for_missing_workspace(
    tmp_path: Path,
) -> None:
    response = client.post(
        "/api/v1/knowledge/search",
        json={
            "query": "runtime",
            "workspace": str(tmp_path / "missing"),
            "top_k": 5,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "knowledge_retrieve_error"


def test_knowledge_search_rejects_invalid_payload() -> None:
    invalid_payloads = [
        {"query": " ", "workspace": ".", "top_k": 5},
        {"query": "runtime", "workspace": ".", "top_k": True},
    ]

    for payload in invalid_payloads:
        response = client.post("/api/v1/knowledge/search", json=payload)
        assert response.status_code == 422


def test_knowledge_search_is_exposed_in_openapi() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/api/v1/knowledge/search"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/KnowledgeSearchRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RetrievalResult"
    }
