from fastapi.testclient import TestClient

from app.main import app


def test_health_is_public() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_authenticated_routes_reject_anonymous_requests() -> None:
    response = TestClient(app).get("/api/auth/me")

    assert response.status_code == 401
