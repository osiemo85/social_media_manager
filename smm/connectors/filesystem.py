"""Filesystem connector — recent locally modified files as signals (consent-gated).

Adapted from the user's original get_recent_files_context tool. Only reads
inside the explicitly allowlisted directories recorded at consent time.
"""
import json
import time
from pathlib import Path

from .. import consent
from ..config import MAX_SIGNAL_CONTENT
from ..storage import add_signal, get_db, log_ledger

ALLOWED_EXTENSIONS = (".py", ".ipynb", ".md")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".smm"}


def _read_content(path: Path) -> str:
    if path.suffix == ".ipynb":
        try:
            notebook = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except json.JSONDecodeError:
            return ""
        cells = [
            "".join(c.get("source", []))
            for c in notebook.get("cells", [])
            if c.get("cell_type") == "code"
        ]
        return "\n\n".join(cells)
    return path.read_text(encoding="utf-8", errors="ignore")


def ingest(hours: int = 24) -> list[int]:
    """Scan allowlisted paths for files modified in the last N hours."""
    record = consent.require("filesystem", scope="read:paths")
    allowlist = [Path(p).expanduser().resolve() for p in record["meta"]["paths"]]
    cutoff = time.time() - hours * 3600

    conn = get_db()
    new_ids = []
    for base in allowlist:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file() or path.suffix not in ALLOWED_EXTENSIONS:
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    continue
                content = _read_content(path)[:MAX_SIGNAL_CONTENT]
            except OSError:
                continue
            sid = add_signal(
                conn, "filesystem", "file_modified",
                f"Worked on {path.name}", content=content, url=str(path),
            )
            new_ids.append(sid)

    log_ledger(conn, "filesystem", "ingest", f"new_signals={len(new_ids)} hours={hours}")
    conn.close()
    return new_ids
