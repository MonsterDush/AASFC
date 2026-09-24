# POS Integration Layer v0.4 — Stage 3

Stage 3 expands Quick Resto only across capabilities confirmed by the Stage 2
live probe. The historical `CLOSED Shift -> OrderInfo -> DailyReport` flow is
unchanged and remains the source used by Reports, Finance and Payroll.

## Implemented scope

- `CURRENT_BUSINESS_SHIFT` is derived by paginating `Shift` and applying the
  exact `status in {OPEN, OPENED}` predicate locally. The live account uses
  `OPENED`; the server-side status filter is not trusted.
- `RESTAURANT_SECTIONS` and `TABLES` are flattened from the selected
  `TableScheme` detail into `POSRestaurantSection` and `POSTable`.
- `EMPLOYEES` are normalized into `POSEmployee`.
- all eight probed warehouse document surfaces are stored as generic
  `POSInventoryDocument` records. Incoming documents also populate
  `POSPurchaseDocument`; discard documents populate `POSWriteoff`. A sampled
  `InventoryDocument2` detail exposed only summary fields, so no item or
  movement is invented when its line collection is absent.
- stock movements are derived from the confirmed line collections:
  `invoiceItems`, `invoiceComponents`, `sourceItems` and `resultComponents`.
  `actualAmount` is the confirmed quantity field. Exchange documents create a
  transfer-out and transfer-in pair; processing/cooking/transformation inputs
  are negative at the source store and outputs are positive at the target. A
  movement is materialized only when both its warehouse and product already
  have canonical identities; the generic document and item remain available
  when a reference cannot yet be resolved.

Every provider record follows the required path:

```text
Quick Resto response
-> entity-specific allowlist
-> encrypted IntegrationRawObject
-> replay normalizer
-> canonical upsert
```

Identical `source_version + payload_hash` input reuses the Raw row and all
canonical writes are idempotent. `replay_quickresto_expanded_raw` rebuilds an
entity without another provider request.

Employee Raw payloads deliberately exclude the nested `user` object. Generic
Raw storage also rejects token-bearing keys recursively.

## Live read-only verification

On 2026-09-21 the probe was streamed to the production backend for Axelio
venue 21 without copying files to the server. It used only Quick Resto
`GET /api/list` and `GET /api/read`, sent no payload values, and performed zero
database writes.

The live account returned 531 scoped shifts (`CLOSED=530`, `OPENED=1`), 36
employees, five sampled documents on each populated warehouse surface, and
the real table/document field shapes described above. The probe also confirmed
that `ExchangeInvoice` identifies `fromStore` and `store`, while
`ProcessingInvoice` separates `sourceItems` and `resultComponents`.

The reusable structural probe is:

```bash
cd backend
.venv/bin/python -m app.scripts.quickresto_stage3_readonly_probe \
  --venue-id 21 --compact
```

This verification proves read compatibility only. Canonical writes still need
a bounded canary after this code is deployed.

## Explicitly blocked capabilities

Stage 3 does not infer capabilities absent from the live evidence:

- `OPEN_ORDERS` and `CURRENT_ORDER_TOTAL` remain blocked because sampled
  `OrderInfo` rows had no verifiable open/closed state;
- `MODIFIERS` remain degraded because the documented modifier class returned
  `ModifierGroup` rows;
- product variants, stop lists and stock balances remain unknown.

These states do not silently return empty success. Operational adapter calls
for open orders raise `ProviderCapabilityError`.

## Financial isolation

The current open shift is stored with zero financial amounts and an encrypted,
compacted `POSOperationalSnapshot`. The Stage 3 sync creates no order, payment,
report value, payroll or finance projection, does not change `read_mode`, and
does not enable canonical reads.

## Isolated execution

The worker entry point is separate from the existing historical worker:

```bash
cd backend
.venv/bin/python -m app.scripts.sync_quickresto_expanded \
  --connection-id 1 \
  --period-start 2026-09-01 \
  --period-end-exclusive 2026-09-22
```

It requires an active Quick Resto connection with confirmed scope. Automatic
10–30 second realtime scheduling belongs to Stage 5; Stage 3 does not add API
load to the existing scheduled historical import.
