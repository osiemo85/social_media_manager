---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                            User-facing layer                         │
│   CLI (local)  |  Web dashboard (cloud)  |  Chat/Copilot interface   │
└───────────────────────────┬──────────────────────────────────────────┘
                             │
┌───────────────────────────▼──────────────────────────────────────────┐
│                        Consent & Identity Service                    │
│  - User accounts (local: single profile file; cloud: multi-tenant DB)│
│  - OAuth token vault (per user, per provider, encrypted at rest)     │
│  - Consent ledger (append-only log of grants/revocations/scopes)     │
└───────────────────────────┬──────────────────────────────────────────┘
                             │
        ┌────────────────────┴─────────────────────┐
        ▼                                            ▼
┌─────────────────────────────┐      ┌──────────────────────────────────┐
│   Connected-Source Path     │      │        Manual Input Path          │
│  (OAuth connectors, §3)     │      │  (typed hints / uploaded files,   │
│  LinkedIn|GitHub|Drive|     │      │   §6 — no account access needed)  │
│  Email|Calendar|Slack|...   │      │                                    │
└──────────────┬───────────────┘      └────────────────┬───────────────┘
               │                                        │
               └───────────────────┬────────────────────┘
                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│                Event Ingestion & Normalization → SignalEvent          │
└───────────────────────────┬──────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│              Drafting & Ranking Engine (LLM) → draft post(s)          │
└───────────────────────────┬──────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│   Publishing Mode Router (§5): Review Queue  OR  Auto-Publish         │
└───────────────────────────┬──────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│           Publishing Layer (LinkedIn API) — rate-limited,             │
│                 idempotent, retry-safe, audit-logged                 │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Sources (all opt-in, independently revocable)

| Source | What it provides | Scope requested | Sensitivity |
|---|---|---|---|
| **Upload-Post (publisher)** | Publish to LinkedIn + up to 21 other platforms (X, Threads, Bluesky, Facebook, Reddit, ...) in one API call | API key; per-platform `publish:<platform>` scopes granted individually | High (destination platforms) |
| **GitHub** | Commits, PRs merged, releases, issues closed, repo stars | Read-only, repo- or org-scoped | Medium |
| **Google Drive / Docs** | Design docs, blog drafts, project write-ups | Read-only, folder-scoped preferred over full-drive | Medium-High |
| **Gmail / Outlook Email** | Newsletter mentions, conference confirmations, launch announcements | Read-only, label/folder-scoped, never full inbox by default | High |
| **Google / Outlook Calendar** | Talks, conferences, milestones, launches | Read-only, event titles + free/busy | Medium |
| **Slack** | Team announcements, ship-it channel messages | Read-only, specific channel scope | Medium |
| **Notion / Confluence** | Project retros, changelogs | Read-only, workspace/page scoped | Medium |
| **Jira / Linear** | Completed epics/sprints | Read-only | Low-Medium |
| **RSS / Blog / YouTube** | Published articles, videos | Public, no auth required | Low |
| **Local filesystem** | Local markdown notes, `CHANGELOG.md` | Explicit path allowlist | Low (user-controlled) |
| **Manual input** (§6) | Typed hints, pasted text, uploaded files | None — no OAuth, no account access | None |

Each connector is independent: add, pause, or remove any one without
affecting the others. A user may run with **zero** connected sources and
rely solely on Manual Input Mode plus LinkedIn (§6).


### 4.3 Consent flow (OAuth, per provider)

1. User clicks **Connect** for a provider in the dashboard or CLI.
2. Agent redirects to the provider's OAuth consent screen with minimal
   scopes and a `state` param bound to `user_id` (PKCE where supported).
3. Provider redirects back with an auth code; the agent exchanges it for
   access/refresh tokens **server-side** — tokens are never exposed to the
   frontend.
4. Tokens are encrypted (AES-256-GCM, per-tenant key) and stored in the
   token vault; never logged in plaintext.
5. A consent ledger entry is written (§4.2).
6. User sees a confirmation summary, e.g.: *"You've granted read-only
   access to GitHub repo `org/repo`. Used to draft posts about merged PRs.
   Revoke anytime in Settings > Connections."*
