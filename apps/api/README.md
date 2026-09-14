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
