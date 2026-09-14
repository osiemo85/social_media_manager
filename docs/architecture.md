social-ai-platform/
├── apps/
│   ├── api/                              # FastAPI application
│   │   ├── app/
│   │   │   ├── main.py                   # Application entry point
│   │   │   ├── config/
│   │   │   │   ├── settings.py
│   │   │   │   ├── logging.py
│   │   │   │   └── feature_flags.py
│   │   │   │
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   ├── dependencies.py
│   │   │   │   ├── middleware/
│   │   │   │   └── errors/
│   │   │   │
│   │   │   ├── modules/
│   │   │   │   ├── identity/
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── schemas.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   ├── models.py
│   │   │   │   │   └── repository.py
│   │   │   │   │
│   │   │   │   ├── workspaces/
│   │   │   │   ├── integrations/
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── schemas.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   ├── models.py
│   │   │   │   │   └── providers/
│   │   │   │   │       ├── github.py
│   │   │   │   │       ├── google_drive.py
│   │   │   │   │       ├── email.py
│   │   │   │   │       └── upload_post.py
│   │   │   │   │
│   │   │   │   ├── sources/
│   │   │   │   ├── content/
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── schemas.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   ├── models.py
│   │   │   │   │   └── policies.py
│   │   │   │   │
│   │   │   │   ├── campaigns/
│   │   │   │   ├── publishing/
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── schemas.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   ├── models.py
│   │   │   │   │   ├── state_machine.py
│   │   │   │   │   └── providers/
│   │   │   │   │       └── upload_post.py
│   │   │   │   │
│   │   │   │   ├── scheduling/
│   │   │   │   ├── approvals/
│   │   │   │   ├── memory/
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── schemas.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   ├── retrieval.py
│   │   │   │   │   ├── summarization.py
│   │   │   │   │   └── models.py
│   │   │   │   │
│   │   │   │   ├── analytics/
│   │   │   │   ├── notifications/
│   │   │   │   └── webhooks/
│   │   │   │
│   │   │   ├── shared/
│   │   │   │   ├── database/
│   │   │   │   │   ├── session.py
│   │   │   │   │   ├── base.py
│   │   │   │   │   └── transaction.py
│   │   │   │   ├── events/
│   │   │   │   ├── security/
│   │   │   │   ├── storage/
│   │   │   │   ├── http/
│   │   │   │   ├── pagination.py
│   │   │   │   └── exceptions.py
│   │   │   │
│   │   │   └── workers/
│   │   │       ├── celery_app.py
│   │   │       ├── tasks/
│   │   │       │   ├── ingest_sources.py
│   │   │       │   ├── generate_content.py
│   │   │       │   ├── publish_content.py
│   │   │       │   ├── reconcile_publications.py
│   │   │       │   └── collect_analytics.py
│   │   │       └── schedules.py
│   │   │
│   │   ├── migrations/
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   ├── integration/
│   │   │   ├── contract/
│   │   │   └── e2e/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
├── frontend/                                  # Next.js frontend
│       ├── app/
│       │   ├── page.tsx                       # Sign-in/register landing route
│       │   ├── layout.tsx
│       │   └── (dashboard)/                   # Shared authenticated workspace layout
│       │       ├── layout.tsx
│       │       ├── dashboard/                 # /dashboard
│       │       ├── review/                    # /review
│       │       ├── connections/               # /connections
│       │       ├── settings/                  # /settings
│       │       └── audit/                     # /audit
│       ├── features/                          # Domain-specific UI and client behavior
│       │   ├── identity/components/
│       │   ├── content/components/
│       │   ├── integrations/components/
│       │   ├── settings/components/
│       │   └── audit/components/
│       ├── components/
│       │   └── layouts/                       # Reusable application shells
│       ├── lib/
│       │   └── api-client.ts                  # Shared API client
│       ├── public/
│       ├── tests/
│       │   ├── unit/
│       │   ├── integration/
│       │   └── e2e/
│       ├── package.json
│       └── Dockerfile
│
├── packages/
│   ├── contracts/                         # Shared API schemas and generated types
│   ├── eslint-config/
│   ├── tsconfig/
│   └── ui/                                # Optional shared UI components
│
├── infrastructure/
│   ├── docker/
│   │   ├── docker-compose.dev.yml
│   │   └── docker-compose.test.yml
│   ├── terraform/
│   ├── nginx/
│   └── monitoring/
│
├── scripts/
│   ├── seed_database.py
│   ├── generate_types.py
│   └── run_worker.sh
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── security/
│   └── decisions/
│
│
├── .env.example
├── AGENTS.md
├── Makefile
└── README.md