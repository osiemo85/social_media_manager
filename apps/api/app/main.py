"""FastAPI HTTP boundary for the consent-first Social Media Manager."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

import requests
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import check_password_hash, generate_password_hash
from pydantic import BaseModel, Field

from app.config.settings import (BASE_DIR, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET,
                                 GITHUB_OAUTH_SCOPE, SCHEDULE_CHOICES,
                                 SOURCE_DEFAULTS, SOURCE_LOOKBACK_CHOICES,
                                 SOURCE_MAX_ITEMS, SUPPORTED_PLATFORMS,
                                 set_user_context)
from app.modules.content import service as drafting
from app.modules.integrations import service as consent
from app.modules.integrations.providers import manual as manual_connector
from app.modules.integrations.providers import gmail as gmail_connector
from app.modules.integrations.providers import google_drive as drive_connector
from app.modules.integrations.providers import google_oauth
from app.modules.publishing import service as publisher
from app.modules.publishing import state_machine as router
from app.shared.database.session import add_draft, get_db, get_latest_published_post
from app.workers.tasks import pipeline as scheduler

USERS_DB = BASE_DIR / "web_users.db"
SECRET_PATH = BASE_DIR / "web_secret.key"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


class SourceRunOption(BaseModel):
    enabled: bool = True
    max_items: int | None = Field(default=None, ge=1, le=SOURCE_MAX_ITEMS)
    lookback_hours: int | None = None


class PipelineRunRequest(BaseModel):
    sources: dict[str, SourceRunOption] = Field(default_factory=dict)


class SourcePolicyUpdate(BaseModel):
    max_items: int = Field(ge=1, le=SOURCE_MAX_ITEMS)
    lookback_hours: int
    scheduled_enabled: bool = False
    label_ids: list[str] | None = None
    folder_id: str | None = None
    folder_name: str | None = None


def users_db() -> sqlite3.Connection:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    return conn


def _session_secret() -> str:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_hex(32))
        os.chmod(SECRET_PATH, 0o600)
    return SECRET_PATH.read_text().strip()


def current_user(request: Request) -> dict:
    user_id = request.session.get("user_id")
    email = request.session.get("email")
    if not user_id or not email:
        raise HTTPException(401, "Authentication is required.")
    # This is the sole tenancy selector; no client-supplied tenant is trusted.
    set_user_context(user_id)
    return {"id": int(user_id), "email": email}


def error(exc: Exception) -> HTTPException:
    return HTTPException(400, str(exc))


def public_connection(item: dict) -> dict:
    return {**item, "meta": {
        key: value for key, value in item.get("meta", {}).items()
        if key != "google_sub"
    }}


def scheduler_loop() -> None:
    while True:
        try:
            conn = users_db()
            ids = [row["id"] for row in conn.execute("SELECT id FROM users")]
            conn.close()
            for user_id in ids:
                set_user_context(user_id)
                try:
                    scheduler.run_due()
                except Exception:  # An individual tenant cannot stop the worker.
                    pass
        finally:
            set_user_context(None)
            time.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    thread = threading.Thread(target=scheduler_loop, daemon=True, name="smm-scheduler")
    thread.start()
    yield


app = FastAPI(title="Social Media Manager API", version="1.0.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=_session_secret(), https_only=os.getenv("SMM_COOKIE_SECURE", "false").lower() == "true", same_site="lax")
# Next proxies /api in development. This permits a separately hosted web app too.
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("WEB_ORIGIN", "http://localhost:3000")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(request: Request, email: str = Form(), password: str = Form()) -> dict:
    email = email.strip().lower()
    if not email or len(password) < 8:
        raise HTTPException(422, "Email is required and password must be at least 8 characters.")
    conn = users_db()
    try:
        cur = conn.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, generate_password_hash(password)))
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "That email is already registered.") from exc
    finally:
        conn.close()
    request.session.update({"user_id": cur.lastrowid, "email": email})
    return {"user": {"id": cur.lastrowid, "email": email}}


@app.post("/api/auth/login")
def login(request: Request, email: str = Form(), password: str = Form()) -> dict:
    conn = users_db()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    conn.close()
    if not row or not check_password_hash(row["password_hash"], password):
        raise HTTPException(401, "Invalid email or password.")
    request.session.update({"user_id": row["id"], "email": row["email"]})
    return {"user": {"id": row["id"], "email": row["email"]}}


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request) -> None:
    request.session.clear()


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {"user": user}


@app.get("/api/dashboard")
def dashboard(_: dict = Depends(current_user)) -> dict:
    conn = get_db()
    counts = {name: conn.execute("SELECT COUNT(*) n FROM drafts WHERE status=?", (name,)).fetchone()["n"] for name in ("pending", "published")}
    unused = conn.execute("SELECT COUNT(*) n FROM signals WHERE used=0").fetchone()["n"]
    recent = [dict(row) for row in conn.execute(
        "SELECT * FROM drafts WHERE status='published' ORDER BY published_at DESC, id DESC LIMIT 5"
    )]
    conn.close()
    return {"pending": counts["pending"], "published": counts["published"], "unused": unused, "mode": router.get_mode(), "schedule": scheduler.get_schedule(), "connections": [public_connection(item) for item in consent.list_all() if item["status"] == "active"], "recent": recent}


@app.post("/api/drafts")
async def create_draft(hint: str = Form(""), file: UploadFile | None = File(None), _: dict = Depends(current_user)) -> dict:
    signal_ids: list[int] = []
    if hint.strip():
        signal_ids.append(manual_connector.add_hint(hint.strip()))
    if file and file.filename:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in manual_connector.SUPPORTED_SUFFIXES:
            raise HTTPException(422, f"Unsupported file type '{suffix}'.")
        contents = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Files must be 2 MB or smaller.")
        # Keep uploads only long enough for the established manual connector.
        path = BASE_DIR / "users" / str(_.get("id")) / f"upload-{secrets.token_hex(8)}{suffix}"
        path.write_bytes(contents)
        try:
            signal_ids.append(manual_connector.add_file(str(path)))
        finally:
            path.unlink(missing_ok=True)
    if not signal_ids:
        raise HTTPException(422, "Provide a hint or a supported file.")
    conn = get_db()
    marks = ",".join("?" * len(signal_ids))
    signals = [dict(row) for row in conn.execute(f"SELECT * FROM signals WHERE id IN ({marks})", signal_ids)]
    previous_published_post = get_latest_published_post(conn)
    # The Agents SDK synchronous runner must not block FastAPI's event loop.
    draft_text = await asyncio.to_thread(drafting.draft_post, signals, previous_published_post)
    draft_id = add_draft(conn, draft_text, signal_ids, ["linkedin"])
    conn.execute(f"UPDATE signals SET used=1 WHERE id IN ({marks})", signal_ids)
    conn.commit(); conn.close()
    outcome = router.route_draft(draft_id, ["manual"])
    return {"draft_id": draft_id, **outcome}


@app.post("/api/pipeline/run")
def run_pipeline(request: PipelineRunRequest | None = Body(default=None),
                 _: dict = Depends(current_user)) -> dict:
    selected = None
    if request is not None and request.sources:
        allowed = {"github", "filesystem", "gmail", "google_drive"}
        unknown = set(request.sources) - allowed
        if unknown:
            raise HTTPException(422, f"Unsupported source(s): {sorted(unknown)}")
        selected = {
            name: options.model_dump(exclude_none=True)
            for name, options in request.sources.items()
        }
        for name, options in selected.items():
            lookback = options.get("lookback_hours")
            if lookback is not None and lookback not in SOURCE_LOOKBACK_CHOICES:
                raise HTTPException(422, f"{name} lookback_hours must be one of {SOURCE_LOOKBACK_CHOICES}")
    return scheduler.run_pipeline(selected_sources=selected)


@app.get("/api/drafts")
def list_drafts(status: Literal["pending", "published", "rejected"] = "pending", _: dict = Depends(current_user)) -> dict:
    conn = get_db()
    drafts = []
    for row in conn.execute("SELECT * FROM drafts WHERE status=? ORDER BY id", (status,)):
        draft = dict(row)
        ids = json.loads(draft.get("signal_ids") or "[]")
        citations = []
        if ids:
            marks = ",".join("?" * len(ids))
            citations = [
                {"source": source["source"], "title": source["title"],
                 "timestamp": source["ts"],
                 "url": source["url"].split("#smm-version=", 1)[0]}
                for source in conn.execute(
                    f"SELECT source,title,ts,url FROM signals WHERE id IN ({marks}) ORDER BY ts DESC",
                    ids,
                )
            ]
        draft["citations"] = citations
        drafts.append(draft)
    conn.close()
    return {"drafts": drafts}


@app.patch("/api/drafts/{draft_id}")
async def update_draft(draft_id: int, request: Request, _: dict = Depends(current_user)) -> dict:
    body = await request.json(); text = str(body.get("text", "")).strip()
    if not text: raise HTTPException(422, "Draft text cannot be empty.")
    conn = get_db(); changed = conn.execute("UPDATE drafts SET text=? WHERE id=? AND status='pending'", (text, draft_id)).rowcount; conn.commit(); conn.close()
    if not changed: raise HTTPException(404, "Pending draft not found.")
    return {"draft_id": draft_id, "text": text}


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: int, _: dict = Depends(current_user)) -> dict:
    conn = get_db(); changed = conn.execute("UPDATE drafts SET status='rejected' WHERE id=? AND status='pending'", (draft_id,)).rowcount; conn.commit(); conn.close()
    if not changed: raise HTTPException(404, "Pending draft not found.")
    return {"draft_id": draft_id, "status": "rejected"}


@app.post("/api/drafts/{draft_id}/publish")
def publish_draft(draft_id: int, _: dict = Depends(current_user)) -> dict:
    try: return publisher.publish_draft(draft_id)
    except (publisher.PublishError, consent.ConsentError) as exc: raise error(exc) from exc


@app.get("/api/connections")
def connections(_: dict = Depends(current_user)) -> dict:
    items = []
    for item in consent.list_all():
        items.append(public_connection(item))
    return {
        "connections": items,
        "platforms": SUPPORTED_PLATFORMS,
        "source_defaults": SOURCE_DEFAULTS,
        "lookback_choices": SOURCE_LOOKBACK_CHOICES,
        "source_max_items": SOURCE_MAX_ITEMS,
    }


@app.post("/api/connections/upload-post")
def connect_upload_post(api_key: str = Form(), username: str = Form(), platforms: list[str] = Form(), auto_publish: bool = Form(False), _: dict = Depends(current_user)) -> dict:
    allowed = [platform for platform in platforms if platform in SUPPORTED_PLATFORMS]
    if not api_key.strip() or not username.strip() or not allowed: raise HTTPException(422, "API key, username, and one supported platform are required.")
    scopes = [f"publish:{platform}" for platform in allowed] + (["auto_publish"] if auto_publish else [])
    return consent.grant("upload_post", scopes, meta={"platforms": allowed}, secrets={"api_key": api_key.strip(), "username": username.strip()})


@app.get("/api/connections/github/start")
def github_start(request: Request, _: dict = Depends(current_user)) -> dict:
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET: raise HTTPException(503, "GitHub OAuth is not configured.")
    state = secrets.token_urlsafe(32); request.session["github_oauth_state"] = state
    # The callback deliberately goes through Next's /api proxy so the browser
    # retains the same-origin session cookie established during login.
    callback = os.getenv("WEB_ORIGIN", "http://localhost:3000").rstrip("/") + "/api/connections/github/callback"
    return {"authorization_url": "https://github.com/login/oauth/authorize?" + urlencode({"client_id": GITHUB_CLIENT_ID, "redirect_uri": callback, "scope": GITHUB_OAUTH_SCOPE, "state": state})}


@app.get("/api/connections/github/callback")
def github_callback(request: Request, state: str = "", code: str = "", _: dict = Depends(current_user)) -> RedirectResponse:
    expected = request.session.pop("github_oauth_state", "")
    if not expected or not hmac.compare_digest(expected, state): raise HTTPException(400, "GitHub authorization could not be verified.")
    try:
        token = requests.post("https://github.com/login/oauth/access_token", headers={"Accept": "application/json"}, data={"client_id": GITHUB_CLIENT_ID, "client_secret": GITHUB_CLIENT_SECRET, "code": code}, timeout=20).json().get("access_token")
        profile = requests.get("https://api.github.com/user", headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}, timeout=20).json()
        if not token or not profile.get("login"): raise ValueError("GitHub did not return a usable account.")
    except (requests.RequestException, ValueError) as exc: raise HTTPException(502, "GitHub connection failed.") from exc
    consent.grant("github", ["read:activity"], meta={"username": profile["login"]}, secrets={"token": token})
    return RedirectResponse(os.getenv("WEB_ORIGIN", "http://localhost:3000").rstrip("/") + "/?github=connected", status_code=303)


def _google_callback_url() -> str:
    return os.getenv("WEB_ORIGIN", "http://localhost:3000").rstrip("/") + "/api/connections/google/callback"


@app.get("/api/connections/{provider}/start")
def google_start(provider: Literal["gmail", "google-drive"], request: Request,
                 _: dict = Depends(current_user)) -> dict:
    internal = "google_drive" if provider == "google-drive" else provider
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    request.session["google_oauth"] = {
        "state": state, "provider": internal, "verifier": verifier,
    }
    try:
        url = google_oauth.authorization_url(internal, state, _google_callback_url(), challenge)
    except google_oauth.GoogleProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"authorization_url": url}


@app.get("/api/connections/google/callback")
def google_callback(request: Request, state: str = "", code: str = "",
                    oauth_error: str = Query(default="", alias="error"),
                    _: dict = Depends(current_user)) -> RedirectResponse:
    pending = request.session.pop("google_oauth", {})
    if oauth_error:
        raise HTTPException(400, "Google authorization was cancelled.")
    if not pending or not hmac.compare_digest(str(pending.get("state", "")), state):
        raise HTTPException(400, "Google authorization could not be verified.")
    provider = str(pending["provider"])
    try:
        secret, profile = google_oauth.exchange_code(
            provider, code, _google_callback_url(), str(pending["verifier"])
        )
    except google_oauth.GoogleProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    meta = {
        "account": profile["email"],
        "google_sub": profile["sub"],
        "grant_method": "oauth_web",
        "retention": "source text cleared after drafting",
        "revocation_url": "https://myaccount.google.com/connections",
        "policy": SOURCE_DEFAULTS[provider],
    }
    consent.grant(provider, google_oauth.SCOPES[provider], meta=meta, secrets=secret)
    label = "drive" if provider == "google_drive" else provider
    return RedirectResponse(
        os.getenv("WEB_ORIGIN", "http://localhost:3000").rstrip("/")
        + f"/connections?{label}=connected", status_code=303,
    )


@app.get("/api/connections/gmail/labels")
def gmail_labels(_: dict = Depends(current_user)) -> dict:
    try:
        return {"labels": gmail_connector.list_labels()}
    except (consent.ConsentError, google_oauth.GoogleProviderError) as exc:
        raise error(exc) from exc


@app.get("/api/connections/google-drive/folders")
def drive_folders(q: str = "", _: dict = Depends(current_user)) -> dict:
    try:
        return {"folders": drive_connector.list_folders(q[:100])}
    except (consent.ConsentError, google_oauth.GoogleProviderError) as exc:
        raise error(exc) from exc


@app.put("/api/connections/{provider}/settings")
def source_settings(provider: Literal["gmail", "google_drive"], body: SourcePolicyUpdate,
                    _: dict = Depends(current_user)) -> dict:
    values = body.model_dump(exclude_none=True)
    try:
        return {"policy": consent.set_source_policy(provider, values)}
    except (ValueError, consent.ConsentError) as exc:
        raise error(exc) from exc


@app.delete("/api/connections/{provider}")
def disconnect(provider: Literal["upload_post", "github", "filesystem", "gmail", "google_drive"], _: dict = Depends(current_user)) -> None:
    if provider in {"gmail", "google_drive"}:
        google_oauth.disconnect(provider)
    else:
        consent.revoke(provider)


@app.get("/api/settings")
def get_settings(_: dict = Depends(current_user)) -> dict:
    return {"mode": router.get_mode(), "runs_per_day": scheduler.get_schedule(), "schedule_choices": SCHEDULE_CHOICES}


@app.put("/api/settings")
async def save_settings(request: Request, _: dict = Depends(current_user)) -> dict:
    body = await request.json()
    try:
        router.set_mode(body["mode"]); scheduler.set_schedule(int(body["runs_per_day"]))
    except (KeyError, ValueError, consent.ConsentError) as exc: raise error(exc) from exc
    return get_settings(_)


@app.get("/api/audit")
def audit(_: dict = Depends(current_user)) -> dict:
    return {"connections": consent.list_all(), "ledger": consent.audit_log(limit=100)}
