# Axelio audit source notes

## Scope

- Repository: Axelio at commit `b7b4eb1dcf82ec7b2c2a740b5b1b8a7784360661` on `develop`.
- Audit date: 2026-08-11, Europe/Moscow.
- Surfaces: repository, isolated PostgreSQL E2E, current local frontend/backend, production and dev HTTP/browser behavior.

## Confirmed checks

- Backend: 268 unit tests passed; branch coverage 41% across 20,169 statements and 5,512 branches.
- Bot: 16 tests passed.
- Python compile and tracked JavaScript/ES module syntax checks passed.
- Frontend contract checks for app facade, setup, positions, staff shifts, payroll, finance ledger, finance summary, revenue and CSS passed.
- Alembic reports one current head. A clean PostgreSQL 16 instance accepted all 63 migrations.
- Full night-shift E2E completed payroll, finance, notification and XLSX paths.
- Production owner demo pages were checked on desktop and 375 px mobile. Public staff demo produced 503 px horizontal overflow at 375 px; the current authenticated local staff calendar did not.
- Live frontend/API response headers were inspected for production and dev.
- Accessibility inspection covered landmarks, headings, accessible names, images and focusable controls on the owner summary.

## Score calculation

Weighted total: `(8.8×15 + 7.7×12.5 + 8.0×15 + 5.2×15 + 6.0×12.5 + 6.5×10 + 4.8×7.5 + 5.4×5 + 4.8×7.5) / 100 = 6.6525`, rounded to `6.7`.

## Visual plan

- Native bar chart: compare all nine criterion scores on the same 0–10 scale.
- Detail table: preserve exact weights, scores, overall deductions and reasons.
- Omitted extra charts because the audit has one primary comparison; additional visuals would repeat the same evidence rather than improve interpretation.
