# Social Media Manager (PoC)

Consent-first agent that turns your work signals (GitHub activity, local
files, manual hints) into LinkedIn posts — publishable to 22 platforms via
[Upload-Post](https://www.upload-post.com) (LinkedIn, X, Threads, Bluesky, ...).

See `.github/copilot-instructions.md` for the full design.

## Setup

```bash
cd apps/api && uv sync --all-groups
cd ../..
cp .env.example .env          # optional: add OPENAI_API_KEY for LLM drafting
chmod +x scripts/agent
```

## Quick start

```bash
# 1. Connect publishing (create an Upload-Post account, link LinkedIn there,
#    then paste your API key here — stored encrypted locally):
./scripts/agent connect linkedin

# 2. Optionally connect read-only sources:
./scripts/agent connect github                    # recent activity (PAT optional)
./scripts/agent connect filesystem ~/projects     # allowlisted paths

# 3a. Manual mode — no source access needed:
./scripts/agent draft "shipped retry logic for the connector layer today"
./scripts/agent draft --file notes.md

# 3b. Or draft from ingested signals:
./scripts/agent ingest
./scripts/agent draft --from-signals

# 4. Review and publish (default mode: review):
./scripts/agent review
./scripts/agent publish <draft-id> [--dry-run]

# Auto-publish (opt-in; requires auto_publish consent + guardrails):
./scripts/agent mode auto

# Scheduling — choose cadence and run the daemon:
./scripts/agent schedule 2        # 0=off, 1, 2, 3, 4, 6, 12, 24 runs/day
./scripts/agent daemon            # ingest → draft → route at that cadence

# Governance:
./scripts/agent status
./scripts/agent audit
./scripts/agent disconnect <linkedin|github|filesystem>
```

## Web version (Next.js + FastAPI)

```bash
(cd apps/api && uv sync --all-groups && uv run uvicorn app.main:app --reload --port 8000)
# API: http://localhost:8000
(cd frontend && npm run dev)                          # web, http://localhost:3000
```

Register an account, then use Connections (consent), Dashboard (manual drafts
and pipeline runs), Review (approve/edit/reject), Settings (mode + schedule), and
Audit. The Next app proxies `/api` to FastAPI in development, keeping its signed
session cookie same-origin. Each user's DB and encrypted vault are fully
isolated under `SMM_DATA_DIR/users/<id>/`; the FastAPI scheduler runs each
user's pipeline at their chosen cadence. Expose publicly only behind HTTPS.

For the web GitHub connection, create a GitHub OAuth App with callback URL
`http://localhost:3000/api/connections/github/callback`, then put its client ID and
client secret in `.env` as `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.
Users can then authorize GitHub from the Connections page without pasting a
personal access token.

Data lives in `~/.smm/` (SQLite DB + Fernet-encrypted vault). Override with
`SMM_DATA_DIR`.
