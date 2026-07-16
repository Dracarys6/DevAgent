from fastapi.testclient import TestClient

from devagent.api.app import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "devagent",
        "version": "0.1.0",
    }


def test_openapi_schema_is_available():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "DevAgent"


def test_unknown_path_returns_404():
    response = client.get("/missing")

    assert response.status_code == 404


def test_local_frontend_origin_is_allowed_by_cors():
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )
