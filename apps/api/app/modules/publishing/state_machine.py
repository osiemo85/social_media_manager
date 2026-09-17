"""Publishing Mode Router: Review Mode (default) vs Auto-Publish Mode.

Review mode: drafts wait in the queue for explicit user approval.
Auto mode:   drafts publish immediately, subject to guardrails:
             - separate consent scope 'auto_publish' must have been granted
             - keyword blocklist check
             - daily rate limit (default 1 auto-post/day)
Manual-source drafts always route to review, even in auto mode.
"""
import json
from datetime import datetime, timedelta, timezone

from app.modules.integrations import service as consent
from app.modules.publishing import service as publisher
from app.config.settings import AUTO_PUBLISH_MAX_PER_DAY, BLOCKLIST
from app.shared.database.session import get_db, get_setting, log_ledger, set_setting


def get_mode() -> str:
    conn = get_db()
    mode = get_setting(conn, "publishing_mode", "review")
    conn.close()
    return mode


def set_mode(mode: str) -> None:
    if mode not in ("review", "auto"):
        raise ValueError("Mode must be 'review' or 'auto'.")
    if mode == "auto":
        # Enabling auto-publish is its own consent event.
        record = consent.get("upload_post")
        if not record or "auto_publish" not in record["scopes"]:
            raise consent.ConsentError(
                "Auto-publish requires explicit consent. Reconnect with "
                "'agent connect linkedin' and answer yes to auto-publish."
            )
    conn = get_db()
    set_setting(conn, "publishing_mode", mode)
    log_ledger(conn, "settings", "mode_change", f"publishing_mode={mode}")
    conn.close()


def _blocklist_hit(text: str) -> str | None:
    lowered = text.lower()
    for word in BLOCKLIST:
        if word in lowered:
            return word
    return None


def _auto_posts_today(conn) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM drafts WHERE status='published' AND published_at > ?",
        (cutoff,),
    ).fetchone()
    return row["n"]


def route_draft(draft_id: int, sources: list[str], dry_run: bool = False) -> dict:
    """Decide what happens to a new draft. Returns routing outcome."""
    mode = get_mode()
    conn = get_db()
    row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    text = row["text"]

    if mode != "auto":
        conn.close()
        return {"routed": "review_queue", "reason": "review mode active"}

    if "manual" in sources:
        conn.close()
        return {"routed": "review_queue", "reason": "manual-source drafts always require review"}

    if {"gmail", "google_drive"}.intersection(sources):
        conn.close()
        return {"routed": "review_queue",
                "reason": "Gmail and Drive drafts require review in this release"}

    hit = _blocklist_hit(text)
    if hit:
        log_ledger(conn, "router", "auto_blocked", f"draft={draft_id} blocklist='{hit}'")
        conn.close()
        return {"routed": "review_queue", "reason": f"blocklist keyword: '{hit}'"}

    if _auto_posts_today(conn) >= AUTO_PUBLISH_MAX_PER_DAY:
        conn.close()
        return {"routed": "review_queue",
                "reason": f"daily auto-publish limit ({AUTO_PUBLISH_MAX_PER_DAY}) reached"}

    conn.close()
    result = publisher.publish_draft(draft_id, dry_run=dry_run)
    return {"routed": "auto_published", "result": result}
