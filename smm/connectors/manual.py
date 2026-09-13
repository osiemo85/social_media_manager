"""Manual input connector — the no-access path.

Requires NO consent, NO tokens: users supply hints, pasted text, or files
directly. Content becomes a `source: manual` signal used only for drafting.
"""
from pathlib import Path

from ..config import MAX_SIGNAL_CONTENT
from ..storage import add_signal, get_db

SUPPORTED_SUFFIXES = {".md", ".txt", ".py", ".ipynb", ".json", ".rst", ".csv"}


def add_hint(hint: str) -> int:
    """Store a short free-text hint as a manual signal."""
    conn = get_db()
    sid = add_signal(conn, "manual", "hint", hint[:120], content=hint[:MAX_SIGNAL_CONTENT * 4])
    conn.close()
    return sid


def add_file(path: str) -> int:
    """Ingest a user-supplied file as a manual signal (content truncated)."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {p}")
    if p.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type '{p.suffix}'. "
                         f"Supported: {sorted(SUPPORTED_SUFFIXES)}")
    content = p.read_text(encoding="utf-8", errors="ignore")[:MAX_SIGNAL_CONTENT * 4]
    conn = get_db()
    sid = add_signal(conn, "manual", "file", f"Uploaded: {p.name}", content=content)
    conn.close()
    return sid
