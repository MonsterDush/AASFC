# Provider capability matrix

This matrix documents implementation state, not marketing availability. Only a
successful API probe may move a capability to `SUPPORTED`.

| Domain | Capability | Quick Resto | iiko | Stage 1 storage/contract |
|---|---|---:|---:|---:|
| Scope | organizations/venues | unknown | unknown | yes |
| Scope | terminal groups/terminals/stores | unknown | unknown | yes |
| Realtime | current business shift | unknown | unknown | yes |
| Realtime | open orders/current total | unknown | unknown | yes |
| Restaurant | sections/tables | unknown | unknown | yes |
| Menu | products/groups | existing historical path | unknown | yes |
| Menu | variants/options | unknown | unknown | yes |
| Menu | modifiers/rules | unknown | unknown | yes |
| Menu | stop lists | unknown | unknown | yes |
| Orders | historical orders/items/payments | existing historical path | unknown | yes |
| Commands | create/update/close/cancel | unknown | unknown | ledger only |
| Webhooks | realtime events | unknown | unknown | event inbox only |
| Inventory | warehouses/stock/documents | partial historical path | unknown | yes |
| Loyalty | customers/wallets/coupons/programs | unknown | unknown | contract only |

“Unknown” is intentional until a real account probe succeeds. Provider API
documentation or a user-interface feature alone is not enough evidence.
