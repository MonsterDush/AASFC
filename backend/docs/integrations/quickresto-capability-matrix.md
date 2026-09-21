# Quick Resto capability matrix

This matrix records evidence, not marketing availability. API documentation
identifies a candidate source; only a successful live read-only probe may move
the live status to `SUPPORTED` or `DERIVED`.

| Canonical capability | Quick Resto API 2.92 | Live probe status | Canonical model | Stage |
|---|---|---|---|---|
| `CURRENT_BUSINESS_SHIFT` | `front.zreport.Shift`, list filtered by `status=OPEN` | `DEGRADED` — 2026-09-21 probes ended before an HTTP response (TLS timeout, then connection failure) | `POSBusinessShift`, `POSOperationalSnapshot` | 2 discovery; normalization in 3 |
| `OPEN_ORDERS` | `front.orders.OrderInfo`, list filtered by `status=OPEN` | `DEGRADED` — live payload structure unverified | `POSOrder`, `POSOperationalSnapshot` | 2 discovery; normalization in 3 |
| `CURRENT_ORDER_TOTAL` | candidate amount/total field in an open `OrderInfo` | `UNKNOWN` until an open-order amount field is observed | `POSOrder.current_amount` | 2 discovery; normalization in 3 |
| `TABLES` | `front.tablemanagement.TableScheme` detail | `DEGRADED` — live collection structure not yet received | `POSTable` | 2 discovery; normalization in 3 |
| `RESTAURANT_SECTIONS` | `front.tablemanagement.TableScheme` detail | `DEGRADED` — live collection structure not yet received | `POSRestaurantSection` | 2 discovery; normalization in 3 |
| `MODIFIERS` | `warehouse.nomenclature.mods.Modifier` and `ModifierGroup` | `DEGRADED` — documented endpoints, no live payload | `POSModifier`, `POSModifierGroup`, `POSProductModifierRule` | 2 discovery; normalization in 3 |
| `PRODUCT_VARIANTS` | candidate configuration/option structure in `warehouse.nomenclature.dish.Dish` detail | `UNKNOWN` until sampled structure is observed | `POSProductVariant`, `POSProductOption`, `POSProductVariantOption` | 2 discovery; normalization in 3 |
| `EMPLOYEES` | `personnel.employee.Employee` | `DEGRADED` — documented endpoint, no live payload | `POSEmployee` | 2 discovery; normalization in 3 |
| `STOP_LISTS` | no dedicated read endpoint documented in API 2.92 | `UNKNOWN`; the product UI is not API evidence | `POSStopListEntry` | requires provider evidence before 3 |
| `INVENTORY` | `warehouse.inventory.document.v2.InventoryDocument2` | `DEGRADED` — documented endpoint, no live payload | `POSInventoryDocument`, `POSInventoryItem` | 2 discovery; normalization in 3 |
| `PURCHASES` | `warehouse.documents.incoming.IncomingInvoice` | `DEGRADED` — documented endpoint, no live payload | `POSPurchaseDocument`, `POSPurchaseItem` | 2 discovery; normalization in 3 |
| `WRITEOFFS` | `warehouse.documents.discard.DiscardInvoice` | `DEGRADED` — documented endpoint, no live payload | `POSWriteoff`, `POSWriteoffItem` | 2 discovery; normalization in 3 |
| `STOCK_MOVEMENTS` | inventory, incoming, outgoing, discard, exchange, cooking, decomposition and processing documents | `DEGRADED`; becomes `DERIVED` after at least one successful document probe | `POSStockMovement` | 2 discovery; derivation in 3 |
| `STOCK_BALANCES` | no dedicated stock-balance list endpoint documented in API 2.92 | `UNKNOWN` | `POSStockSnapshot` | requires provider evidence before 3 |

The existing historical Quick Resto paths for closed shifts, orders, payment
types, products, venues, sale places and stores remain intact. Stage 2 neither
changes report/finance/payroll reads nor enables canonical read flags.
