"""Consent-gated Google Drive ingestion scoped by an application folder policy."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import quote

from pypdf import PdfReader

from app.config.settings import GOOGLE_MAX_DOWNLOAD_BYTES
from app.modules.integrations import service as consent
from app.modules.integrations.providers import google_oauth
from app.modules.integrations.providers.cleaning import clean_text, clean_title
from app.shared.database.session import add_signal_once, get_db, log_ledger

API = "https://www.googleapis.com/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
PDF_MIME = "application/pdf"
TEXT_MIMES = {"text/plain", "text/markdown", "text/x-markdown"}
SUPPORTED_MIMES = {DOC_MIME, PDF_MIME, *TEXT_MIMES}
MAX_FOLDER_VISITS = 200
MAX_ENTRIES = 2000


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def list_folders(query: str = "") -> list[dict]:
    consent.require("google_drive", "https://www.googleapis.com/auth/drive.readonly")
    filters = [f"mimeType='{FOLDER_MIME}'", "trashed=false"]
    if query.strip():
        filters.append(f"name contains '{_escape_query(query.strip())}'")
    response = google_oauth.api_request(
        "google_drive", "GET", API,
        params={"q": " and ".join(filters), "pageSize": 100,
                "orderBy": "name", "fields": "files(id,name,parents)"},
    )
    if response.status_code != 200:
        raise google_oauth.GoogleProviderError("Drive folders could not be loaded.")
    return google_oauth.response_json(response, "Drive returned invalid folder data.").get("files", [])


def _folder_children(folder_id: str) -> list[dict]:
    files: list[dict] = []
    page_token = ""
    while True:
        params = {
            "q": f"'{_escape_query(folder_id)}' in parents and trashed=false",
            "pageSize": 100,
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,size)",
        }
        if page_token:
            params["pageToken"] = page_token
        response = google_oauth.api_request("google_drive", "GET", API, params=params)
        if response.status_code != 200:
            raise google_oauth.GoogleProviderError("Drive folder contents could not be loaded.")
        payload = google_oauth.response_json(response, "Drive returned invalid file data.")
        files.extend(payload.get("files", []))
        page_token = payload.get("nextPageToken", "")
        if not page_token:
            return files


def _recent_files(folder_id: str, lookback_hours: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    queue = deque([folder_id])
    visited: set[str] = set()
    candidates: list[dict] = []
    entries = 0
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if len(visited) > MAX_FOLDER_VISITS:
            raise google_oauth.GoogleProviderError(
                "The selected Drive folder is too large; choose a narrower folder."
            )
        children = _folder_children(current)
        entries += len(children)
        if entries > MAX_ENTRIES:
            raise google_oauth.GoogleProviderError(
                "The selected Drive folder contains too many entries; choose a narrower folder."
            )
        for item in children:
            if item.get("mimeType") == FOLDER_MIME:
                queue.append(item["id"])
                continue
            if item.get("mimeType") not in SUPPORTED_MIMES or not item.get("modifiedTime"):
                continue
            if datetime.fromisoformat(item["modifiedTime"].replace("Z", "+00:00")) >= cutoff:
                candidates.append(item)
    candidates.sort(key=lambda item: item["modifiedTime"], reverse=True)
    return candidates


def _bounded_content(response) -> bytes:
    length = response.headers.get("Content-Length")
    if length and int(length) > GOOGLE_MAX_DOWNLOAD_BYTES:
        raise google_oauth.GoogleProviderError("A Drive file exceeded the 5 MB download limit.")
    content = response.content
    if len(content) > GOOGLE_MAX_DOWNLOAD_BYTES:
        raise google_oauth.GoogleProviderError("A Drive file exceeded the 5 MB download limit.")
    return content


def _extract(item: dict) -> str:
    file_id = item["id"]
    mime = item["mimeType"]
    if mime == DOC_MIME:
        response = google_oauth.api_request(
            "google_drive", "GET", f"{API}/{file_id}/export",
            params={"mimeType": "text/plain"},
        )
    else:
        response = google_oauth.api_request(
            "google_drive", "GET", f"{API}/{file_id}", params={"alt": "media"}
        )
    if response.status_code != 200:
        raise google_oauth.GoogleProviderError("A selected Drive file could not be read.")
    content = _bounded_content(response)
    if mime == PDF_MIME:
        try:
            reader = PdfReader(BytesIO(content))
            return "\n".join((page.extract_text() or "") for page in reader.pages[:20])
        except Exception as exc:  # pypdf exposes several parser-specific errors.
            raise google_oauth.GoogleProviderError("A selected PDF could not be parsed.") from exc
    return content.decode("utf-8", errors="ignore")


def ingest(*, max_items: int, lookback_hours: int, folder_id: str) -> list[int]:
    consent.require("google_drive", "https://www.googleapis.com/auth/drive.readonly")
    if not folder_id:
        raise google_oauth.GoogleProviderError("Choose a Drive folder before running ingestion.")
    candidates = _recent_files(folder_id, lookback_hours)[:max_items]
    conn = get_db()
    new_ids: list[int] = []
    skipped = 0
    for item in candidates:
        try:
            content = clean_text(_extract(item))
        except google_oauth.GoogleProviderError:
            skipped += 1
            continue
        version = quote(item["modifiedTime"], safe="")
        citation = item.get("webViewLink") or f"https://drive.google.com/open?id={item['id']}"
        signal_id = add_signal_once(
            conn, "google_drive", "file", clean_title(item["name"]), content=content,
            url=f"{citation}#smm-version={version}", ts=item["modifiedTime"],
        )
        if signal_id:
            new_ids.append(signal_id)
    log_ledger(
        conn, "google_drive", "ingest",
        f"new_signals={len(new_ids)} skipped={skipped} max_items={max_items} lookback_hours={lookback_hours}",
    )
    conn.close()
    return new_ids
