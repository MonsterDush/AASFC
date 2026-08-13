# Axelio engineering architecture

## Runtime boundaries

1. Nginx serves the static frontend and proxies API traffic.
2. The FastAPI application authenticates browser/Telegram sessions, enforces
   venue permissions and billing state, and commits domain changes to
   PostgreSQL.
3. The Telegram bot handles bot-facing interaction. Durable notification jobs
   are persisted by the API and delivered by systemd workers/timers.
4. PostgreSQL is the system of record for identity, memberships, shifts,
   reports, finance, payroll, billing, and notification delivery state.
5. Sentry receives scrubbed application failures. Structured systemd logs retain
   request IDs, release SHA, environment, route, status, and duration.
6. The production monitor samples service, API, database/business, and backup
   guardrails every five minutes and sends deduplicated Telegram alerts and
   recovery notices.

## Code boundaries

- Routers own HTTP validation, access guards, transaction boundaries, and
  response serialization. Domain calculations belong in `backend/app/services`.
- Models own persistence shape only. Schema changes require Alembic migrations.
- Large frontend entry points are compatibility/orchestration facades. New
  cohesive behavior belongs in bounded modules under `frontend/app`,
  `frontend/staff-shifts`, or the page-specific module directory.
- `ops` files are release code. Changes require contract tests and a runbook just
  like application changes.

## Release and recovery model

The commit SHA is the release identity. CI verifies a commit before the managed
release script activates it. The script snapshots the previous SHA, takes the
required production backup before migration, installs tracked systemd/Nginx
assets, restarts services, and executes an external smoke. A failed activation
automatically reactivates the previous SHA. Manual rollback remains available
through the protected GitHub environment.

The recovery hierarchy is: retry an idempotent job, roll back the application,
restore an encrypted backup to an isolated drill database, validate counts and
migrations, and only then schedule a reviewed production restore.
