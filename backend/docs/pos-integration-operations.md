# POS integration operations

The provider-neutral POS worker is intentionally separate from the legacy
QuickResto timer. The legacy timer remains authoritative for existing
QuickResto report imports; canonical shadow writes stay additive until a venue
passes reconciliation and its read switch is explicitly enabled.

## Runtime

`app.scripts.process_pos_integration_jobs` is run every minute by
`axelio-pos-integration-{dev,prod}.timer`. Each invocation enqueues due work and
processes at most 100 jobs. Work is claimed in this order:

1. `CRITICAL`: five-minute sales and fifteen-minute connection health checks;
2. `NORMAL`: catalog, employee, warehouse, stock, purchase, write-off,
   inventory, and attendance synchronization;
3. `BULK`: historical backfills and daily 14–30 day Raw Layer to ACDM
   reconciliation.

The queue uses durable idempotency keys and retries with bounded exponential
backoff. A worker also releases a job left in `RUNNING` for more than 30 minutes
after a process crash; the same attempt limit still applies. Historical imports
are placed in the `BULK` queue instead of keeping an owner HTTP request open. A
connection becomes `DEGRADED` after a provider/job failure or a partial batch.
No job changes a venue from `LEGACY` to `CANONICAL` read mode.

## Capability configuration

Availability is based on a successful API probe for the exact connection.
Provider marketing claims do not enable capabilities.

- iiko P1/P2 exports are configured as an encrypted `extended_endpoints` map.
  Only relative `/api/1/...` paths on the configured `*.iiko.services` host are
  accepted.
- QuickResto P1/P2 exports are configured as encrypted `object_types` entries
  containing `module_name` and `class_name`. Unknown object types are never
  guessed by the adapter.

After changing configuration, run the capability probe and confirm the
capability is `AVAILABLE` before enqueueing a backfill.

## Quarantine and data quality

Raw payloads are saved before normalization. Invalid objects are isolated in
`integration_quarantine`; other records in the same page continue. Blocking
rules include negative revenue, closed paid orders without payments, non-zero
orders without items, purchases without suppliers, inventory rows without a
product identity, duplicate normalized identities, normalization errors, and
persistence errors. Unknown employee/product/warehouse references are warnings
and remain visible for review.

Use `GET /venues/{venue_id}/integrations/{provider}/operations` for freshness,
open issue counts, and recent jobs. The quarantine list deliberately omits raw
payloads to avoid exposing provider PII through the management UI.

## Rollout and rollback

1. Keep `read_mode=LEGACY` and enable QuickResto canonical shadow writes.
2. Complete the 12-month backfill (24 when the provider and volume permit).
3. Confirm employee mappings and resolve every blocking quarantine issue.
4. Run source reconciliation for the intended coverage; unexplained monetary
   difference must be zero.
5. Enable canonical reads for one venue only. Observe freshness, partial/failed
   jobs, quarantine, and reconciliation alerts.
6. Roll back immediately with the legacy read-mode endpoint if any business
   metric differs. Provider-specific legacy tables are not removed by this
   stage.

Do not claim a provider or P1/P2 capability as production-verified without an
observed API probe using credentials for that connection.
