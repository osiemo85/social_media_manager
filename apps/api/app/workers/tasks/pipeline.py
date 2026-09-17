"""Scheduler & pipeline: run ingest → draft → route on a user-chosen cadence.

Users pick runs-per-day (0 = off, 1 = daily, 2 = twice a day, ... up to 24).
`run_due()` is idempotent: it only runs when the interval since the last run
has elapsed, so both the CLI daemon and the web scheduler thread can call it
as often as they like.
"""
from datetime import datetime, timezone

from app.modules.integrations import service as consent
from app.modules.content import service as drafting
from app.modules.publishing import state_machine as router
from app.config.settings import SCHEDULE_CHOICES
from app.modules.integrations.providers import filesystem as fs_connector
from app.modules.integrations.providers import gmail as gmail_connector
from app.modules.integrations.providers import google_drive as drive_connector
from app.modules.integrations.providers import github as gh_connector
from app.shared.database.session import (add_draft, clear_signal_content, get_db,
                                         get_latest_published_post, get_setting,
                                         log_ledger, set_setting)

SOURCES = {"github": gh_connector.ingest, "filesystem": fs_connector.ingest}
GOOGLE_SOURCES = {"gmail", "google_drive"}


def get_schedule() -> int:
    conn = get_db()
    value = int(get_setting(conn, "runs_per_day", "0"))
    conn.close()
    return value


def set_schedule(runs_per_day: int) -> None:
    if runs_per_day not in SCHEDULE_CHOICES:
        raise ValueError(f"runs_per_day must be one of {SCHEDULE_CHOICES}")
    conn = get_db()
    set_setting(conn, "runs_per_day", str(runs_per_day))
    log_ledger(conn, "settings", "schedule_change", f"runs_per_day={runs_per_day}")
    conn.close()


def _google_options(name: str, overrides: dict | None) -> dict:
    policy = consent.get_source_policy(name)
    if overrides:
        policy.update({key: value for key, value in overrides.items()
                       if key in {"max_items", "lookback_hours"}})
    # Run overrides use the same validation bounds without persisting them.
    max_items = int(policy["max_items"])
    lookback = int(policy["lookback_hours"])
    from app.config.settings import SOURCE_LOOKBACK_CHOICES, SOURCE_MAX_ITEMS
    if not 1 <= max_items <= SOURCE_MAX_ITEMS:
        raise ValueError(f"{name} max_items must be between 1 and {SOURCE_MAX_ITEMS}")
    if lookback not in SOURCE_LOOKBACK_CHOICES:
        raise ValueError(f"{name} lookback_hours must be one of {SOURCE_LOOKBACK_CHOICES}")
    if name == "gmail":
        return {"max_items": max_items, "lookback_hours": lookback,
                "label_ids": policy["label_ids"]}
    return {"max_items": max_items, "lookback_hours": lookback,
            "folder_id": policy["folder_id"]}


def ingest_all(selected_sources: dict[str, dict] | None = None,
               *, scheduled: bool = False) -> tuple[dict[str, int | str], list[int]]:
    """Ingest every consented source; per-source errors don't stop the rest."""
    results: dict[str, int | str] = {}
    signal_ids: list[int] = []
    all_sources = {**SOURCES, "gmail": gmail_connector.ingest,
                   "google_drive": drive_connector.ingest}
    for name, ingest_fn in all_sources.items():
        if selected_sources is not None:
            selection = selected_sources.get(name)
            if not selection or not selection.get("enabled", True):
                continue
        else:
            selection = None
        record = consent.get(name)
        if not record or record["status"] != "active":
            if selected_sources is not None:
                results[name] = "error: source is not connected or requires authorization"
            continue
        if scheduled and name in GOOGLE_SOURCES:
            if not consent.get_source_policy(name).get("scheduled_enabled"):
                results[name] = "skipped: scheduled access is off"
                continue
        try:
            if name in GOOGLE_SOURCES:
                ids = ingest_fn(**_google_options(name, selection))
            else:
                ids = ingest_fn()
            results[name] = len(ids)
            signal_ids.extend(ids)
        except Exception as e:  # noqa: BLE001 — a failing source must not kill the run
            results[name] = f"error: {e}"
    return results, signal_ids


def draft_from_signals(signal_ids: list[int], platforms: list[str] | None = None,
                       dry_run: bool = False) -> dict | None:
    """Draft one post from signals fetched by this run and route it."""
    if not signal_ids:
        return None
    platforms = platforms or ["linkedin"]
    conn = get_db()
    marks = ",".join("?" * len(signal_ids))
    rows = conn.execute(
        f"SELECT * FROM signals WHERE used=0 AND id IN ({marks}) ORDER BY ts DESC",
        signal_ids,
    ).fetchall()
    if not rows:
        conn.close()
        return None
    signals = [dict(r) for r in rows]
    signal_ids = [s["id"] for s in signals]

    previous_published_post = get_latest_published_post(conn)
    text = drafting.draft_post(signals, previous_published_post)
    draft_id = add_draft(conn, text, signal_ids, platforms)
    qmarks = ",".join("?" * len(signal_ids))
    conn.execute(f"UPDATE signals SET used=1 WHERE id IN ({qmarks})", signal_ids)
    conn.commit()
    sensitive_ids = [s["id"] for s in signals if s["source"] in GOOGLE_SOURCES]
    clear_signal_content(conn, sensitive_ids)
    conn.close()

    sources = list({s["source"] for s in signals})
    outcome = router.route_draft(draft_id, sources, dry_run=dry_run)
    return {"draft_id": draft_id, "text": text, **outcome}


def run_pipeline(dry_run: bool = False, selected_sources: dict[str, dict] | None = None,
                 *, scheduled: bool = False) -> dict:
    """One full manual or scheduled run: ingest, draft, and route."""
    ingested, signal_ids = ingest_all(selected_sources, scheduled=scheduled)
    outcome = draft_from_signals(signal_ids, dry_run=dry_run)
    conn = get_db()
    set_setting(conn, "last_run_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    log_ledger(conn, "scheduler", "run",
               f"ingested={ingested} outcome={(outcome or {}).get('routed', 'no_signals')}")
    conn.close()
    return {"ingested": ingested, "outcome": outcome}


def seconds_until_due() -> float | None:
    """None if scheduling is off; <=0 if a run is due now; else seconds left."""
    runs_per_day = get_schedule()
    if runs_per_day <= 0:
        return None
    interval = 86400 / runs_per_day
    conn = get_db()
    last = get_setting(conn, "last_run_at", "")
    conn.close()
    if not last:
        return 0
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
    return interval - elapsed


def run_due(dry_run: bool = False) -> dict | None:
    """Run the pipeline only if a scheduled run is due. Safe to poll."""
    due = seconds_until_due()
    if due is None or due > 0:
        return None
    return run_pipeline(dry_run=dry_run, scheduled=True)
