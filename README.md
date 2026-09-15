# Social Media Manager

Social Media Manager is a consent-first assistant for turning work updates into social-media drafts. It can use a manual note or user-authorized GitHub and local-file signals, generate a grounded draft, and route it through review before publishing.

This repository is a proof of concept designed for local, single-user CLI use and a small multi-user web experience. Users control every data connection, can revoke access at any time, and must explicitly connect a publishing destination. LinkedIn publishing is handled through Upload-Post; additional supported destinations include X, Threads, Bluesky, Facebook, Reddit, Telegram, Discord, Mastodon, and Pinterest.

## What it does

- Creates drafts from manual notes, supported local files, or recent GitHub activity.
- Records consent with scopes and a default 90-day expiry.
- Keeps provider credentials in an encrypted local vault.
- Lets users review, edit, reject, or publish drafts; auto-publishing is opt-in and guarded.
- Provides a Next.js dashboard for authentication, connections, drafting, review, settings, and audit history.

## Tech stack

| Area | Technology |
| --- | --- |
| API and CLI | Python 3.12+, FastAPI, Uvicorn, Click |
| Web app | Next.js 16, React 19, TypeScript |
| Local persistence | SQLite with a Fernet-encrypted credential vault |
| Drafting | OpenAI Agents SDK (optional; template drafts are used without an API key) |
| Publishing | Upload-Post API |
| Source connections | GitHub OAuth or a personal access token; allowlisted local files |

## Prerequisites

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 or later and npm

Optional accounts and credentials:

- An OpenAI API key for LLM-generated drafts.
- An Upload-Post account with LinkedIn or another destination connected, for publishing.
- A GitHub OAuth app for the web connection flow, or a personal access token for the CLI.

## Install

From the repository root:

```bash
cp .env.example .env
cd apps/api
uv sync --all-groups
cd ../../frontend
npm ci
cd ..
chmod +x scripts/agent
```

Edit `.env` to add only the integrations you intend to use. `OPENAI_API_KEY` is optional. For browser-based GitHub authorization, set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`; configure the OAuth callback URL as `http://localhost:3000/api/connections/github/callback`.

By default, application data is stored in `~/.smm/`. Set `SMM_DATA_DIR` in `.env` to use a different location.

## Run the web app

Start the API in one terminal:

```bash
cd apps/api
uv run uvicorn app.main:app --reload --port 8000
```

Start the frontend in another terminal:

```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000), register an account, and use:

- **Connections** to grant or revoke GitHub and Upload-Post access.
- **Dashboard** to create a manual draft or run the signal pipeline.
- **Review** to edit, approve, publish, or reject drafts.
- **Settings** to choose review or guarded auto-publish mode and a schedule.
- **Audit** to inspect connection and action history.

The frontend proxies `/api` requests to the FastAPI server at `http://127.0.0.1:8000` during development. Visit [http://localhost:8000/health](http://localhost:8000/health) to confirm the API is running.

## Run the CLI

The CLI supports the same consent-first workflow without the web UI:

```bash
# Connect a publishing destination through Upload-Post.
./scripts/agent connect linkedin

# Optional read-only sources.
./scripts/agent connect github
./scripts/agent connect filesystem ~/projects

# Create a draft from a manual update, then review it.
./scripts/agent draft "Shipped retry logic for the connector layer today"
./scripts/agent review

# Or generate from authorized, ingested signals.
./scripts/agent ingest
./scripts/agent draft --from-signals

# Inspect or revoke access.
./scripts/agent status
./scripts/agent audit
./scripts/agent disconnect github
```

Use `./scripts/agent --help` to see all commands. Publishing is review-first by default. Auto-publishing requires separate consent and can be enabled with `./scripts/agent mode auto`.

## Checks

Run the focused backend tests and frontend quality checks:

```bash
cd apps/api
uv run pytest
uv run python -m compileall -q app

cd ../../frontend
npm run lint
npm run build
```

## Privacy and safety

Only connect sources and destinations you authorize. The application verifies consent before source ingestion and publishing, retains source signals locally, and allows revocation through the CLI or Connections page. Do not commit `.env`, API keys, OAuth client secrets, or exported application data. For any public deployment, serve the API and web app behind HTTPS and set `SMM_COOKIE_SECURE=true`.
