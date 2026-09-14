"""SQLite storage: consent records, audit ledger, signals, drafts, settings."""
import json
import sqlite3
from datetime import datetime, timezone

from app.config.settings import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS consent (
    provider    TEXT PRIMARY KEY,
    scopes      TEXT NOT NULL,
    granted_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS ledger (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    provider TEXT NOT NULL,
    action   TEXT NOT NULL,
    details  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS signals (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source  TEXT NOT NULL,
    type    TEXT NOT NULL,
    title   TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    url     TEXT NOT NULL DEFAULT '',
    ts      TEXT NOT NULL,
    used    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS drafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    signal_ids   TEXT NOT NULL DEFAULT '[]',
    text         TEXT NOT NULL,
    platforms    TEXT NOT NULL DEFAULT '["linkedin"]',
    status       TEXT NOT NULL DEFAULT 'pending',
    published_at TEXT,
    post_result  TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def log_ledger(conn: sqlite3.Connection, provider: str, action: str, details: str = "") -> None:
    conn.execute(
        "INSERT INTO ledger (ts, provider, action, details) VALUES (?, ?, ?, ?)",
        (now_iso(), provider, action, details),
    )
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def add_signal(conn, source: str, type_: str, title: str,
               content: str = "", url: str = "", ts: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO signals (source, type, title, content, url, ts) VALUES (?, ?, ?, ?, ?, ?)",
        (source, type_, title, content, url, ts or now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def add_draft(conn, text: str, signal_ids: list[int], platforms: list[str]) -> int:
    cur = conn.execute(
        "INSERT INTO drafts (created_at, signal_ids, text, platforms) VALUES (?, ?, ?, ?)",
        (now_iso(), json.dumps(signal_ids), text, json.dumps(platforms)),
    )
    conn.commit()
    return cur.lastrowid
