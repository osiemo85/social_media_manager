# FastAPI service

Run from this directory with `uv`:

```bash
cd apps/api
uv sync --all-groups
uv run uvicorn app.main:app --reload --port 8000
```

The service exposes the consent-gated workflows under `/api`. Domain logic is
organized under `app/modules`, shared infrastructure under `app/shared`, and
pipeline orchestration under `app/workers`.

Google source setup uses the shared callback
`http://localhost:3000/api/connections/google/callback` in local development.
Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and
`SMM_GOOGLE_SOURCES_ENABLED=true`. Gmail and Drive grants, policies, tokens,
and revocations remain separate inside the application.
