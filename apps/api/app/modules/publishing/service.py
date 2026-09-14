"""Publisher: posts approved drafts via Upload-Post (LinkedIn + 21 platforms).

Consent-gated: requires an active 'upload_post' consent with a 'publish:<platform>'
scope for every platform in the draft. One API call can fan out to multiple
platforms (LinkedIn, X, Threads, Bluesky, ...) — see https://www.upload-post.com/.
"""
import json

import requests

from app.modules.integrations import service as consent
from app.shared.security import vault
from app.config.settings import UPLOAD_POST_URL
from app.shared.database.session import get_db, log_ledger, now_iso


class PublishError(Exception):
    pass


def publish_text(text: str, platforms: list[str], dry_run: bool = False) -> dict:
    """Publish text to one or more platforms via Upload-Post. Consent-gated."""
    record = consent.require("upload_post")
    for p in platforms:
        if f"publish:{p}" not in record["scopes"]:
            raise consent.ConsentError(
                f"No publish consent for platform '{p}'. "
                f"Reconnect and include it: agent connect linkedin"
            )

    secrets = vault.get_secret("upload_post")
    if not secrets or "api_key" not in secrets:
        raise PublishError("Upload-Post API key missing from vault. Reconnect.")

    if dry_run:
        return {"success": True, "dry_run": True, "platforms": platforms, "text": text}

    headers = {"Authorization": f"Apikey {secrets['api_key']}"}
    data = [("user", secrets["username"]), ("title", text)]
    data += [("platform[]", p) for p in platforms]

    try:
        resp = requests.post(UPLOAD_POST_URL, headers=headers, data=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        detail = ""
        if getattr(e, "response", None) is not None:
            detail = f" — {e.response.status_code}: {e.response.text[:200]}"
        raise PublishError(f"Upload-Post request failed{detail}. "
                           "Check your API key and connected platforms.") from e
    if not result.get("success", False):
        msg = result.get("message") or result.get("error") or "Unknown error"
        raise PublishError(f"Upload-Post API failed: {msg}")
    return result


def publish_draft(draft_id: int, dry_run: bool = False) -> dict:
    """Publish an approved (or pending-in-auto-mode) draft and record the result."""
    conn = get_db()
    row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        conn.close()
        raise PublishError(f"Draft {draft_id} not found.")
    if row["status"] == "published":
        conn.close()
        raise PublishError(f"Draft {draft_id} already published (idempotency guard).")
    if row["status"] == "rejected":
        conn.close()
        raise PublishError(f"Draft {draft_id} was rejected; cannot publish.")

    platforms = json.loads(row["platforms"])
    result = publish_text(row["text"], platforms, dry_run=dry_run)

    if not dry_run:
        conn.execute(
            "UPDATE drafts SET status='published', published_at=?, post_result=? WHERE id=?",
            (now_iso(), json.dumps(result), draft_id),
        )
        conn.commit()
        log_ledger(conn, "upload_post", "publish",
                   f"draft={draft_id} platforms={platforms}")
    conn.close()
    return result
