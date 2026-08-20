# Contributing to Axelio

## Branch and change scope

Create a focused branch from `develop`. Keep migrations, runtime code, tests,
runbooks, and deployment assets in the same change when they form one release
contract. Never commit `.env` files, production data, generated browser
artifacts, backup archives, or credentials.

## Definition of done

A change is ready when:

1. New behavior has a unit, contract, or browser regression test.
2. Database changes include an Alembic migration that survives the PostgreSQL
   upgrade/downgrade/upgrade smoke.
3. UI changes pass owner/staff/demo E2E at the relevant desktop and mobile
   viewport without horizontal overflow.
4. Critical and serious axe-core WCAG violations are zero on gated pages.
5. Asset and page performance measurements remain within
   `tools/performance-budgets.json`; budget increases require a written reason.
6. New operational failure modes have a metric, alert, or runbook response.
7. Public behavior, configuration, and on-call procedures are documented.
8. Tracked files satisfy `tools/check_repository_hygiene.py`; source files stay
   at or below 512 KiB and other files at or below 2 MiB.

## Required checks

Run the checks that match the change locally. The authoritative complete set is
the `quality` job in `.github/workflows/deploy.yml`.

```bash
python -m ruff check --select E9,F63,F7,F82 backend/app backend/test bot_service tools
python -m ruff check backend/app backend/test bot_service tools
python -m ruff format --check backend/app backend/test bot_service tools
python tools/check_repository_hygiene.py
python -m bandit -q -r backend/app bot_service -x backend/test -ll
pnpm test:frontend-quality
pnpm test:budgets

cd backend
python -m coverage run --branch --source=app -m unittest discover -s test -v
cd ../bot_service
python -m unittest discover -s test -v
```

The repository-wide lint gate covers every configured Ruff rule, including
unused imports. Compatibility facades declare their intended re-exports with
redundant aliases, so a plain import remains distinguishable from public API.
The formatting gate covers all maintained backend, test, bot, and Python tool
code; Alembic migration history remains excluded by the Ruff configuration.

Do not weaken a coverage, accessibility, security, dependency, or performance
gate merely to make CI green. Fix the regression, or document and review a
deliberate threshold change in the same pull request.

## Release flow

Merge verified changes to `develop` first. The managed workflow deploys the
exact commit to development after quality passes. Merge to `main` only after the
development run and production-readiness job are green. Production activation
uses the same release script and rolls back automatically if migration,
services, Nginx validation, or smoke checks fail.
