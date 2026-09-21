# POS Integration Layer v0.4 — Stage 2

Stage 2 implements conservative Quick Resto capability discovery. It does not
normalize the newly discovered surfaces or write business data.

## Probe scope

The read-only discovery checks each surface independently so one unsupported or
temporarily failing endpoint does not hide evidence from the others:

- open business shift and open orders, including validation that a non-empty
  filtered response contains only `OPEN` rows;
- table schemes and sampled detail structure for restaurant sections/tables;
- modifier groups, modifiers and sampled dish configuration/option structure;
- employees;
- inventory, incoming, outgoing, discard, exchange, cooking, decomposition and
  processing documents;
- explicit `UNKNOWN` results for stop lists and stock balances because API 2.92
  has no documented dedicated read endpoint for them.

An endpoint response alone is insufficient for nested capabilities. Tables,
sections, variants and current order totals require the corresponding sampled
structural path. Derived stock movements require at least one successful
document surface.

## Safe evidence and fixtures

`quickresto_capability_probe.py` stores only field names, structural paths, row
counts, stable error categories and capability states. It never stores field
values, credentials, customer data, employee values, exception text or the
Quick Resto cloud name. The synthetic fixture contains fake values specifically
to verify that none of them can leak into the report.

Run the probe from the backend virtual environment:

```bash
cd backend
.venv/bin/python -m app.scripts.quickresto_capability_probe \
  --sample-limit 5 \
  --timeout-seconds 45
```

The default output is a timestamped JSON file in `/private/tmp`. Supplying
`--output` requires an absolute path.

## Current live evidence

On 2026-09-21 the probe was executed in an isolated temporary checkout on the
production host using the already configured encrypted Quick Resto connection
for venue 21. It did not change the production checkout, database, services or
feature flags. The temporary checkout and report were deleted on exit.

The live result established:

- current shift is `DERIVED`: the server ignored `status=OPEN`, while exact
  `status` and `opened` fields allow local filtering;
- tables, halls, employees, inventory documents, purchases and write-offs are
  `SUPPORTED`;
- stock movements are `DERIVED` from confirmed document surfaces;
- open orders and current order total remain `UNKNOWN`: `OrderInfo` exposes
  table, waiter and amount fields, but not an explicit open/closed state, and
  the requested OPEN filter could not be verified;
- modifiers are `DEGRADED`: both documented class requests returned rows whose
  schema class was `ModifierGroup`;
- variants/configurations, stop lists and stock balances remain `UNKNOWN`.

No payload values, credentials, employee names or customer data were retained.
The synthetic fixture and sanitized live-shape fixture cover the resulting
contract and prevent a field such as `paidByPartner` from being mistaken for an
open-order state.

## Stage boundary

Stage 2 adds provider evidence only. Stage 3 may implement canonical
normalization for capabilities proven by a successful probe. Existing closed
shift imports and financial consumers remain on their current paths until
separate replay, reconciliation and rollout gates pass.
