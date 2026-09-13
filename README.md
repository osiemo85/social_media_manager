# Social Media Manager (PoC)

Consent-first agent that turns your work signals (GitHub activity, local
files, manual hints) into LinkedIn posts — publishable to 22 platforms via
[Upload-Post](https://www.upload-post.com) (LinkedIn, X, Threads, Bluesky, ...).

See `.github/copilot-instructions.md` for the full design.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # optional: add OPENAI_API_KEY for LLM drafting
chmod +x agent
```

## Quick start

```bash
# 1. Connect publishing (create an Upload-Post account, link LinkedIn there,
#    then paste your API key here — stored encrypted locally):
./agent connect linkedin

# 2. Optionally connect read-only sources:
./agent connect github                    # recent activity (PAT optional)
./agent connect filesystem ~/projects     # allowlisted paths

# 3a. Manual mode — no source access needed:
./agent draft "shipped retry logic for the connector layer today"
./agent draft --file notes.md

# 3b. Or draft from ingested signals:
./agent ingest
./agent draft --from-signals

# 4. Review and publish (default mode: review):
./agent review
./agent publish <draft-id> [--dry-run]

# Auto-publish (opt-in; requires auto_publish consent + guardrails):
./agent mode auto

# Scheduling — choose cadence and run the daemon:
./agent schedule 2        # 0=off, 1, 2, 3, 4, 6, 12, 24 runs/day
./agent daemon            # ingest → draft → route at that cadence

# Governance:
./agent status
./agent audit
./agent disconnect <linkedin|github|filesystem>
```

## Web version (multi-user)

```bash
.venv/bin/python web/app.py                          # dev, http://localhost:5000
.venv/bin/waitress-serve --port=8080 web.app:app     # prod-ish
```

Register an account, then use Connections (consent), Dashboard (manual
drafts + run pipeline), Review (approve/edit/reject), Settings (mode +
schedule) and Audit. Each user's DB and encrypted vault are fully isolated
under `SMM_DATA_DIR/users/<id>/`; a background thread runs each user's
pipeline at their chosen cadence. Expose publicly only behind HTTPS.

Data lives in `~/.smm/` (SQLite DB + Fernet-encrypted vault). Override with
`SMM_DATA_DIR`.
