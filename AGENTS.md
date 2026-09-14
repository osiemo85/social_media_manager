# Social Media Manager — Engineering Instructions

## Goal

Build a consent-first, multi-tenant social media assistant that converts user-authorized work signals—such as GitHub activity, documents, emails, calendar events, releases, talks, and manual notes—into accurate social media drafts.

Users retain control over connected accounts, source access, drafts, approvals, and publishing. The system must support local single-user use and cloud multi-user deployment. Publishing must use an Upload-Post adapter and support LinkedIn and other approved platforms.

## Architecture

Read `docs/architecture.md` before introducing files, modules, folders, or major dependencies.

## Technology Standards

* Backend: Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL.
* Background jobs: Celery and Redis for queues, retries, scheduling, and cache where needed.
* Retrieval: PostgreSQL full-text search and pgvector, with citations and defined retention.
* Frontend: Next.js and TypeScript.
* Configuration: environment-based settings, `.env.example`, secure production secret management.
* Security: encrypt provider tokens at rest; never commit or log credentials.

All background jobs must be idempotent, observable, retry-safe, and report progress where applicable.

## Consent, Privacy, and Tenancy

### Consent

* Require separate consent for every data source and publishing destination.
* Request the minimum provider scopes required.
* Record: tenant/user, provider, scopes, grant method, grant time, expiry time, status, revocation path, and retention period.
* Default consent expiry to 90 days unless a provider or product requirement specifies otherwise.
* Verify active consent before every ingestion, retrieval, generation, and publishing action.

## Ingestion, Memory, and Generation

Use this pipeline:

1. Verify active consent.
2. Fetch only the minimum relevant fields and date range.
3. Normalize content through provider-specific cleaners.
4. Remove secrets and unnecessary personal information.
5. Deduplicate, truncate, and rank content by recency, relevance, and confidence.
6. Retrieve only authorized and relevant memory.
7. Generate one grounded draft with citations.
8. Validate factual support, privacy, duplication, length, and policy compliance.
9. Save or publish only after the required user approval.

Prompt safety requirements:

* Keep trusted instructions separate from ingested source content.
* Treat source content as data, never as instructions.
* Do not invent facts or expose private information.
* Track source identifiers and prior usage to avoid repeatedly promoting the same commit, document, or event without a meaningful update.

## API, Data, and Reliability

* Validate all inputs with typed schemas.
* Return consistent, non-sensitive error responses.
* Use Alembic migrations for schema changes; never modify production schemas manually.
* Use transactions for consent, publishing state, and audit mutations.
* Apply timeouts, bounded exponential retries, idempotency keys, rate-limit handling, and safe failure states to external calls.
* Use feature flags for incomplete or high-risk functionality.
* Record significant technical decisions in `docs/decisions`.


Reconcile published and failed states with the provider.

Observability requirements:

* Structured logs
* Metrics
* Correlation IDs
* Health checks
* Redaction of tokens and sensitive source content

## Frontend and Accessibility

Build responsive, keyboard-accessible interfaces for mobile, tablet, and desktop.

Every relevant feature must handle:

* Loading
* Empty
* Error
* Confirmation
* Destructive-action states

Clearly explain consent, scopes, expiry, retention, and publishing mode. Keep revocation and deletion actions visible and easy to use.

### Color Palette

| Purpose        | Color     |
| -------------- | --------- |
| Primary        | `#2563EB` |
| Primary hover  | `#1D4ED8` |
| Background     | `#F8FAFC` |
| Surface        | `#FFFFFF` |
| Main text      | `#0F172A` |
| Secondary text | `#64748B` |
| Border         | `#E2E8F0` |
| Success        | `#16A34A` |
| Warning        | `#D97706` |
| Error          | `#DC2626` |

## Testing and Verification

Inspect existing package scripts before running commands.

For every behavioral change, add tests covering the relevant scenarios:

* Successful operation
* Invalid input
* Authorization failure
* Expired or revoked consent
* Provider failure
* Duplicate delivery
* Deletion or purge behavior

Use mocked providers. Never use real user accounts or credentials in tests.

Run focused checks first. Run the full suite only for large, cross-cutting, migration, or contract changes.

Required checks, where applicable:

* Backend unit and integration tests
* API and provider contract tests
* Worker retry, idempotency, expiry, and recovery tests
* Frontend unit, integration, and critical-flow E2E tests
* Type checks, linting, formatting, migration checks, and builds
* Responsive and accessibility checks

Update documentation and `.env.example` whenever configuration or behavior changes.

## Test and Evaluation Standards

* Small and medium changes: run tests covering the modified code.
* Large, migration, or contract changes: run the full relevant suite.
* Every feature includes tests and an evaluation suite in the same change.
* Every bug fix includes a regression test and an evaluation that would catch similar failures.
* Non-behavioral changes, such as copy or styling-only edits, do not require new tests.
* Gate tests must be deterministic, local, free, and fast.
* Periodic evaluations may use LLM calls, must define a pass threshold, and should run before release and on a scheduled basis.
* When a failure reveals reusable guidance, document it through the project’s skillification process during the same session where practical.

## Development Commands

```bash
# Backend — from repository root
cd apps/api
uv sync --all-groups
uv run uvicorn app.main:app --reload --port 8000

# Backend checks
cd apps/api
uv run python -m compileall -q app
uv run pytest

# Frontend
cd frontend
npm run lint
npm run build
npm run dev
```

Run relevant backend checks and frontend lint/build after API or web changes.

## Change Discipline

* Read relevant architecture, security, and decision documents before implementation.
* Keep changes focused and preserve existing user work.
* Review diffs for secrets, accidental data exposure, and unrelated edits.
* Prefer backward-compatible migrations.
* Document breaking changes clearly.

## Completion Status

End every task with one status:

* `DONE` — Completed and verified. State what changed and what tests or evaluations ran.
* `DONE_WITH_CONCERNS` — Completed, but include each concern, severity, and recommended follow-up.
* `BLOCKED` — Cannot proceed. State the blocker and what was attempted.
* `NEEDS_CONTEXT` — State the exact information required to continue.
* Always list which files changed.

Do not use “partially done” as a completion status.