7. A re-consent prompt fires automatically at `expires_at - 7 days`.

### 4.4 Publishing consent (LinkedIn & other platforms via Upload-Post)

Publishing is the only write-capable integration and gets extra guardrails:
- Platform OAuth (LinkedIn, X, Threads, ...) happens on the user's own
  Upload-Post account; the agent stores only the Upload-Post API key,
  encrypted in the vault.
- Consent is **per platform**: a `publish:<platform>` scope is granted for
  each platform the user names (e.g., `publish:linkedin`, `publish:x`) —
  the agent can never post to a platform the user did not explicitly list.
- `auto_publish` is a separate scope, requested as its own yes/no question
  at connect time (§5.2).
- Every post shows a preview of the exact text/media before it is used,
  regardless of Publishing Mode (see §5.2 for the Auto-Publish exception
  window).
- Agent keeps its own post history (URL, timestamp, source citation),
  independent of the platforms, for audit and undo support.

---

## 5. Publishing Mode (user-level setting, changeable anytime)

Every user picks exactly one default mode; it can be overridden per draft.

### 5.1 Review Mode (default for all new users)
- Agent drafts posts and places them in a **Review Queue**. Nothing is
  published until the user acts.
- Available actions per draft: **Approve & publish now**, **Approve &
  schedule**, **Edit then approve**, **Reject** (reason optionally fed back
  into future scoring), **Snooze**.
- Recommended for all users, mandatory for the first 14 days of any new
  connected source (a "trust-building" period).

### 5.2 Auto-Publish Mode (opt-in, off by default)
- Agent publishes drafts without per-post approval, subject to guardrails:
  - Explicit, separate toggle from Review Mode — enabling it is its own
    consent event, logged in the ledger.
  - **Rate limit**: max N auto-posts/day (default 1), configurable.
  - **Topic/keyword blocklist** checked before every auto-post (e.g., no
    salary, no client names, no unreleased features).
  - **Confidence threshold**: drafts scoring below the configured
    confidence/relevance threshold are automatically routed to Review Mode
    instead of published.
  - **Cooling-off window**: every auto-published post is held for a short
    delay (default 10 minutes) during which the user can cancel it from a
    notification, before it actually goes out.
  - Can be scoped per source (e.g., auto-publish GitHub release signals,
    but require review for email-derived signals).
- Auto-Publish never applies to a source in its first 14 days of connection
  (falls back to Review Mode automatically).

