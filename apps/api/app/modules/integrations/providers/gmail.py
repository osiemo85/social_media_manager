"""Consent-gated Gmail ingestion with bounded labels, lookback, and content."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from app.modules.integrations import service as consent
from app.modules.integrations.providers import google_oauth
from app.modules.integrations.providers.cleaning import clean_text, clean_title, html_to_text
from app.shared.database.session import add_signal_once, get_db, log_ledger

API = "https://gmail.googleapis.com/gmail/v1/users/me"


def list_labels() -> list[dict]:
    consent.require("gmail", "https://www.googleapis.com/auth/gmail.readonly")
    response = google_oauth.api_request("gmail", "GET", f"{API}/labels")
    if response.status_code != 200:
        raise google_oauth.GoogleProviderError("Gmail labels could not be loaded.")
    labels = google_oauth.response_json(response, "Gmail returned invalid label data.").get("labels", [])
    return sorted(
        ({"id": item["id"], "name": item["name"]} for item in labels
         if item.get("id") not in {"SPAM", "TRASH"}),
        key=lambda item: (item["id"] != "INBOX", item["name"].lower()),
    )


def _decode(value: str) -> str:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode(
            "utf-8", errors="ignore"
        )
    except (ValueError, TypeError):
        return ""


def _message_text(part: dict) -> tuple[str, str]:
    plain: list[str] = []
    rich: list[str] = []

    def walk(node: dict) -> None:
        mime = node.get("mimeType", "")
        data = node.get("body", {}).get("data", "")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(html_to_text(_decode(data)))
        for child in node.get("parts", []) or []:
            walk(child)

    walk(part)
    return "\n".join(plain), "\n".join(rich)


def _header(message: dict, name: str) -> str:
    for item in message.get("payload", {}).get("headers", []):
        if item.get("name", "").lower() == name.lower():
            return str(item.get("value", ""))
    return ""


def ingest(*, max_items: int, lookback_hours: int,
           label_ids: list[str] | None = None) -> list[int]:
    """Store at most max_items newest messages from the union of selected labels."""
    consent.require("gmail", "https://www.googleapis.com/auth/gmail.readonly")
    labels = label_ids or ["INBOX"]
    after = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp())
    by_label: list[list[str]] = []
    for label_id in labels:
        response = google_oauth.api_request(
            "gmail", "GET", f"{API}/messages",
            params={"labelIds": label_id, "q": f"after:{after}",
                    "maxResults": min(max_items * 2, 100)},
        )
        if response.status_code != 200:
            raise google_oauth.GoogleProviderError("Gmail messages could not be listed.")
        by_label.append([
            item["id"] for item in google_oauth.response_json(
                response, "Gmail returned invalid message data."
            ).get("messages", []) if item.get("id")
        ])

    # Round-robin labels so a busy Inbox cannot completely starve a smaller
    # user-selected label. Only the configured number receive full body reads.
    candidate_ids: list[str] = []
    seen: set[str] = set()
    index = 0
    while len(candidate_ids) < max_items and any(index < len(items) for items in by_label):
        for items in by_label:
            if index < len(items) and items[index] not in seen:
                seen.add(items[index])
                candidate_ids.append(items[index])
                if len(candidate_ids) == max_items:
                    break
        index += 1

    messages: list[dict] = []
    for message_id in candidate_ids:
        response = google_oauth.api_request(
            "gmail", "GET", f"{API}/messages/{message_id}",
            params={"format": "full"},
        )
        if response.status_code != 200:
            continue
        messages.append(google_oauth.response_json(response, "Gmail returned an invalid message."))
    messages.sort(key=lambda item: int(item.get("internalDate", 0)), reverse=True)

    conn = get_db()
    new_ids: list[int] = []
    for message in messages[:max_items]:
        message_id = message["id"]
        plain, rich = _message_text(message.get("payload", {}))
        body = plain or rich or str(message.get("snippet", ""))
        subject = clean_title(_header(message, "Subject") or "Email update")
        received = datetime.fromtimestamp(
            int(message.get("internalDate", 0)) / 1000, timezone.utc
        ).isoformat(timespec="seconds")
        signal_id = add_signal_once(
            conn, "gmail", "email", subject,
            content=clean_text(body, email=True),
            url=f"https://mail.google.com/mail/u/0/#all/{message_id}",
            ts=received,
        )
        if signal_id:
            new_ids.append(signal_id)
    log_ledger(
        conn, "gmail", "ingest",
        f"new_signals={len(new_ids)} max_items={max_items} lookback_hours={lookback_hours} labels={len(labels)}",
    )
    conn.close()
    return new_ids
