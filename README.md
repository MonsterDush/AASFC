# Axelio

Axelio is a web and Telegram application for venue shifts, reports, payroll,
expenses, day economics, billing, and operational notifications. The repository
contains the FastAPI backend, browser frontend, Telegram bot, database
migrations, tests, and production operations code.

## Repository map

- `backend/app` — API, domain services, jobs, and models.
- `backend/alembic` — PostgreSQL migrations.
- `backend/test` — unit, contract, and regression tests.
- `frontend` — dependency-light HTML, CSS, and JavaScript application.
- `bot_service` — Telegram bot runtime and tests.
- `ops` — deploy, rollback, backup, monitoring, Nginx, and systemd assets.
- `tools` — migration, browser E2E, coverage, hygiene, and budget gates.

## Local verification

Use Python 3.12+, Node.js 22, pnpm 11.16, and PostgreSQL 16.

```bash
python -m pip install -r backend/requirements-dev.txt -r bot_service/requirements.txt
pnpm install --frozen-lockfile

cd backend
python -m coverage run --branch --source=app -m unittest discover -s test -v
cd ..

pnpm test:budgets
node frontend/app_split_check.mjs
node frontend/staff_shifts_split_check.mjs
```

For the PostgreSQL-backed browser scenarios, copy `.env.e2e.example` to
`.env.e2e`, then run `tools/e2e-local.sh up` and
`tools/e2e-local.sh browser`. The browser gate covers owner, staff, and public
demo journeys, critical/serious WCAG violations, responsive overflow, API 5xx,
uncaught JavaScript errors, and page performance budgets.

## Engineering guarantees

Every pull request and push to `develop` or `main` runs compilation,
repository-wide lint including unused imports, critical-module formatting, branch coverage,
PostgreSQL migration round-trip,
dependency audits, frontend contracts, browser E2E, encrypted backup/restore,
and source/per-page performance budgets. Production releases also require
Sentry, encrypted offsite backup, Telegram alert recipients, post-deploy smoke,
automatic rollback on activation failure, and a dispatchable production
restore/observability drill with recorded RPO and RTO.

Operational and contributor references:

- [Architecture](backend/docs/architecture.md)
- [Engineering stage 3: deploy, rollback, Sentry, backups](backend/docs/engineering-stage3-runbook.md)
- [Engineering stage 4: metrics, alerts, accessibility, performance](backend/docs/engineering-stage4-runbook.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