### 5.3 Hybrid (per-rule mode)
- Users may set Review vs. Auto-Publish independently per signal type or
  per source (e.g., "auto-publish GitHub releases", "always review
  anything derived from email or Drive"). Hybrid is Review Mode by default
  for any rule not explicitly set to Auto-Publish.

### 5.4 Scheduling & cadence (user-chosen)
Each user chooses how often the agent runs its pipeline
(ingest → draft → route) automatically:

- **Choices**: off (manual only), 1×, 2×, 3×, 4×, 6×, 12×, or 24× per day.
- **Where**: CLI `agent schedule <n>` + `agent daemon`, or the web
  Settings page (a background scheduler thread runs each user's pipeline
  when their interval elapses).
- **Idempotent runs**: a run only fires when the interval since
  `last_run_at` has elapsed, so restarts and overlapping pollers never
  double-run.
- **Mode interaction**: in Review Mode, scheduled runs only fill the review
  queue; in Auto-Publish Mode they may publish, still bounded by the daily
  auto-post cap, blocklist, and all other §5.2 guardrails.
- Every scheduled run is recorded in the audit ledger
  (`scheduler / run` entries).

---

## 6. Manual Input Mode (no account access required)

For users who don't want to connect any external account, the agent is
still fully usable through direct, user-provided context. This path
requires **no OAuth, no tokens, no consent ledger entries** — content is
supplied directly by the user for the current session/draft only.

### 6.1 Input methods
- **Quick hint**: a short free-text prompt, e.g. `agent draft "shipped
  retry logic for the connector layer today"`.
- **Pasted text**: longer freeform notes pasted directly into the CLI or
  dashboard (release notes, a meeting recap, a personal update).
- **File upload**: user uploads one or more files (Markdown, PDF, .txt,
  .docx, slide decks, screenshots) via CLI path or dashboard drag-and-drop.
  Files are processed only to extract draft-relevant content.
- **URL reference**: user pastes a public link (blog post, GitHub release,
  YouTube video) the agent fetches directly, no auth required.

### 6.2 Handling rules
- Manual inputs are treated as a `SignalEvent` with `source: "manual"`,
  bypassing the connector/consent layer entirely.
- Uploaded files/pasted text are processed in-memory or in short-lived
  storage and **deleted immediately after drafting** unless the user
  explicitly opts to keep them (e.g., to reuse across multiple drafts in
  one session).
- Manual Input Mode always defaults to **Review Mode** for publishing —
  Auto-Publish is not available for manually supplied content unless the
  user explicitly enables it for that rule.
- Manual and connected-source inputs can be combined freely (e.g., connect
  GitHub for signals, but also paste an extra hint to add context to a
  specific draft).

### 6.3 Why this matters
This mode lets privacy-conscious users, contractors without admin rights
to connect org accounts, or first-time users evaluating the agent get full
drafting value without ever granting third-party access beyond LinkedIn
itself (and even LinkedIn can be skipped if the user only wants drafts to
copy/paste manually).

---

## 7. Functional Process — End to End

1. **Onboarding**
   - Create local/cloud user profile.
   - Choose Publishing Mode (§5): Review (default), Auto-Publish, or Hybrid.
   - Connect LinkedIn (recommended, at least read-only for tone-matching)
     — or skip entirely and use Manual Input Mode with copy/paste output.
   - Optionally connect other sources via the consent flow (§4.3), and/or
     rely on Manual Input Mode (§6).
   - Set posting cadence, tone/voice sample (3-5 example posts), and
     topics of interest/exclusion.

2. **Ingestion** (connected sources) — each connector polls or receives
   webhooks for new events since the last checkpoint, normalized into a
   `SignalEvent`:
   ```json
   {
     "source": "github",
     "type": "pr_merged",
     "title": "Add retry logic to connector layer",
     "url": "...",
     "timestamp": "...",
     "raw_ref": "org/repo#456",
     "user_id": "u_123"
   }
   ```
   Manual inputs (§6) are converted to the same `SignalEvent` shape with
   `source: "manual"` and skip the ingestion scheduler entirely.

3. **Scoring & Selection** — heuristic + LLM scoring ranks signals by
   recency, novelty (not posted before), topic alignment, and
   shareability; deduplicated against post history.

4. **Drafting** — LLM drafts 1-3 post variants matching the user's voice,
   citing the source, suggesting hashtags/mentions. Drafts always land in
   the review queue first, *regardless of Publishing Mode* — Auto-Publish
   only skips the manual approval step, not the draft-creation step.

5. **Routing** — the Publishing Mode Router (§5) decides, per draft:
   route to Review Queue, or proceed to the Auto-Publish cooling-off flow.

6. **Publishing** — approved (or auto-approved) posts go through a publish
   worker: rate-limited, retried with backoff, idempotent. Result (URL,
   timestamp, status) is logged to post history.

7. **Feedback loop** — optionally pull engagement metrics (likes/comments)
   via the LinkedIn API, if scope granted, to improve future scoring.

8. **Ongoing governance** — periodic consent re-confirmation (§4.3.7);
   nightly retention/purge job; full audit log via `agent audit`.

---

## 8. Running Locally vs. Cloud

### 8.1 Local mode (CLI)
- **Storage**: SQLite/local encrypted file for consent ledger, token
  vault, event store, post history. Tokens encrypted via OS keychain or
  passphrase-derived key.
- **Scheduling**: `agent schedule <n>` + `agent daemon` polling loop (or
  cron / systemd timer).
- **Auth callback**: loopback OAuth redirect (`http://localhost:PORT/callback`),
  no public URL needed.
- **CLI**: `agent connect <source>`, `agent ingest`, `agent draft "<hint>"`,
  `agent review`, `agent publish`, `agent mode [review|auto]`,
  `agent schedule <n>`, `agent daemon`, `agent audit`,
  `agent disconnect <source>`.
- No data leaves the user's machine except direct provider API calls.

### 8.2 Web mode (multi-user, shared over the internet)
- **App**: Next.js frontend plus FastAPI service — register/login (hashed
  passwords and session cookies), dashboard, manual draft + file upload,
  connections & consent pages, review queue, settings, and audit log.
- **Per-user isolation (PoC)**: every user gets a fully separate SQLite DB
  and Fernet-encrypted vault under `SMM_DATA_DIR/users/<id>/`, selected per
  request via a user-context variable — no cross-user data paths exist.
- **Scheduling**: a background scheduler thread checks each user's cadence
  (§5.4) every minute and runs due pipelines; one user's failure never
  affects others.
- **Run**: `cd apps/api && uv run uvicorn app.main:app --port 8000`, and
  `cd frontend && npm run dev`. Expose over the internet only behind HTTPS
  (reverse proxy such as nginx/Caddy, or a tunnel for demos).
- **Scale-up path**: swap SQLite-per-user for multi-tenant Postgres
  (row-level security), local key files for a KMS-backed vault, the thread
  for a worker queue, and add email verification + 2FA before public
  launch.

### 8.3 Shared core
CLI and web share the FastAPI domain modules; only the entry point and the
user-context selection differ, so business logic is written once and served
both ways.

---

## 9. Guardrails & Safety Checklist (must hold true at all times)

- [ ] No connected source is read without an active, non-expired consent record.
- [ ] No LinkedIn post is published without either explicit per-post
      approval, or an active Auto-Publish rule that has passed its
      confidence threshold, blocklist check, and cooling-off window.
- [ ] Auto-Publish is off by default and never active in a source's first
      14 days of connection.
- [ ] Manual Input Mode never requires OAuth or third-party account access.
- [ ] Tokens are encrypted at rest; never logged in plaintext.
- [ ] Raw ingested/manual content has a TTL and is purged on schedule
      unless the user explicitly opts to retain it.
- [ ] Every publish action is idempotent and logged with source citation.
- [ ] Users can revoke any single source without affecting others.
- [ ] Users can export/delete all of their data and their account on request.
- [ ] Sensitive content filters (PII, secrets, confidential excerpts) run
      on every draft — connected-source or manual — before it reaches the
      review queue or Auto-Publish pipeline.

---

## 10. Repo Layout (as implemented — PoC)


---

## 11. Implementation Status & Next Steps

**Done (PoC):**
- Consent module: encrypted vault, per-platform scopes, TTL, revoke+purge,
  append-only audit ledger (`./scripts/agent audit` / web Audit page).
- Publisher: Upload-Post multi-platform (`publish:<platform>` scopes),
  idempotency guard, dry-run support, graceful API-error handling.
- Publishing Modes: Review (default) and Auto (opt-in `auto_publish` scope,
  blocklist, daily rate limit, manual-source drafts always reviewed).
- Scheduling: user-chosen cadence (off/1–24 runs per day), CLI
  `schedule` + `daemon`, web background scheduler thread, idempotent runs.
- Manual Input Mode: hints and file uploads, zero consent required
  (CLI + web).
- Sources: GitHub (read-only recent activity, optional PAT; CLI + web),
  Gmail (selected labels, bounded body extraction; web), Google Drive
  (folder-scoped discovery of Docs/text/Markdown/PDF; web), and local
  filesystem (allowlisted paths; CLI only).
- Drafting: OpenAI if `OPENAI_API_KEY` set, template fallback otherwise
  (also falls back gracefully on LLM API errors).
- Web PoC: multi-user register/login, per-user isolated DB + vault,
  dashboard, consent pages, review queue, settings, audit.

**Next:**
1. Cooling-off window + 14-day trust period for Auto-Publish.
2. Google Calendar and additional email providers.
3. Expand sensitive-content filtering beyond Google-source ingestion.
4. Production hardening for web: Google restricted-scope verification,
   HTTPS/reverse proxy, email verification,
   2FA, CSRF tokens, Postgres + KMS adapters, worker queue.
