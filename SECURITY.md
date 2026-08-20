# Security policy

## Reporting a vulnerability

Do not open a public issue containing an exploit, credential, personal data, or
production endpoint detail. Send a private report to the Axelio operator through
the existing support channel with:

- affected component and environment;
- reproduction steps and required permissions;
- observed and expected behavior;
- impact assessment;
- safe proof of concept with secrets and personal data removed.

The operator should acknowledge the report within two business days, classify
severity, preserve evidence, and coordinate a fix and disclosure window. There
is no promise of a bounty unless agreed separately in writing.

## Supported code

`main` is the supported production line. Security fixes are validated in
`develop`, then promoted to `main` through the normal quality and readiness
gates. For an actively exploited critical issue, isolate the affected path,
rotate exposed credentials, preserve logs, deploy the smallest safe fix, and
run the production smoke and rollback checks.

## Secrets and production data

- Store runtime secrets only in protected environment files or GitHub
  Environment secrets, never in Git, logs, screenshots, fixtures, or artifacts.
- Treat access tokens, cookies, Telegram tokens, Sentry DSNs, database URLs,
  backup encryption passwords, and rclone configuration as secrets.
- Use synthetic E2E records. Do not copy production personal or financial data
  into local tests.
- Rotate a secret immediately if it appears in a commit, CI log, chat, or
  artifact; deleting the visible value is not sufficient.
- Gitleaks scans repository history, Bandit and CodeQL scan application code,
  and dependency audits block known high-risk packages in CI.
- Public lead CAPTCHA fails closed when required, and browser error tracking
  scrubs credentials, request data, cookies, and user context before delivery.

See `backend/docs/engineering-stage3-runbook.md` for rollback, backup restore,
and Sentry evidence, and `backend/docs/engineering-stage4-runbook.md` for alerts
and operational triage. Current gate configuration and required CAPTCHA/Sentry
settings are in `backend/docs/engineering-assurance.md`.
