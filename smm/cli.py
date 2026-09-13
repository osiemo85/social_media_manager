"""smm CLI — connect / ingest / draft / review / publish / mode / audit / disconnect."""
import json
import sys

import click
import requests

from . import consent as consent_mod
from . import drafting, publisher, router, scheduler
from .config import SCHEDULE_CHOICES, SUPPORTED_PLATFORMS
from .connectors import filesystem as fs_connector
from .connectors import github as gh_connector
from .connectors import manual as manual_connector
from .storage import add_draft, get_db


@click.group()
def cli():
    """Social Media Manager — consent-first social posting agent (PoC)."""


# ---------------------------------------------------------------- connect ---

@cli.group()
def connect():
    """Grant consent and connect a source or the publisher."""


@connect.command("linkedin")
def connect_linkedin():
    """Connect LinkedIn (and optionally more platforms) via Upload-Post.

    OAuth to each platform happens on your Upload-Post account
    (https://app.upload-post.com) — you supply only your Upload-Post API key,
    which is stored encrypted in the local vault.
    """
    click.echo("Publishing is handled via Upload-Post (https://www.upload-post.com).")
    click.echo("1. Create an account and connect LinkedIn (and any other platforms) there.")
    click.echo("2. Copy your API key and profile username.\n")
    api_key = click.prompt("Upload-Post API key", hide_input=True)
    username = click.prompt("Upload-Post username")

    click.echo(f"\nAvailable platforms: {', '.join(SUPPORTED_PLATFORMS)}")
    platforms_raw = click.prompt("Platforms to allow publishing to (comma-separated)",
                                 default="linkedin")
    platforms = [p.strip().lower() for p in platforms_raw.split(",") if p.strip()]
    bad = [p for p in platforms if p not in SUPPORTED_PLATFORMS]
    if bad:
        raise click.ClickException(f"Unsupported platform(s): {bad}")

    scopes = [f"publish:{p}" for p in platforms]
    if click.confirm("Also allow AUTO-publish (agent may post without per-post "
                     "approval, subject to guardrails)?", default=False):
        scopes.append("auto_publish")

    record = consent_mod.grant("upload_post", scopes,
                               meta={"platforms": platforms},
                               secrets={"api_key": api_key, "username": username})
    click.echo(f"\n✓ Consent granted for platforms {platforms} "
               f"(expires {record['expires_at']}).")
    click.echo("  Revoke anytime with: agent disconnect linkedin")


@connect.command("github")
def connect_github():
    """Connect GitHub as a read-only signal source (recent activity)."""
    username = click.prompt("GitHub username")
    token = click.prompt("Personal access token (optional, blank for public-only)",
                         default="", hide_input=True, show_default=False)
    click.echo("\nThe agent will READ-ONLY fetch your recent public activity "
               "(pushes, merged PRs, releases) to draft posts. Nothing is written "
               "to GitHub.")
    if not click.confirm("Grant read access?", default=True):
        raise click.Abort()
    secrets = {"token": token} if token else None
    record = consent_mod.grant("github", ["read:activity"],
                               meta={"username": username}, secrets=secrets)
    click.echo(f"✓ GitHub connected (expires {record['expires_at']}).")


@connect.command("filesystem")
@click.argument("paths", nargs=-1, required=True)
def connect_filesystem(paths):
    """Allowlist local directories; recently modified files become signals."""
    click.echo("The agent will READ-ONLY scan these paths for recently modified "
               f"files (.py/.ipynb/.md):\n  " + "\n  ".join(paths))
    if not click.confirm("Grant read access to these paths?", default=True):
        raise click.Abort()
    record = consent_mod.grant("filesystem", ["read:paths"],
                               meta={"paths": list(paths)})
    click.echo(f"✓ Filesystem connected (expires {record['expires_at']}).")


@cli.command()
@click.argument("source")
def disconnect(source):
    """Revoke consent and purge secrets + unused cached data for a source."""
    provider = "upload_post" if source == "linkedin" else source
    consent_mod.revoke(provider)
    click.echo(f"✓ '{source}' disconnected: consent revoked, secrets and "
               "unused cached signals purged.")


# ----------------------------------------------------------------- ingest ---

@cli.command()
@click.option("--source", type=click.Choice(["github", "filesystem", "all"]),
              default="all")
