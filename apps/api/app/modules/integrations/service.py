"""Consent management: grant, check, revoke. Gates every connector and publish.

Every grant/revoke is written to the append-only ledger. Consent is
time-boxed (default 90 days) and checked before any source read or publish.
"""
import json
from datetime import datetime, timedelta, timezone

from app.config.settings import (CONSENT_TTL_DAYS, SOURCE_DEFAULTS,
                                 SOURCE_LOOKBACK_CHOICES, SOURCE_MAX_ITEMS)
from app.shared.database.session import get_db, log_ledger, now_iso
from app.shared.security import vault


class ConsentError(Exception):
    """Raised when an action is attempted without valid consent."""


# CLI-facing names for providers whose internal id differs.
_DISPLAY = {"upload_post": "linkedin"}


def _cli_name(provider: str) -> str:
    return _DISPLAY.get(provider, provider)


def grant(provider: str, scopes: list[str], meta: dict | None = None,
          secrets: dict | None = None, ttl_days: int = CONSENT_TTL_DAYS) -> dict:
    """Record consent for a provider; store its secrets in the encrypted vault."""
    conn = get_db()
    granted_at = datetime.now(timezone.utc)
    expires_at = granted_at + timedelta(days=ttl_days)
    record = {
        "provider": provider,
        "scopes": scopes,
        "granted_at": granted_at.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "status": "active",
        "meta": meta or {},
    }
    conn.execute(
        "INSERT INTO consent (provider, scopes, granted_at, expires_at, status, meta) "
        "VALUES (?, ?, ?, ?, 'active', ?) "
        "ON CONFLICT(provider) DO UPDATE SET scopes=excluded.scopes, "
        "granted_at=excluded.granted_at, expires_at=excluded.expires_at, "
        "status='active', meta=excluded.meta",
        (provider, json.dumps(scopes), record["granted_at"],
         record["expires_at"], json.dumps(meta or {})),
    )
    conn.commit()
    log_ledger(conn, provider, "grant", f"scopes={scopes} ttl={ttl_days}d")
    if secrets:
        vault.set_secret(provider, secrets)
    conn.close()
    return record


def revoke(provider: str, *, purge_all: bool = False) -> None:
    """Revoke consent and purge the provider's secrets and cached signals."""
    conn = get_db()
    conn.execute("UPDATE consent SET status='revoked' WHERE provider=?", (provider,))
    suffix = "" if purge_all else " AND used=0"
    purged = conn.execute(
        f"DELETE FROM signals WHERE source=?{suffix}", (provider,)
    ).rowcount
    conn.commit()
    log_ledger(conn, provider, "revoke", f"purged_unused_signals={purged}")
    vault.delete_secret(provider)
    conn.close()


def update_meta(provider: str, meta: dict) -> dict:
    """Update non-secret connector policy while retaining the consent grant."""
    record = require(provider)
    conn = get_db()
    conn.execute("UPDATE consent SET meta=? WHERE provider=?", (json.dumps(meta), provider))
    conn.commit()
    log_ledger(conn, provider, "settings_change", "connector policy updated")
    conn.close()
    return {**record, "meta": meta}


def get_source_policy(provider: str) -> dict:
    if provider not in SOURCE_DEFAULTS:
        return {}
    record = get(provider)
    saved = (record or {}).get("meta", {}).get("policy", {})
    return {**SOURCE_DEFAULTS[provider], **saved}


def set_source_policy(provider: str, policy: dict) -> dict:
    """Validate and persist user-controlled fetch bounds for a Google source."""
    if provider not in SOURCE_DEFAULTS:
        raise ValueError("That source does not support fetch settings.")
    record = require(provider)
    current = get_source_policy(provider)
    merged = {**current, **policy}
    try:
        merged["max_items"] = int(merged["max_items"])
        merged["lookback_hours"] = int(merged["lookback_hours"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Source limits must be numbers.") from exc
    if not 1 <= merged["max_items"] <= SOURCE_MAX_ITEMS:
        raise ValueError(f"max_items must be between 1 and {SOURCE_MAX_ITEMS}.")
    if merged["lookback_hours"] not in SOURCE_LOOKBACK_CHOICES:
        raise ValueError(f"lookback_hours must be one of {SOURCE_LOOKBACK_CHOICES}.")
    merged["scheduled_enabled"] = bool(merged.get("scheduled_enabled", False))
    if provider == "gmail":
        labels = merged.get("label_ids")
        if not isinstance(labels, list) or not labels or len(labels) > 20:
            raise ValueError("Choose between 1 and 20 Gmail labels.")
        merged["label_ids"] = [str(label) for label in labels if str(label).strip()]
        if not merged["label_ids"]:
            raise ValueError("Choose at least one Gmail label.")
    else:
        if not str(merged.get("folder_id", "")).strip():
            raise ValueError("Choose a Drive folder.")
        merged["folder_id"] = str(merged["folder_id"])
        merged["folder_name"] = str(merged.get("folder_name", ""))[:200]
    meta = {**record["meta"], "policy": merged}
    update_meta(provider, meta)
    return merged


def set_status(provider: str, status: str, details: str = "") -> None:
    conn = get_db()
    conn.execute("UPDATE consent SET status=? WHERE provider=?", (status, provider))
    conn.commit()
    log_ledger(conn, provider, status, details)
    conn.close()


def get(provider: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM consent WHERE provider=?", (provider,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "provider": row["provider"],
        "scopes": json.loads(row["scopes"]),
        "granted_at": row["granted_at"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        "meta": json.loads(row["meta"]),
    }


def require(provider: str, scope: str | None = None) -> dict:
    """Assert active, unexpired consent for provider (and scope, if given)."""
    record = get(provider)
    if not record or record["status"] != "active":
        raise ConsentError(
            f"No active consent for '{provider}'. Run: agent connect {_cli_name(provider)}"
        )
    if now_iso() > record["expires_at"]:
        conn = get_db()
        conn.execute("UPDATE consent SET status='expired' WHERE provider=?", (provider,))
        conn.commit()
        log_ledger(conn, provider, "expired", "consent TTL reached")
        conn.close()
        raise ConsentError(
            f"Consent for '{provider}' expired on {record['expires_at']}. "
            f"Reconnect with: agent connect {_cli_name(provider)}"
        )
    if scope and scope not in record["scopes"]:
        raise ConsentError(
            f"Consent for '{provider}' does not include scope '{scope}'. "
            f"Granted scopes: {record['scopes']}"
        )
    return record


def list_all() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM consent ORDER BY provider").fetchall()
    conn.close()
    return [
        {
            "provider": r["provider"],
            "scopes": json.loads(r["scopes"]),
            "granted_at": r["granted_at"],
            "expires_at": r["expires_at"],
            "status": r["status"],
            "meta": json.loads(r["meta"]),
        }
        for r in rows
    ]


def audit_log(provider: str | None = None, limit: int = 50) -> list[dict]:
    conn = get_db()
    if provider:
        rows = conn.execute(
            "SELECT * FROM ledger WHERE provider=? ORDER BY id DESC LIMIT ?",
            (provider, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
