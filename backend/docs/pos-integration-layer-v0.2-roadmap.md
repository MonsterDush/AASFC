# POS Integration Layer v0.2: staged delivery

The implementation is split into three stages so the existing QuickResto production path can remain operational until the provider-neutral path has equivalent contracts and regression coverage.

## Stage 1 — safe foundation (this branch)

Status: implemented locally, pending review and merge.

- Introduce a provider-neutral `POSProvider` contract, provider registry, DTOs, capability audit, and explicit unavailable-capability behavior.
- Store generic integration connections and per-capability states without replacing `QuickRestoConnection`.
- Encrypt provider credential bundles by reusing the existing integration encryption domain; plaintext and legacy unversioned values are rejected.
- Store lossless raw provider JSON with a deterministic SHA-256 hash, idempotent upsert identity, source/receipt timestamps, and normalization version markers.
- Introduce the P0 Axelio canonical data model (ACDM): venues, terminals, employees/mapping, products/groups/prices, orders, items, events, payments, refunds, and discounts.
- Add an explicit venue timezone used later to derive provider business dates safely.
- Keep all existing routes, background jobs, models, and services under `app.services.integrations` unchanged.

Acceptance gates:

- a single Alembic head and an upgrade/downgrade round trip;
- provider/registry, capability, credential, raw-layer, and P0 persistence contract tests;
- existing QuickResto and frontend integration contract suites remain green;
- no switch of production reads or writes to the new tables.

## Stage 2 — P0 provider adapters and controlled migration

- Implement QuickResto and iiko adapters behind `POSProvider`.
- Normalize venues, terminals, employees, products, orders/items/events, payments, refunds, and discounts into ACDM.
- Add paginated historical backfill plus incremental synchronization with provider cursors.
- Dual-write or shadow-write from the existing QuickResto path; compare totals, counts, business dates, mapping outcomes, and historical coverage.
- Introduce an explicit per-venue read switch only after reconciliation is green; preserve rollback to the legacy path.

## Stage 3 — P1/P2 operational depth

- Add recipes, warehouses, stock balances/movements, suppliers, purchases, write-offs, inventories, and attendance where the capability audit confirms availability.
- Add durable sync runs/cursors, retry queues, quarantine, validation rules, freshness/degraded-state monitoring, and data-quality dashboards.
- Add provider golden fixtures and cross-provider parity tests.
- Retire provider-specific storage only after every connected venue has passed reconciliation and rollback gates.

## Compatibility rule

Stage 1 is additive. Nothing registers an adapter globally, calls a provider, schedules synchronization, or changes the existing QuickResto selection/import flow. Later stages must keep the legacy path available until a venue-specific migration is explicitly completed and verified.
