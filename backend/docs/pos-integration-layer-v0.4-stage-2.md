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

Two read-only attempts on 2026-09-21 used the configured real Quick Resto
account. The first timed out during the TLS handshake; the Stage 2 probe then
reported a connection failure. Neither received an HTTP response or payload.
An unauthenticated transport check established TLS in about 0.2 seconds, after
which the cloud closed the stream with an HTTP/2 protocol error; forcing
HTTP/1.1 produced a connection reset.
The circuit breaker stopped the remaining calls after the global transport
failure while preserving all matrix rows as `DEGRADED`. Documentation-only
surfaces remain `UNKNOWN`; none is promoted to `SUPPORTED`. A later successful
probe may update the matrix without changing discovery code.

## Stage boundary

Stage 2 adds provider evidence only. Stage 3 may implement canonical
normalization for capabilities proven by a successful probe. Existing closed
shift imports and financial consumers remain on their current paths until
separate replay, reconciliation and rollout gates pass.
