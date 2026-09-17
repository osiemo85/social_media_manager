from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app import main
from app.modules.integrations.providers import google_oauth


def test_google_start_contract_and_pipeline_validation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "USERS_DB", tmp_path / "users.db")
    monkeypatch.setattr(google_oauth, "GOOGLE_SOURCES_ENABLED", True)
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_SECRET", "test-secret")

    client = TestClient(main.app)
    registered = client.post(
        "/api/auth/register",
        data={"email": "source-test@example.com", "password": "password123"},
    )
    assert registered.status_code == 201

    started = client.get("/api/connections/gmail/start")
    assert started.status_code == 200
    scopes = parse_qs(urlparse(started.json()["authorization_url"]).query)["scope"][0]
    assert "gmail.readonly" in scopes
    assert "drive.readonly" not in scopes

    invalid = client.post("/api/pipeline/run", json={
        "sources": {"gmail": {"enabled": True, "max_items": 5, "lookback_hours": 72}}
    })
    assert invalid.status_code == 422

    unauthorized_settings = client.put("/api/connections/gmail/settings", json={
        "max_items": 5, "lookback_hours": 24,
        "scheduled_enabled": False, "label_ids": ["INBOX"],
    })
    assert unauthorized_settings.status_code == 400
