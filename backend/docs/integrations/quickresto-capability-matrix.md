# Quick Resto capability matrix

This matrix records evidence, not marketing availability. API documentation
identifies a candidate source; only a successful live read-only probe may move
the live status to `SUPPORTED` or `DERIVED`.

| Canonical capability | Quick Resto API 2.92 | Live probe status | Canonical model | Stage |
|---|---|---|---|---|
| `CURRENT_BUSINESS_SHIFT` | `front.zreport.Shift` | `DERIVED` — the real cloud ignored `status=OPEN`, but rows expose exact `status`/`opened` fields for local filtering | `POSBusinessShift`, `POSOperationalSnapshot` | local-filter normalization in 3 |
| `OPEN_ORDERS` | `front.orders.OrderInfo` | `UNKNOWN` — the real response has order/table/waiter/amount fields but no explicit open/closed state; `status=OPEN` was not verifiable | `POSOrder`, `POSOperationalSnapshot` | requires another source or correlation proof |
| `CURRENT_ORDER_TOTAL` | `frontTotalPrice` and related amount fields in `OrderInfo` | `UNKNOWN` — amount exists, but no sampled row was proven to be an open order | `POSOrder.current_amount` | blocked by `OPEN_ORDERS` evidence |
| `TABLES` | `front.tablemanagement.TableScheme.tables` | `SUPPORTED` — list/read exposed table identity, capacity, shape and coordinates | `POSTable` | normalization in 3 |
| `RESTAURANT_SECTIONS` | `front.tablemanagement.TableScheme.webHalls` | `SUPPORTED` — list/read exposed halls with nested tables | `POSRestaurantSection` | normalization in 3 |
| `MODIFIERS` | `warehouse.nomenclature.mods.Modifier` and `ModifierGroup` | `DEGRADED` — on the real cloud both class requests returned `ModifierGroup`; independent modifier rows were not proven | `POSModifier`, `POSModifierGroup`, `POSProductModifierRule` | requires alternate source/class evidence |
| `PRODUCT_VARIANTS` | candidate configuration/option structure in `warehouse.nomenclature.dish.Dish` detail | `UNKNOWN` — sampled list/read had sales and price structure but no configuration/variant/option structure | `POSProductVariant`, `POSProductOption`, `POSProductVariantOption` | requires another source or representative data |
| `EMPLOYEES` | `personnel.employee.Employee` | `SUPPORTED` — real list response exposed stable identity and active/blocked structure | `POSEmployee` | normalization in 3 |
| `STOP_LISTS` | no dedicated read endpoint documented in API 2.92 | `UNKNOWN`; the product UI is not API evidence | `POSStopListEntry` | requires provider evidence before 3 |
| `INVENTORY` | `warehouse.inventory.document.v2.InventoryDocument2` | `SUPPORTED` — real rows exposed store, date, processed state and totals | `POSInventoryDocument`, `POSInventoryItem` | normalization in 3 |
| `PURCHASES` | `warehouse.documents.incoming.IncomingInvoice` | `SUPPORTED` — real rows exposed provider, store, date, paid/processed state and totals | `POSPurchaseDocument`, `POSPurchaseItem` | normalization in 3 |
| `WRITEOFFS` | `warehouse.documents.discard.DiscardInvoice` | `SUPPORTED` — real rows exposed store, reason, date, processed state and totals | `POSWriteoff`, `POSWriteoffItem` | normalization in 3 |
| `STOCK_MOVEMENTS` | inventory, incoming, outgoing, discard, exchange, cooking, decomposition and processing documents | `DERIVED` — multiple document surfaces returned live structural evidence | `POSStockMovement` | derivation in 3 |
| `STOCK_BALANCES` | no dedicated stock-balance list endpoint documented in API 2.92 | `UNKNOWN` | `POSStockSnapshot` | requires provider evidence before 3 |

The existing historical Quick Resto paths for closed shifts, orders, payment
types, products, venues, sale places and stores remain intact. Stage 2 neither
changes report/finance/payroll reads nor enables canonical read flags.
