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
from app.modules.integrations.providers import github as gh_connector
from app.shared.database.session import add_draft, get_db, get_setting, log_ledger, set_setting

SOURCES = {"github": gh_connector.ingest, "filesystem": fs_connector.ingest}


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


def ingest_all() -> dict[str, int | str]:
    """Ingest every consented source; per-source errors don't stop the rest."""
    results: dict[str, int | str] = {}
    for name, ingest_fn in SOURCES.items():
        record = consent.get(name)
        if not record or record["status"] != "active":
            continue
        try:
            results[name] = len(ingest_fn())
        except Exception as e:  # noqa: BLE001 — a failing source must not kill the run
            results[name] = f"error: {e}"
    return results


def draft_from_unused_signals(platforms: list[str] | None = None,
                              dry_run: bool = False) -> dict | None:
    """Draft one post from unused non-manual signals and route it."""
    platforms = platforms or ["linkedin"]
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM signals WHERE used=0 AND source != 'manual' "
        "ORDER BY ts DESC LIMIT 10"
    ).fetchall()
    if not rows:
        conn.close()
        return None
    signals = [dict(r) for r in rows]
    signal_ids = [s["id"] for s in signals]

    print(f"Drafting post from signals: {signals}")
    text = drafting.draft_post(signals)
    draft_id = add_draft(conn, text, signal_ids, platforms)
    qmarks = ",".join("?" * len(signal_ids))
    conn.execute(f"UPDATE signals SET used=1 WHERE id IN ({qmarks})", signal_ids)
    conn.commit()
    conn.close()

    sources = list({s["source"] for s in signals})
    outcome = router.route_draft(draft_id, sources, dry_run=dry_run)
    return {"draft_id": draft_id, "text": text, **outcome}


def run_pipeline(dry_run: bool = False) -> dict:
    """One full scheduled run: ingest all sources, draft, route."""
    ingested = ingest_all()
    outcome = draft_from_unused_signals(dry_run=dry_run)
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
    return run_pipeline(dry_run=dry_run)
