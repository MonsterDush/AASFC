# Engineering stage 4 runbook

This runbook covers the fourth engineering-assurance stage: application
metrics, actionable alerts, accessibility and performance gates, source-size
guardrails, and the operational checks required after deployment.

## 1. Production configuration

Add an explicit high-entropy metrics token and one or more Telegram chat/user
IDs to `/var/www/axelio/prod/repo/backend/.env`:

```dotenv
METRICS_TOKEN=replace-with-a-long-random-secret
AXELIO_ALERT_TG_CHAT_IDS=123456789
BOT_SERVICE_URL=https://bot-internal.example.com
BOT_SERVICE_SECRET=replace-with-a-shared-high-entropy-secret
```

`SUPER_ADMIN_TG_USER_IDS` is accepted as an alert-recipient fallback. A
production-readiness run fails if neither recipient setting is present or the
separate bot-service transport is not configured. The application VPS never
contacts Telegram directly: alerts go through the authenticated bot service on
the Telegram VPS. Do not paste the real secret or IDs into Git, CI logs, or
support messages.

The release installs and enables `axelio-monitor-prod.timer`. It runs every five
minutes and checks:

- API and bot services plus shift, notification, and backup timers;
- `/health/ready`, database readiness, and API latency;
- encrypted backup existence, age, checksum, and metadata;
- failed payments during 24 hours;
- open high/critical billing reconciliation issues;
- failed or stale notification jobs.

Terminal notification failures remain visible in the database and metrics for
forensics. Pager-style alerts use a rolling 24-hour window so a resolved
historical delivery failure does not keep production permanently red.

Alerts are deduplicated by the current failure set. A separate recovery message
is sent after all checks return to green.

Run the GitHub Actions workflow `Production assurance drill` in
`observability` mode after changing metrics or alerts and at least quarterly.
It verifies the authenticated public metrics endpoint, executes the real
production monitor, sends a clearly labelled Telegram test alert followed by a
recovery message, and records its last successful timestamp. It does not induce
a production outage.

## 2. Activation and verification

The Nginx include is a one-time reviewed server change. Follow
`ops/nginx/README.md` for both the security and performance snippets before
promoting the first stage-4 release.

After the deployment:

```bash
sudo systemctl status axelio-monitor-prod.timer --no-pager
sudo systemctl start axelio-monitor-prod.service
sudo systemctl status axelio-monitor-prod.service --no-pager
sudo journalctl -u axelio-monitor-prod.service -n 100 --no-pager
sudo cat /var/lib/axelio-monitoring/monitor-last-success.timestamp
```

The oneshot service exits non-zero while a guardrail is failing. That is an
alert state, not a broken timer; inspect `last-alert.txt`, remediate the listed
cause, and rerun the service.

## 3. Prometheus endpoint and rules

`GET /metrics` exposes release, process, request count/latency, auth/rate-limit,
database, pool, notification, billing, backup, and deployment-smoke metrics in
Prometheus text format. Loopback clients need no token. Remote scrapers must use
one of:

```text
Authorization: Bearer <METRICS_TOKEN>
X-Metrics-Token: <METRICS_TOKEN>
```

Unauthorized remote requests deliberately return 404. Example verification:

```bash
curl --fail --silent \
  --header "Authorization: Bearer ${METRICS_TOKEN}" \
  https://api.axelio.ru/metrics | grep '^axelio_build_info'
```

Import `ops/monitoring/prometheus-alerts.yml` into the existing Prometheus rule
loader and route its `critical` and `warning` severities through the existing
Alertmanager. Validate rules with `promtool check rules` before reload. The
systemd/Telegram monitor remains the minimum working alert path when Prometheus
is unavailable.

## 4. Alert response

- API/service down: inspect the named unit and request-correlated logs, then use
  the managed rollback if the current release caused the failure.
- Readiness/database error: stop mutations if integrity is uncertain, inspect
  PostgreSQL connectivity and locks, and do not restart repeatedly without a
  diagnosis.
- Stale backup: run `axelio-backup-prod.service`, confirm offsite upload, then
  run the isolated restore drill from the stage-3 runbook.
- Failed/stale notification job: inspect `last_error`, attempts, lock age, and
  idempotency key before retrying or returning a job to `pending`.
- Payment/reconciliation alert: compare provider event, billing transaction,
  venue state, and reconciliation fingerprint before any manual correction.

Record the alert time, release SHA, request/job IDs, action, result, and follow-up
test in the incident note.

## 5. Accessibility and performance gates

`tools/browser-e2e.mjs` runs axe-core on authentication, owner summary,
expenses, payroll, settings, staff shifts, and public demo pages. Any critical
or serious WCAG 2.0/2.1/2.2 A/AA violation fails CI. It also fails on uncaught
browser errors, API 5xx, or horizontal overflow.

`tools/performance-budgets.json` is the reviewed source of asset and page limits.
The static gate caps individual JavaScript, CSS, and HTML files. Browser E2E
caps ready time, request count, transferred bytes, and DOM nodes for each key
page. Update a budget only with measurements and an explanation of why the new
cost is intentional.

Run locally:

```bash
pnpm test:budgets
tools/e2e-local.sh up
tools/e2e-local.sh browser
```

New behavior should be extracted into bounded modules instead of expanding a
large facade. Existing split-contract checks preserve public exports, API call
manifests, DOM bindings, and synchronized mutable state during decomposition.
