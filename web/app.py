"""Web PoC: multi-user social media manager over HTTP.

- Register/login (passwords hashed, session cookie).
- Per-user isolated data: each user gets their own SQLite DB + encrypted
  vault under SMM_DATA_DIR/users/<id>/ via smm.config.set_user_context.
- Consent flows for Upload-Post (LinkedIn + other platforms) and GitHub.
- Manual input mode (hint / file upload), review queue, audit log,
  publishing mode + schedule settings.
- Background scheduler thread runs each user's pipeline at their cadence.

Run:  .venv/bin/python web/app.py           (dev, port 5000)
      .venv/bin/waitress-serve --port=8080 web.app:app   (prod-ish)
"""
import json
import hmac
import os
import requests
import secrets
import sqlite3
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import (Flask, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from smm import consent, publisher, router, scheduler
from smm.config import (BASE_DIR, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET,
                        GITHUB_OAUTH_SCOPE, SCHEDULE_CHOICES,
                        SUPPORTED_PLATFORMS, set_user_context)
from smm.connectors import manual as manual_connector
from smm.storage import get_db as user_db

USERS_DB = BASE_DIR / "web_users.db"
SECRET_PATH = BASE_DIR / "web_secret.key"

BASE_DIR.mkdir(parents=True, exist_ok=True)
if not SECRET_PATH.exists():
    SECRET_PATH.write_text(secrets.token_hex(32))
    os.chmod(SECRET_PATH, 0o600)

app = Flask(__name__)
app.secret_key = SECRET_PATH.read_text().strip()
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB uploads


def users_db() -> sqlite3.Connection:
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, "
        "password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    return conn


# ------------------------------------------------------------------ auth ---

@app.before_request
def load_user():
    g.user_id = session.get("user_id")
    g.email = session.get("email")
    if g.user_id:
        set_user_context(g.user_id)  # isolate all smm data per user


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not g.user_id:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        if not email or len(password) < 8:
            flash("Email required; password must be at least 8 characters.", "error")
            return render_template("register.html")
        conn = users_db()
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "error")
            return render_template("register.html")
        finally:
            conn.close()
        session["user_id"] = cur.lastrowid
        session["email"] = email
        flash("Welcome! Start by connecting your publishing account.", "ok")
        return redirect(url_for("connections"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        conn = users_db()
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if row and check_password_hash(row["password_hash"], request.form["password"]):
            session["user_id"] = row["id"]
            session["email"] = email
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------- dashboard ---

@app.route("/")
@login_required
def dashboard():
    conn = user_db()
    pending = conn.execute(
        "SELECT COUNT(*) n FROM drafts WHERE status='pending'").fetchone()["n"]
    published = conn.execute(
        "SELECT COUNT(*) n FROM drafts WHERE status='published'").fetchone()["n"]
    unused = conn.execute("SELECT COUNT(*) n FROM signals WHERE used=0").fetchone()["n"]
    recent = conn.execute(
        "SELECT * FROM drafts WHERE status='published' ORDER BY id DESC LIMIT 5"
    ).fetchall()
    conn.close()
    return render_template(
        "dashboard.html",
        mode=router.get_mode(),
        schedule=scheduler.get_schedule(),
        pending=pending, published=published, unused=unused,
        connections=[c for c in consent.list_all() if c["status"] == "active"],
        recent=recent,
    )


@app.route("/draft", methods=["POST"])
@login_required
def create_draft():
    hint = request.form.get("hint", "").strip()
    upload = request.files.get("file")
    signal_ids = []
    if hint:
        signal_ids.append(manual_connector.add_hint(hint))
    if upload and upload.filename:
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in manual_connector.SUPPORTED_SUFFIXES:
            flash(f"Unsupported file type '{suffix}'.", "error")
            return redirect(url_for("dashboard"))
        tmp = Path(BASE_DIR) / "users" / str(g.user_id) / f"upload{suffix}"
        upload.save(tmp)
        try:
            signal_ids.append(manual_connector.add_file(str(tmp)))
        finally:
            tmp.unlink(missing_ok=True)  # manual uploads are not retained
    if not signal_ids:
        flash("Provide a hint or a file.", "error")
        return redirect(url_for("dashboard"))

    conn = user_db()
    qmarks = ",".join("?" * len(signal_ids))
    signals = [dict(r) for r in conn.execute(
        f"SELECT * FROM signals WHERE id IN ({qmarks})", signal_ids).fetchall()]
    from smm import drafting
    from smm.storage import add_draft
    text = drafting.draft_post(signals)
    draft_id = add_draft(conn, text, signal_ids, ["linkedin"])
    conn.execute(f"UPDATE signals SET used=1 WHERE id IN ({qmarks})", signal_ids)
    conn.commit()
    conn.close()
    outcome = router.route_draft(draft_id, ["manual"])
    flash(f"Draft #{draft_id} created → {outcome['routed'].replace('_', ' ')}.", "ok")
    return redirect(url_for("review"))


@app.route("/run-now", methods=["POST"])
@login_required
def run_now():
    result = scheduler.run_pipeline()
    outcome = result["outcome"]
    msg = f"Ingested: {result['ingested'] or 'no connected sources'}. "
    msg += (f"Draft #{outcome['draft_id']} → {outcome['routed'].replace('_', ' ')}."
            if outcome else "No new signals to draft from.")
    flash(msg, "ok")
    return redirect(url_for("dashboard"))


# ------------------------------------------------------------ connections ---

@app.route("/connections")
@login_required
def connections():
    return render_template(
        "connections.html",
        connections=consent.list_all(),
        platforms=SUPPORTED_PLATFORMS,
    )


@app.route("/connect/upload-post", methods=["POST"])
@login_required
def connect_upload_post():
    api_key = request.form.get("api_key", "").strip()
    username = request.form.get("username", "").strip()
    platforms = request.form.getlist("platforms")
    if not api_key or not username or not platforms:
        flash("API key, username, and at least one platform are required.", "error")
        return redirect(url_for("connections"))
    scopes = [f"publish:{p}" for p in platforms if p in SUPPORTED_PLATFORMS]
    if request.form.get("auto_publish") == "on":
        scopes.append("auto_publish")
    record = consent.grant("upload_post", scopes, meta={"platforms": platforms},
                           secrets={"api_key": api_key, "username": username})
    flash(f"Publishing connected for {', '.join(platforms)} "
          f"(consent expires {record['expires_at']}).", "ok")
    return redirect(url_for("connections"))


@app.route("/connect/github/start")
@login_required
def connect_github_start():
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        flash("GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and "
              "GITHUB_CLIENT_SECRET in .env.", "error")
        return redirect(url_for("connections"))

    state = secrets.token_urlsafe(32)
    session["github_oauth_state"] = state
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": url_for("connect_github_callback", _external=True),
        "scope": GITHUB_OAUTH_SCOPE,
        "state": state,
    }
    from urllib.parse import urlencode
    return redirect("https://github.com/login/oauth/authorize?" + urlencode(params))


@app.route("/connect/github/callback")
@login_required
def connect_github_callback():
    state = session.pop("github_oauth_state", None)
    if not state or not hmac.compare_digest(state, request.args.get("state", "")):
        flash("GitHub authorization could not be verified. Please try again.", "error")
        return redirect(url_for("connections"))
    if request.args.get("error"):
        flash("GitHub authorization was cancelled.", "error")
        return redirect(url_for("connections"))

    code = request.args.get("code", "")
    if not code:
        flash("GitHub did not return an authorization code.", "error")
        return redirect(url_for("connections"))

    try:
        token_resp = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={"client_id": GITHUB_CLIENT_ID,
                  "client_secret": GITHUB_CLIENT_SECRET, "code": code},
            timeout=20,
        )
        token_resp.raise_for_status()
        token = token_resp.json().get("access_token")
        if not token:
            raise ValueError(token_resp.json().get("error_description", "No access token returned"))

        profile_resp = requests.get(
            "https://api.github.com/user",
            headers={"Accept": "application/vnd.github+json",
                     "Authorization": f"Bearer {token}"},
            timeout=20,
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()
        username = profile.get("login")
        if not username:
            raise ValueError("GitHub profile did not include a username")
    except (requests.RequestException, ValueError) as exc:
        flash(f"GitHub connection failed: {exc}", "error")
        return redirect(url_for("connections"))

    record = consent.grant("github", ["read:activity"],
                           meta={"username": username},
                           secrets={"token": token})
    flash(f"GitHub connected as {username} (consent expires {record['expires_at']}).", "ok")
    return redirect(url_for("connections"))


@app.route("/disconnect/<provider>", methods=["POST"])
@login_required
def disconnect(provider):
    if provider not in ("upload_post", "github", "filesystem"):
        flash("Unknown provider.", "error")
    else:
        consent.revoke(provider)
        flash(f"'{provider}' disconnected: consent revoked, secrets and "
              "unused cached data purged.", "ok")
    return redirect(url_for("connections"))


# ----------------------------------------------------------------- review ---

@app.route("/review")
@login_required
def review():
    conn = user_db()
    drafts = [dict(r) for r in conn.execute(
        "SELECT * FROM drafts WHERE status='pending' ORDER BY id").fetchall()]
    conn.close()
    for d in drafts:
        d["platforms"] = json.loads(d["platforms"])
    return render_template("review.html", drafts=drafts)


@app.route("/review/<int:draft_id>", methods=["POST"])
@login_required
def review_action(draft_id):
    action = request.form["action"]
    conn = user_db()
    if action == "save":
        conn.execute("UPDATE drafts SET text=? WHERE id=?",
                     (request.form["text"].strip(), draft_id))
        conn.commit()
        flash(f"Draft #{draft_id} updated.", "ok")
    elif action == "reject":
        conn.execute("UPDATE drafts SET status='rejected' WHERE id=?", (draft_id,))
        conn.commit()
        flash(f"Draft #{draft_id} rejected.", "ok")
    elif action == "publish":
        new_text = request.form.get("text", "").strip()
        if new_text:
            conn.execute("UPDATE drafts SET text=? WHERE id=?", (new_text, draft_id))
            conn.commit()
        conn.close()
        try:
            publisher.publish_draft(draft_id)
            flash(f"Draft #{draft_id} published! 🎉", "ok")
        except (publisher.PublishError, consent.ConsentError) as e:
            flash(str(e), "error")
        return redirect(url_for("review"))
    conn.close()
    return redirect(url_for("review"))


# --------------------------------------------------------------- settings ---

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        try:
            router.set_mode(request.form["mode"])
            scheduler.set_schedule(int(request.form["runs_per_day"]))
            flash("Settings saved.", "ok")
        except (ValueError, consent.ConsentError) as e:
            flash(str(e), "error")
        return redirect(url_for("settings"))
    return render_template("settings.html", mode=router.get_mode(),
                           schedule=scheduler.get_schedule(),
                           choices=SCHEDULE_CHOICES)


@app.route("/audit")
@login_required
def audit():
    return render_template("audit.html", connections=consent.list_all(),
                           ledger=consent.audit_log(limit=100))


# -------------------------------------------------------------- scheduler ---

def scheduler_loop(poll_seconds: int = 60):
    """Background thread: run each user's pipeline when their cadence is due."""
    while True:
        try:
            conn = users_db()
            user_ids = [r["id"] for r in conn.execute("SELECT id FROM users").fetchall()]
            conn.close()
            for uid in user_ids:
                set_user_context(uid)
                try:
                    scheduler.run_due()
                except Exception as e:  # noqa: BLE001 — one user must not break others
                    print(f"[scheduler] user {uid} run failed: {e}")
            set_user_context(None)
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] loop error: {e}")
        time.sleep(poll_seconds)


threading.Thread(target=scheduler_loop, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
