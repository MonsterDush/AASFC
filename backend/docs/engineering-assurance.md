# Engineering assurance baseline

This document is the canonical checklist for the engineering guarantees that
protect Axelio changes before promotion from a branch to `develop` and `main`.
The executable source of truth is `.github/workflows/deploy.yml`; this page
explains the intent, required configuration, and local reproduction commands.

## Quality and coverage

Backend unit tests run under branch coverage. The browser E2E API process runs
under a second coverage session, and CI combines both data files before applying
the global 60% gate. `tools/check_critical_coverage.py` additionally requires at
least 75% for every listed critical module, with stricter thresholds for token,
password, permission, privacy, rate-limit, and signed-link code.

The browser suite has exactly 12 named scenarios. It runs the same set at
1440x900 and 375x812: owner and staff authentication, owner venue list, summary,
expenses, payroll, settings, positions, day economics, staff shifts and salary,
and the public read-only demo. Every scenario rejects uncaught JavaScript errors,
API 5xx responses, critical/serious axe-core findings, horizontal overflow, and
performance-budget regressions.

Local reproduction requires PostgreSQL 16 and the synthetic E2E environment:

```bash
cd backend
python -m coverage run --branch --source=app -m unittest discover -s test -v
python -m coverage report --show-missing
cd ..
tools/e2e-local.sh up
tools/e2e-local.sh browser
```

## Security and frontend quality

CI scans full Git history with Gitleaks, runs Bandit against backend and bot
runtime code, runs GitHub CodeQL for Python and JavaScript/TypeScript, and audits
Python and pnpm dependencies. ESLint, Prettier, TypeScript checking, Python Ruff,
shell syntax, and tracked-file hygiene are blocking gates.

The hygiene gate rejects copy-style source names, generated dependency/cache
directories, source files above 512 KiB, and all other tracked files above
2 MiB. Compress or split an offender, or store it outside Git; do not weaken the
limit just to pass CI.

## Public lead CAPTCHA

Public lead submission supports Cloudflare Turnstile server-side validation.
Production configuration is:

```dotenv
PUBLIC_LEAD_CAPTCHA_REQUIRED=true
TURNSTILE_SITE_KEY=<public widget site key>
TURNSTILE_SECRET_KEY=<server-only secret key>
TURNSTILE_EXPECTED_ACTION=public_lead
TURNSTILE_ALLOWED_HOSTNAMES=axelio.ru,www.axelio.ru
TURNSTILE_TIMEOUT_SECONDS=5
```

The public landing page must render the widget with action `public_lead` and send
the resulting token as `captchaToken` in `POST /public/leads`. The landing page
is deployed separately from this repository, so enabling the required flag
before that client change would intentionally fail closed. Never expose the
secret key to the browser. Server validation checks success, action, hostname,
token length, provider availability, and rate limits before notification.

Reference: <https://developers.cloudflare.com/turnstile/get-started/server-side-validation/>.

## Browser error tracking and source maps

The deploy script writes `frontend/runtime-config.json` atomically from the
protected backend environment. Browser Sentry is disabled when no DSN is
configured and otherwise uses the exact release SHA, environment, bounded trace
sample, disabled default PII, and a scrubber for credentials and request data.
The early-error queue captures failures that occur before the Sentry bundle is
ready.

Runtime configuration:

```dotenv
SENTRY_BROWSER_DSN=<browser-safe DSN; falls back to SENTRY_DSN>
SENTRY_BROWSER_TRACES_SAMPLE_RATE=0.05
```

GitHub Actions repository or Environment secrets required for source-map upload:

- `SENTRY_AUTH_TOKEN`
- `SENTRY_ORG`
- `SENTRY_PROJECT`

`pnpm build:error-tracking` creates a minified bundle plus an external source
map with embedded sources and injected debug IDs. The push workflow uploads the
map for release `axelio@<commit SHA>` before deployment and fails closed if any
upload secret is missing.

The reviewed bundle-specific source budget is 90,000 bytes because the minified
Sentry browser runtime is loaded asynchronously as an isolated asset; the
current gzip transfer is about 30 KiB. All other JavaScript retains the stricter
80,000-byte source limit.

## Versioned static caching

`ops/nginx/axelio-cache-map.conf` assigns
`Cache-Control: public, max-age=31536000, immutable` only to supported static
extensions with a non-empty `v` query parameter. `runtime-config.json` is
explicitly `no-store`; HTML, API responses, and unversioned assets keep their
normal revalidation behavior. The release installs the HTTP-context map, the
server snippet uses it, and post-deploy smoke verifies the real public response
header.

## Operations evidence

Managed production rollback and recovery evidence is recorded in
`production-rollback-drill-2026-08-20.md`. Stage 3 and stage 4 runbooks remain the
operational procedures for deployment, backups, restore drills, Sentry,
monitoring, alerts, and incident response.
