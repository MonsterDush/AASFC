# Axelio stage 3 operations runbook

This runbook covers managed releases, post-deploy smoke, rollback, Sentry,
structured request logs, encrypted PostgreSQL backups, and restore drills.

## Guarantees

- A push cannot deploy until the `quality` job is green.
- Every release is an exact 40-character commit SHA.
- Production uses the protected GitHub Environment named `production`.
- Production refuses to start without a Sentry DSN.
- A production deployment creates and uploads an encrypted backup before migrations.
- API, database readiness, frontend, release SHA, request ID, services, and Nginx
  are checked after restart.
- A failed deployment automatically restores the previous application SHA.
- Database migrations are never downgraded automatically.
- Release metadata is retained under `/var/www/axelio/<env>/deployments`.

## One-time GitHub setup

In repository settings, create environments named `development` and
`production`. Add required reviewers to `production`. Keep the SSH secrets
available to both environments:

- `SSH_HOST`
- `SSH_USER`
- `SSH_KEY`
- `SSH_PORT`

Without required reviewers GitHub still records a production deployment, but
it does not provide a human approval gate.

## Sentry setup

Create separate Sentry projects or environments for dev and production. Put
the DSN only in the server-side backend `.env`:

```dotenv
SENTRY_DSN=https://public-key@your-sentry-host/project-id
SENTRY_TRACES_SAMPLE_RATE=0.05
LOG_JSON=true
LOG_LEVEL=INFO
```

The deploy script writes `RELEASE_VERSION=<commit SHA>`. Events are tagged with
`environment` and `axelio@<commit SHA>`. Default PII is disabled; request
bodies, cookies, authorization headers, Telegram webhook secrets, and Sentry
user data are removed before sending an event.

Production configuration validation fails when `SENTRY_DSN` is empty. Start
with a small trace sample and adjust it only after observing event volume.

## Encrypted offsite backup setup

Install PostgreSQL client tools, OpenSSL, and rclone on the VPS. Configure an
offsite rclone target whose storage is not on the Axelio production server.
The example below assumes the target is named `s3-compatible`.

```bash
sudo install -d -m 0700 /etc/axelio
sudo install -m 0600 \
  /var/www/axelio/prod/repo/ops/backup/backup-prod.env.example \
  /etc/axelio/backup-prod.env
sudoedit /etc/axelio/backup-prod.env
sudo chmod 0600 /etc/axelio/backup-prod.env
sudo rclone lsd s3-compatible:
```

Generate a dedicated encryption password and store it in a password manager as
well as `/etc/axelio/backup-prod.env`:

```bash
openssl rand -base64 48
```

The required file contains:

```dotenv
BACKUP_ENCRYPTION_PASSWORD=<long random secret>
BACKUP_RCLONE_REMOTE=s3-compatible:axelio-production-backups
RCLONE_CONFIG=/etc/axelio/rclone.conf
```

The production deployment refuses to migrate the database when this file is
missing, the backup cannot be decrypted and inspected, or the offsite upload
fails.

The timer keeps seven daily and four weekly local copies. The offsite retention
policy must also be configured on the storage provider. Initial objectives:
RPO 24 hours, RTO 4 hours.

## Release flow

Every push to `develop` also runs `production_readiness`. It checks the production Sentry and backup configuration, then creates and uploads a real encrypted backup using the candidate scripts. Do not merge `develop` to `main` unless quality, development deployment, and production readiness are all green.

The normal flow is:

```text
push -> quality -> environment approval -> encrypted backup -> migration
     -> service restart -> public smoke -> release metadata
```

The workflow extracts the deployment tools from the exact tested SHA before it
changes the server checkout. A queued stale workflow run is skipped if its SHA
is no longer the head of the branch.

Inspect the active and previous releases:

```bash
sudo cat /var/www/axelio/prod/deployments/current.sha
sudo cat /var/www/axelio/prod/deployments/previous.sha
sudo cat /var/www/axelio/prod/deployments/*.metadata
```

## Post-deploy smoke

Run the smoke manually when investigating an incident:

```bash
API_BASE_URL=https://api.axelio.ru \
FRONTEND_BASE_URL=https://app.axelio.ru \
EXPECTED_RELEASE="$(sudo cat /var/www/axelio/prod/deployments/current.sha)" \
PYTHON_BIN=/var/www/axelio/prod/venv/bin/python \
/var/www/axelio/prod/repo/ops/deploy/post-deploy-smoke.sh
```

The smoke requires:

- `/health/ready` with a working database connection;
- the expected release SHA;
- an `X-Request-ID` response header;
- a reachable `auth.html` frontend page.

## Rollback

Preferred procedure: run the GitHub Actions workflow `Rollback`, choose
`production`, leave `target_sha` empty to select the recorded previous release,
and approve the production Environment. A specific target must be a full commit
SHA contained in `main`.

Rollback reinstalls the selected release requirements, restarts services, and
runs smoke. It does not rewrite Git history and must not use `git push --force`.

Application rollback does not downgrade Alembic. Migrations must remain
backward compatible. If data restoration is required, stop writes, preserve the
failed database, and follow the restore procedure below.

## Backup verification and restore drill

Check the last scheduled backup:

```bash
sudo systemctl status axelio-backup-prod.timer --no-pager
sudo systemctl status axelio-backup-prod.service --no-pager
sudo journalctl -u axelio-backup-prod.service -n 100 --no-pager
sudo find /var/backups/axelio/prod -maxdepth 2 -type f -print
```

Run a restore drill only into a dedicated database whose name ends with
`_restore_drill`:

```bash
cd /var/www/axelio/prod/repo
set -a
source backend/.env
source /etc/axelio/backup-prod.env
set +a
RESTORE_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST/axelio_restore_drill' \
BACKUP_REQUIRE_OFFSITE=false \
ops/backup/restore-drill.sh
```

The drill creates a fresh encrypted backup, verifies its checksum and archive,
restores it into a clean database, applies outstanding migrations, compares
critical table row counts, reports elapsed time, and removes the drill database.
CI performs the same drill against seeded PostgreSQL data on every change.

Record every quarterly production-data drill with date, source backup, operator,
actual RPO, actual RTO, row-count result, migration result, and follow-up issues.

The preferred procedure is the GitHub Actions workflow `Production assurance
drill` in `all` or `restore` mode on `main`. It creates a fresh encrypted
production snapshot, restores it only into the suffixed drill database, runs
migrations, compares critical row counts, removes the drill database, and writes
an auditable RPO/RTO report under
`/var/www/axelio/prod/deployments/drills`. Run it after material backup changes
and at least quarterly even when the scheduled backups remain green.

## Structured logs and request correlation

Every API response includes `X-Request-ID`. A safe incoming ID is preserved;
otherwise the API generates one. Request logs contain method, route, path,
status, duration, environment, release, request ID, and venue ID when it is
present in the route.

```bash
sudo journalctl -u axelio-api-prod -n 100 --no-pager -o cat | jq .
sudo journalctl -u axelio-api-prod -o cat | jq \
  'select(.request_id == "REQUEST_ID_FROM_RESPONSE")'
```

Never add passwords, OTPs, access tokens, cookies, full payment details, or
unnecessary personal data to logging extras.
