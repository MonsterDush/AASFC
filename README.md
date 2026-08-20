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
pnpm test:frontend-quality

cd backend
python -m coverage run --branch --source=app -m unittest discover -s test -v
cd ..

pnpm test:budgets
pnpm test:i18n
node frontend/app_split_check.mjs
node frontend/staff_shifts_split_check.mjs
```

For the PostgreSQL-backed browser scenarios, copy `.env.e2e.example` to
`.env.e2e`, then run `tools/e2e-local.sh up` and
`tools/e2e-local.sh browser`. The browser gate covers 12 owner, staff, and
public-demo scenarios at both 1440x900 and 375x812, critical/serious WCAG
violations, responsive overflow, API 5xx, uncaught JavaScript errors, and page
performance budgets. A separate isolated owner/admin coverage tour exercises
the remaining read surfaces and representative create, update, export, and
delete workflows before the fixture is rebuilt.

## Engineering guarantees

Every pull request and push to `develop` or `main` runs compilation,
repository-wide lint and formatting including unused imports, combined unit and
browser branch coverage (60% globally and at least 75% for critical modules),
PostgreSQL migration round-trip, secret scanning, SAST, dependency audits,
frontend contracts, browser E2E, encrypted backup/restore, and source/per-page
performance budgets. Production releases also require
Sentry, encrypted offsite backup, Telegram alert recipients, post-deploy smoke,
automatic rollback on activation failure, and a dispatchable production
restore/observability drill with recorded RPO and RTO.

Operational and contributor references:

- [Architecture](backend/docs/architecture.md)
- [Engineering stage 3: deploy, rollback, Sentry, backups](backend/docs/engineering-stage3-runbook.md)
- [Engineering stage 4: metrics, alerts, accessibility, performance](backend/docs/engineering-stage4-runbook.md)
- [Engineering assurance baseline](backend/docs/engineering-assurance.md)
- [Production rollback drill evidence](backend/docs/production-rollback-drill-2026-08-20.md)
- [Russian and English localization](backend/docs/localization.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
