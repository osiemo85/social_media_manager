"""GitHub connector — read-only signal source (consent-gated).

Pulls the user's recent public events (pushes, merged PRs, releases) via the
GitHub REST API. Works unauthenticated for public activity; an optional PAT
(stored encrypted in the vault) raises rate limits and enables private repos.
"""
import requests

from .. import consent, vault
from ..config import MAX_SIGNAL_CONTENT
from ..storage import add_signal, get_db, log_ledger

API = "https://api.github.com"

INTERESTING = {
    "PushEvent": "push",
    "PullRequestEvent": "pull_request",
    "ReleaseEvent": "release",
    "CreateEvent": "repo_created",
}


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    secrets = vault.get_secret("github")
    if secrets and secrets.get("token"):
        headers["Authorization"] = f"Bearer {secrets['token']}"
    return headers


def _ingest_via_repos(conn, seen: set, username: str, days: int = 7) -> list[int]:
    """Authenticated path: recently pushed repos + their commits.

    Reliable for private repos (the public events feed is not), and much
    fresher than /users/<u>/events which can lag by minutes/hours.
    """
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")

    resp = requests.get(
        f"{API}/user/repos", headers=_headers(),
        params={"sort": "pushed", "per_page": 10, "affiliation": "owner"},
        timeout=20,
    )
    resp.raise_for_status()

    new_ids = []
    for repo in resp.json():
        if repo.get("pushed_at", "") < since:
            continue
        full = repo["full_name"]
        commits_resp = requests.get(
            f"{API}/repos/{full}/commits", headers=_headers(),
            params={"since": since, "per_page": 5, "author": username},
            timeout=20,
        )
        if commits_resp.status_code != 200:
            continue
        commits = commits_resp.json()
        if not commits:
            continue
        latest_sha = commits[0]["sha"][:12]
        key = f"https://github.com/{full}|push:{latest_sha}"
        if key in seen:
            continue
        seen.add(key)
        msgs = "; ".join(
            c["commit"]["message"].splitlines()[0] for c in commits
        )[:MAX_SIGNAL_CONTENT]
        visibility = "private " if repo.get("private") else ""
        title = f"Pushed {len(commits)} commit(s) to {visibility}repo {full}"
        sid = add_signal(conn, "github", "push", title, content=msgs, url=key,
                         ts=commits[0]["commit"]["author"]["date"])
        new_ids.append(sid)
    return new_ids


def ingest(limit: int = 30) -> list[int]:
    """Fetch recent GitHub activity and store new signals. Returns signal ids."""
    record = consent.require("github", scope="read:activity")
    username = record["meta"]["username"]

    conn = get_db()
    seen = {
        r["url"]
        for r in conn.execute("SELECT url FROM signals WHERE source='github'").fetchall()
    }

    secrets = vault.get_secret("github")
    if secrets and secrets.get("token"):
        new_ids = _ingest_via_repos(conn, seen, username)
        log_ledger(conn, "github", "ingest", f"new_signals={len(new_ids)} via=repos_api")
        conn.close()
        return new_ids

    resp = requests.get(
        f"{API}/users/{username}/events",
        headers=_headers(),
        params={"per_page": limit},
        timeout=20,
    )
    resp.raise_for_status()
    events = resp.json()

    new_ids = []
    for ev in events:
        etype = INTERESTING.get(ev.get("type", ""))
        if not etype:
            continue
        repo = ev.get("repo", {}).get("name", "")
        payload = ev.get("payload", {})

        if etype == "push":
            commits = payload.get("commits", [])
            if not commits:
                continue
            msgs = "; ".join(c.get("message", "").splitlines()[0] for c in commits[:5])
            title = f"Pushed {len(commits)} commit(s) to {repo}"
            content, url = msgs, f"https://github.com/{repo}"
        elif etype == "pull_request":
            pr = payload.get("pull_request", {})
            if payload.get("action") != "closed" or not pr.get("merged"):
                continue
            title = f"Merged PR in {repo}: {pr.get('title', '')}"
            content, url = (pr.get("body") or "")[:MAX_SIGNAL_CONTENT], pr.get("html_url", "")
        elif etype == "release":
            rel = payload.get("release", {})
            title = f"Released {rel.get('tag_name', '')} in {repo}"
            content, url = (rel.get("body") or "")[:MAX_SIGNAL_CONTENT], rel.get("html_url", "")
        else:  # repo_created
            if payload.get("ref_type") != "repository":
                continue
            title = f"Created new repository {repo}"
            content, url = "", f"https://github.com/{repo}"

        # Dedup key: url + title
        key = url + "|" + title
        if key in seen:
            continue
        seen.add(key)
        sid = add_signal(conn, "github", etype, title,
                         content=content, url=key, ts=ev.get("created_at"))
        new_ids.append(sid)

    log_ledger(conn, "github", "ingest", f"new_signals={len(new_ids)}")
    conn.close()
    return new_ids
