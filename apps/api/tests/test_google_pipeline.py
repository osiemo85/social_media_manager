from app.modules.integrations import service as consent
from app.modules.integrations.providers import google_oauth
from app.modules.publishing import state_machine
from app.shared.database.session import add_draft, add_signal, get_db
from app.workers.tasks import pipeline


def test_scheduled_run_skips_google_source_until_enabled(monkeypatch) -> None:
    consent.grant("gmail", google_oauth.SCOPES["gmail"], meta={"policy": {
        "max_items": 5, "lookback_hours": 24,
        "scheduled_enabled": False, "label_ids": ["INBOX"],
    }})
    called = []
    monkeypatch.setattr(pipeline.gmail_connector, "ingest", lambda **kwargs: called.append(kwargs) or [])

    results, ids = pipeline.ingest_all({"gmail": {"enabled": True}}, scheduled=True)

    assert called == []
    assert ids == []
    assert results["gmail"].startswith("skipped")


def test_explicit_source_without_authorization_returns_safe_error() -> None:
    results, ids = pipeline.ingest_all({"gmail": {"enabled": True}})

    assert ids == []
    assert results == {"gmail": "error: source is not connected or requires authorization"}


def test_pipeline_clears_sensitive_content_after_drafting(monkeypatch) -> None:
    conn = get_db()
    signal_id = add_signal(conn, "gmail", "email", "Launch", content="private source text", url="gmail:1")
    conn.close()
    monkeypatch.setattr(pipeline.drafting, "draft_post", lambda signals, previous: "Grounded draft")
    monkeypatch.setattr(pipeline.router, "route_draft", lambda draft_id, sources, dry_run=False: {"routed": "review_queue"})

    outcome = pipeline.draft_from_signals([signal_id])
    conn = get_db()
    content = conn.execute("SELECT content FROM signals WHERE id=?", (signal_id,)).fetchone()["content"]
    conn.close()

    assert outcome["text"] == "Grounded draft"
    assert content == ""


def test_google_source_draft_never_auto_publishes(monkeypatch) -> None:
    conn = get_db()
    draft_id = add_draft(conn, "A safe update", [], ["linkedin"])
    conn.close()
    monkeypatch.setattr(state_machine, "get_mode", lambda: "auto")

    result = state_machine.route_draft(draft_id, ["gmail"])

    assert result["routed"] == "review_queue"
    assert "require review" in result["reason"]
