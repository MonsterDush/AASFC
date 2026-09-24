# Quick Resto capability matrix

This matrix records evidence, not marketing availability. API documentation
identifies a candidate source; only a successful live read-only probe may move
the live status to `SUPPORTED` or `DERIVED`.

| Canonical capability | Quick Resto API 2.92 | Live probe status | Canonical model | Stage |
|---|---|---|---|---|
| `CURRENT_BUSINESS_SHIFT` | `front.zreport.Shift` | `DERIVED` — venue 21 returned `CLOSED=530`, `OPENED=1`; the real cloud ignored the server filter, so `OPEN`/`OPENED` are filtered locally | `POSBusinessShift`, `POSOperationalSnapshot` | implemented in 3 with local filtering |
| `OPEN_ORDERS` | `front.orders.OrderInfo` | `UNKNOWN` — the real response has order/table/waiter/amount fields but no explicit open/closed state; `status=OPEN` was not verifiable | `POSOrder`, `POSOperationalSnapshot` | requires another source or correlation proof |
| `CURRENT_ORDER_TOTAL` | `frontTotalPrice` and related amount fields in `OrderInfo` | `UNKNOWN` — amount exists, but no sampled row was proven to be an open order | `POSOrder.current_amount` | blocked by `OPEN_ORDERS` evidence |
| `TABLES` | `front.tablemanagement.TableScheme.tables` | `SUPPORTED` — live detail exposed `title`, `maxCapacity`, `deleted`, shape and coordinates | `POSTable` | implemented in 3 |
| `RESTAURANT_SECTIONS` | `front.tablemanagement.TableScheme.webHalls` | `SUPPORTED` — list/read exposed halls with nested tables | `POSRestaurantSection` | implemented in 3 |
| `MODIFIERS` | `warehouse.nomenclature.mods.Modifier` and `ModifierGroup` | `DEGRADED` — on the real cloud both class requests returned `ModifierGroup`; independent modifier rows were not proven | `POSModifier`, `POSModifierGroup`, `POSProductModifierRule` | requires alternate source/class evidence |
| `PRODUCT_VARIANTS` | candidate configuration/option structure in `warehouse.nomenclature.dish.Dish` detail | `UNKNOWN` — sampled list/read had sales and price structure but no configuration/variant/option structure | `POSProductVariant`, `POSProductOption`, `POSProductVariantOption` | requires another source or representative data |
| `EMPLOYEES` | `personnel.employee.Employee` | `SUPPORTED` — 36 live rows exposed stable identity and blocked state; nested `user` is intentionally excluded from Raw storage | `POSEmployee` | implemented in 3 |
| `STOP_LISTS` | no dedicated read endpoint documented in API 2.92 | `UNKNOWN`; the product UI is not API evidence | `POSStopListEntry` | requires provider evidence before 3 |
| `INVENTORY` | `warehouse.inventory.document.v2.InventoryDocument2` | `SUPPORTED` for document summary — sampled detail exposed store/date/status/totals but no line collection, so items and corrections are not inferred | `POSInventoryDocument`, optional `POSInventoryItem` | implemented in 3 without fabricated lines |
| `PURCHASES` | `warehouse.documents.incoming.IncomingInvoice` | `SUPPORTED` — live `invoiceItems` expose product, `actualAmount`, unit and costs | `POSPurchaseDocument`, `POSPurchaseItem` | implemented in 3 |
| `WRITEOFFS` | `warehouse.documents.discard.DiscardInvoice` | `SUPPORTED` — live `invoiceItems` expose product, `actualAmount`, unit and costs; reason is available on the document | `POSWriteoff`, `POSWriteoffItem` | implemented in 3 |
| `STOCK_MOVEMENTS` | inventory, incoming, outgoing, discard, exchange, cooking, decomposition and processing documents | `DERIVED` — live exchange rows expose source/target stores; processing rows expose source/result collections; cooking line collections were structurally present but empty in the sample | `POSStockMovement` | implemented in 3 from resolved document lines; empty/unproven lines create no movement |
| `STOCK_BALANCES` | no dedicated stock-balance list endpoint documented in API 2.92 | `UNKNOWN` | `POSStockSnapshot` | requires provider evidence before 3 |

The existing historical Quick Resto paths for closed shifts, orders, payment
types, products, venues, sale places and stores remain intact. Stage 3 neither
changes report/finance/payroll reads nor enables canonical read flags.