@click.option("--hours", default=24, help="Filesystem lookback window (hours).")
def ingest(source, hours):
    """Pull new signals from connected sources (consent-gated)."""
    total = 0
    try:
        if source in ("github", "all") and consent_mod.get("github"):
            ids = gh_connector.ingest()
            click.echo(f"github: {len(ids)} new signal(s)")
            total += len(ids)
        if source in ("filesystem", "all") and consent_mod.get("filesystem"):
            ids = fs_connector.ingest(hours=hours)
            click.echo(f"filesystem: {len(ids)} new signal(s)")
            total += len(ids)
    except consent_mod.ConsentError as e:
        raise click.ClickException(str(e))
    except requests.HTTPError as e:
        raise click.ClickException(
            f"Source API error: {e}. If this is a GitHub rate limit, reconnect "
            "with a personal access token: agent connect github"
        )
    if total == 0:
        click.echo("No new signals. Connect a source or use: agent draft \"<hint>\"")


# ------------------------------------------------------------------ draft ---

@cli.command()
@click.argument("hint", required=False)
@click.option("--file", "files", multiple=True, type=click.Path(exists=True),
              help="Upload file(s) as manual context (repeatable).")
@click.option("--platforms", default="linkedin",
              help="Comma-separated target platforms.")
@click.option("--from-signals", is_flag=True,
              help="Draft from unused ingested signals instead of manual input.")
@click.option("--dry-run", is_flag=True, help="Never actually publish (auto mode).")
def draft(hint, files, platforms, from_signals, dry_run):
    """Create a post draft from a manual hint/files, or from ingested signals."""
    platform_list = [p.strip() for p in platforms.split(",") if p.strip()]
    conn = get_db()
    signal_ids = []

    if hint:
        signal_ids.append(manual_connector.add_hint(hint))
    for f in files:
        signal_ids.append(manual_connector.add_file(f))

    if from_signals:
        rows = conn.execute(
            "SELECT id FROM signals WHERE used=0 AND source != 'manual' "
            "ORDER BY ts DESC LIMIT 10"
        ).fetchall()
        signal_ids.extend(r["id"] for r in rows)

    if not signal_ids:
        conn.close()
        raise click.ClickException(
            'Nothing to draft from. Provide a hint (agent draft "shipped X"), '
            "--file, or ingest signals first and use --from-signals."
        )

    qmarks = ",".join("?" * len(signal_ids))
    signals = [dict(r) for r in conn.execute(
        f"SELECT * FROM signals WHERE id IN ({qmarks})", signal_ids).fetchall()]

    click.echo("Drafting...")
    text = drafting.draft_post(signals)
    draft_id = add_draft(conn, text, signal_ids, platform_list)
    conn.execute(f"UPDATE signals SET used=1 WHERE id IN ({qmarks})", signal_ids)
    conn.commit()
    conn.close()

    click.echo(f"\n--- Draft #{draft_id} (platforms: {', '.join(platform_list)}) ---")
    click.echo(text)
    click.echo("---")

    sources = list({s["source"] for s in signals})
    outcome = router.route_draft(draft_id, sources, dry_run=dry_run)
    if outcome["routed"] == "auto_published":
        click.echo("✓ AUTO-PUBLISHED." + (" (dry run)" if dry_run else ""))
    else:
        click.echo(f"→ Queued for review ({outcome['reason']}). Run: agent review")


# ----------------------------------------------------------------- review ---

