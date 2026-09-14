"""Configuration and per-user data paths.

Multi-user support: a context variable selects the active user's data
directory. CLI mode uses the base directory (single local user); the web app
calls set_user_context(user_id) per request so every user's DB and vault are
fully isolated on disk.
"""
import contextvars
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(os.getenv("SMM_DATA_DIR", str(Path.home() / ".smm")))

_user_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "smm_user_dir", default=None
)


def set_user_context(user_id: str | int | None) -> None:
    """Select the active user's data dir (None = base/local single user)."""
    _user_ctx.set(str(user_id) if user_id is not None else None)


def data_dir() -> Path:
    uid = _user_ctx.get()
    d = BASE_DIR / "users" / uid if uid else BASE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "smm.db"


def vault_path() -> Path:
    return data_dir() / "vault.enc"


def vault_key_path() -> Path:
    return data_dir() / "vault.key"


# Consent defaults
CONSENT_TTL_DAYS = int(os.getenv("SMM_CONSENT_TTL_DAYS", "90"))

# Auto-publish guardrails
AUTO_PUBLISH_MAX_PER_DAY = int(os.getenv("SMM_AUTO_MAX_PER_DAY", "1"))
BLOCKLIST = [
    w.strip().lower()
    for w in os.getenv("SMM_BLOCKLIST", "salary,confidential,secret,api key,password").split(",")
    if w.strip()
]

# Drafting
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("SMM_OPENAI_MODEL", "gpt-4o-mini")
MAX_SIGNAL_CONTENT = 1000  # chars of raw content kept per signal

# GitHub OAuth (the client secret must never be committed)
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_OAUTH_SCOPE = os.getenv("GITHUB_OAUTH_SCOPE", "read:user repo")

# Upload-Post (unified publisher: LinkedIn + 21 other platforms)
UPLOAD_POST_URL = "https://api.upload-post.com/api/upload_text"
SUPPORTED_PLATFORMS = [
    "linkedin", "x", "threads", "bluesky", "facebook", "reddit",
    "telegram", "discord", "mastodon", "pinterest",
]

# Scheduling: allowed runs-per-day choices (0 = scheduling off)
SCHEDULE_CHOICES = [0, 1, 2, 3, 4, 6, 12, 24]
