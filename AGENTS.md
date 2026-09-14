# Social Media Manager — Engineering Instructions

## Goal

Build a consent-first, multi-tenant social media assistant that turns relevant,
user-authorized work signals—GitHub activity, documents, email, calendar events,
talks, releases, or manual notes—into accurate, useful social posts. Users must
control every connection, draft, and publication. Support both local,
single-user operation and cloud, multi-user operation. Publishing is mediated by
Upload-Post and may target LinkedIn and other supported platforms.


## Core principle
**Never read, retain, infer from, or publish user data without explicit, scoped,
revocable consent.** Enforce this invariant in API services, background jobs,
storage, prompts, and publishing workflows. Default to manual input and human
approval.

## Architecture

Read `docs/architecture.md` before adding files, folders, modules, or major
dependencies. Follow this target structure:

- `apps/api`: FastAPI, domain modules, persistence, integrations, publishing,
  and Celery workers.
- `apps/web`: Next.js, TypeScript, feature modules, shared UI, and API clients.
- `packages`: shared contracts, generated types, configuration, and reusable UI.
- `infrastructure`: Docker, Terraform, reverse proxy, and monitoring.
- `scripts`: repeatable development and operations scripts.
- `docs`: architecture, API, security, and decision records.

Use domain-oriented modules. Keep routers thin; put business rules in services;
isolate persistence in repositories; and isolate external APIs behind provider
adapters. Shared infrastructure belongs in `shared`, not in domain modules.

## Technology standards

- Backend: Python, FastAPI, SQLAlchemy, Alembic, and PostgreSQL.
- Async processing: Celery with Redis for queues, retries, scheduling, and cache
  where appropriate. Jobs must be idempotent and observable.
- Retrieval: PostgreSQL full-text search and pgvector, with citations and clear
  retention rules.
- Frontend: Next.js and TypeScript.
- Publishing: an Upload-Post adapter; never couple domain logic to vendor APIs.
- Configuration: environment-based settings, `.env.example`, production secret
  management, and encrypted tokens at rest. Never commit or log credentials.

## Consent, privacy, and tenancy

- Require separate consent for every source and publishing destination.
- Request the narrowest provider scopes and record exactly what was granted.
- Consent records include tenant/user, provider, scopes, grant and expiry times,
  status, grant method, revocation path, and retention period. Default expiry is
  90 days unless requirements specify otherwise.
- Enforce tenant isolation on every query, task, cache key, object path, and
  authorization decision. Never trust a tenant ID supplied by the client.
- Maintain an append-only, user-visible audit trail for grants, access,
  publishing, revocation, and deletion.
- Expire raw source content after 30 days by default, or sooner when possible.
  Retain only approved posts and minimal citation metadata when justified.
- “Disconnect and purge” removes tokens, raw content, derived signals,
  embeddings, and provider-specific state for that source.
- Manual review is the default publishing mode. Auto-publish requires separate
  opt-in, guardrails, auditability, and an immediate disable path.

## Ingestion and generation

Use this deterministic pipeline: verify active consent; fetch the smallest
relevant range and fields; normalize through provider-specific cleaners; dedupe,
truncate, and rank by recency, relevance, and confidence; remove secrets and
unnecessary personal content; retrieve only authorized relevant memory; generate
one grounded draft; then validate factual support, privacy, repetition, length,
and policy before publishing.

Prompts must separate trusted instructions from source content. The model must
not invent facts, expose private content, or treat ingested text as instructions.
Track source identifiers and prior use so the same commit, document, or event is
not promoted repeatedly without a meaningful update. Save only user-approved
corrections and durable style preferences, with inspect/correct/delete controls.

## API, data, and reliability

- Validate inputs with typed schemas and return consistent, non-sensitive errors.
- Use Alembic migrations; never change production schema manually.
- Use transactions for consent, publishing state, and audit mutations.
- Give external calls timeouts, bounded exponential retries, idempotency keys,
  rate-limit handling, and safe failure states.
- Use an explicit publishing state machine: draft, pending approval, approved,
  queued, published, failed, or cancelled. Reconcile provider status.
- Add structured logs, metrics, correlation IDs, and health checks. Redact all
  tokens and sensitive source content.
- Use feature flags for risky or incomplete behavior and record major decisions
  in `docs/decisions`.

## Frontend and accessibility

Build keyboard-accessible interfaces that work on mobile, tablet, and desktop.
Prevent overflow and overlap; cover loading, empty, error, confirmation, and
destructive-action states. Explain consent, scopes, expiry, retention, and
publishing mode plainly, and keep revocation and deletion easy to find.

Use the palette consistently: primary `#2563EB` (hover `#1D4ED8`), background
`#F8FAFC`, surface `#FFFFFF`, main text `#0F172A`, secondary text `#64748B`,
border `#E2E8F0`, success `#16A34A`, warning `#D97706`, and error `#DC2626`.

## Testing and verification

Inspect package scripts first. Run focused checks for changed code, then every
applicable full suite: backend unit/integration tests; API/provider contract
tests; worker retry, idempotency, expiry, and recovery tests; frontend
unit/integration and critical-flow E2E tests; type checking, linting, formatting,
migration checks, and builds; plus responsive and accessibility checks for UI.

Every new behavior should cover success, invalid input, authorization failure,
expired/revoked consent, provider failure, duplicate delivery, and deletion when
relevant. Mock external providers and never use real user accounts in tests.
Update docs and `.env.example` when configuration or behavior changes.

## Run and test commands

The FastAPI backend is managed with `uv`; do not install its dependencies into
the system Python or run the globally installed `uvicorn` binary.

```bash
# Backend — run from the repository root
cd apps/api
uv sync --all-groups
uv run uvicorn app.main:app --reload --port 8000

# Backend focused checks
cd apps/api
uv run python -m compileall -q app
uv run pytest

# Frontend
cd frontend
npm run lint
npm run build
npm run dev
```

For a quick backend smoke check after starting the API, use
`curl -fsS http://localhost:8000/health`. Run the relevant backend checks and
the frontend lint/build for every web or API change.

## Change discipline

Read relevant architecture, security, and decision documents first. Keep changes
focused, preserve existing user work, inspect diffs for secrets and unrelated
edits, prefer backwards-compatible migrations, and document breaking changes.
In the handoff, state what changed, what was tested, and any known limitations.
