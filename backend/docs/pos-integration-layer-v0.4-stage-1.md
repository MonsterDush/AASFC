# POS Integration Layer v0.4 — Stage 1

Stage 1 adds provider-neutral contracts and storage. It deliberately does not
switch report, finance, payroll, or analytics reads.

## Provider boundary

The former monolithic adapter remains as a compatibility composition of
discovery and historical reads. New providers can expose these independent
contracts:

- `ProviderDiscoveryAdapter`: credentials, health, capabilities, limits, and
  account scope discovery;
- `ProviderReadAdapter`: historical canonical facts;
- `ProviderOperationalAdapter`: current shift, open orders, tables, and halls;
- `ProviderCommandAdapter`: idempotent command submission and status checks;
- `ProviderWebhookAdapter`: signature verification, identity, and parsing;
- `ProviderLoyaltyAdapter`: customers, wallets, coupons, and programs.

Having a method is not proof of support. A capability becomes `SUPPORTED` only
after a successful provider probe with evidence.

## Multi-scope accounts

`ProviderScope` supports many organizations, venues, terminal groups,
terminals, sale places, and stores. An `IntegrationConnection` still belongs to
one Axelio venue and records the selected external organization and venue.
Provider discovery must never silently choose the first organization, venue,
terminal group, or warehouse.

## Canonical additions

- restaurant sections, tables, terminal groups;
- product option groups, options, variants;
- modifier groups, modifiers, product rules, and order-item modifiers;
- product/variant/modifier stop-list entries;
- generic inventory document fields for purchases, outgoing invoices,
  write-offs, inventory, production, transformation, and transfers;
- operational order fields (`current_amount`, source status, table and terminal
  group) while retaining historical `net_amount`.

## Safety boundaries

`POSOperationalSnapshot` stores encrypted, compacted realtime observations. Its
open-order amount is never a financial fact. Closed revenue remains separate
and existing financial reads remain unchanged.

Commands and webhook payloads use separate encryption domains. Commands are
idempotent per connection and preserve asynchronous provider states. Webhooks
are deduplicated by provider event identity or by payload hash and a five-minute
bucket. A webhook schedules normalization/reconciliation; it does not write
canonical facts directly.

`SyncRequest` provides provider-neutral strategies (`FULL_REFRESH`,
`DATE_RANGE`, `UPDATED_SINCE`, `REVISION`, `WEBHOOK_FIRST`, `REALTIME_POLL`) and
maps work to realtime, normal, or bulk queues. Provider responses must still
follow raw-first processing before normalization.

## Deferred to later stages

Stage 1 does not claim live Quick Resto or iiko capability support, add provider
commands, expose realtime UI, or change canonical read flags. Those require
provider probes, reconciliation, and rollout gates from subsequent stages.