@cli.command()
def review():
    """Review pending drafts: approve & publish, edit, reject, or skip."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM drafts WHERE status='pending' ORDER BY id").fetchall()
    conn.close()
    if not rows:
        click.echo("Review queue is empty.")
        return
    for row in rows:
        click.echo(f"\n--- Draft #{row['id']} (platforms: "
                   f"{', '.join(json.loads(row['platforms']))}) ---")
        click.echo(row["text"])
        click.echo("---")
        action = click.prompt("Action", type=click.Choice(["publish", "edit", "reject", "skip"]),
                              default="skip")
        conn = get_db()
        if action == "publish":
            conn.close()
            _do_publish(row["id"])
        elif action == "edit":
            new_text = click.edit(row["text"])
            if new_text:
                conn.execute("UPDATE drafts SET text=? WHERE id=?",
                             (new_text.strip(), row["id"]))
                conn.commit()
                click.echo("Draft updated.")
                if click.confirm("Publish now?", default=False):
                    conn.close()
                    _do_publish(row["id"])
                    continue
            conn.close()
        elif action == "reject":
            conn.execute("UPDATE drafts SET status='rejected' WHERE id=?", (row["id"],))
            conn.commit()
            conn.close()
            click.echo("Rejected.")
        else:
            conn.close()


def _do_publish(draft_id: int, dry_run: bool = False):
    try:
        result = publisher.publish_draft(draft_id, dry_run=dry_run)
        click.echo("✓ Published." + (" (dry run)" if dry_run else ""))
        urls = [
            v.get("url") for v in (result.get("results") or {}).values()
            if isinstance(v, dict) and v.get("url")
        ]
        for u in urls:
            click.echo(f"  {u}")
    except (publisher.PublishError, consent_mod.ConsentError) as e:
        raise click.ClickException(str(e))


@cli.command()
@click.argument("draft_id", type=int)
@click.option("--dry-run", is_flag=True)
def publish(draft_id, dry_run):
    """Publish a specific draft by id (must not be rejected/published)."""
    _do_publish(draft_id, dry_run=dry_run)


# ------------------------------------------------------------ mode / audit ---

@cli.command()
@click.argument("new_mode", required=False,
                type=click.Choice(["review", "auto"]))
def mode(new_mode):
    """Show or set the publishing mode (review | auto)."""
    if new_mode:
        try:
            router.set_mode(new_mode)
        except (ValueError, consent_mod.ConsentError) as e:
            raise click.ClickException(str(e))
        click.echo(f"✓ Publishing mode set to '{new_mode}'.")
    else:
        click.echo(f"Publishing mode: {router.get_mode()}")


@cli.command()
@click.option("--source", default=None, help="Filter by provider.")
def audit(source):
    """Show the consent + action ledger (append-only)."""
    click.echo("=== Connections ===")
    for c in consent_mod.list_all():
        click.echo(f"  {c['provider']:<12} {c['status']:<8} scopes={c['scopes']} "
                   f"expires={c['expires_at']}")
    click.echo("\n=== Ledger (latest first) ===")
    for entry in consent_mod.audit_log(source):
        click.echo(f"  {entry['ts']}  {entry['provider']:<12} "
                   f"{entry['action']:<12} {entry['details']}")


@cli.command()
def status():
    """Quick overview: mode, connections, queue size."""
    conn = get_db()
    pending = conn.execute("SELECT COUNT(*) n FROM drafts WHERE status='pending'").fetchone()["n"]
    published = conn.execute("SELECT COUNT(*) n FROM drafts WHERE status='published'").fetchone()["n"]
    unused = conn.execute("SELECT COUNT(*) n FROM signals WHERE used=0").fetchone()["n"]
    conn.close()
    click.echo(f"Mode: {router.get_mode()}")
    click.echo(f"Drafts pending review: {pending} | published: {published}")
    click.echo(f"Unused signals: {unused}")
    active = [c["provider"] for c in consent_mod.list_all() if c["status"] == "active"]
    click.echo(f"Active connections: {', '.join(active) or 'none (manual mode only)'}")


@cli.command()
@click.argument("runs_per_day", required=False, type=int)
def schedule(runs_per_day):
    """Show or set scheduled runs per day (0=off, 1=daily, 2=twice/day, ...)."""
    if runs_per_day is None:
        current = scheduler.get_schedule()
        click.echo(f"Schedule: {current} run(s)/day"
                   + (" (off — run 'agent daemon' after setting)" if current == 0 else ""))
        return
    try:
        scheduler.set_schedule(runs_per_day)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"✓ Schedule set to {runs_per_day} run(s)/day. "
               f"Start with: agent daemon  (choices: {SCHEDULE_CHOICES})")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Pipeline runs never actually publish.")
@click.option("--poll", default=60, help="Seconds between due-checks.")
def daemon(dry_run, poll):
    """Run the scheduler loop: ingest → draft → route, at the set cadence."""
    import time as _time
    if scheduler.get_schedule() <= 0:
        raise click.ClickException("No schedule set. First run e.g.: agent schedule 2")
    click.echo(f"Daemon started ({scheduler.get_schedule()} run(s)/day, "
               f"mode={router.get_mode()}). Ctrl+C to stop.")
    while True:
        result = scheduler.run_due(dry_run=dry_run)
        if result:
            outcome = result["outcome"]
            click.echo(f"[{result['ingested']}] "
                       + (f"draft #{outcome['draft_id']} → {outcome['routed']}"
                          if outcome else "no new signals"))
        _time.sleep(poll)


def main():
    try:
        cli()
    except consent_mod.ConsentError as e:
        click.echo(f"Consent error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
