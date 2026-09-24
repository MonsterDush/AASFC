# Provider capability matrix

This matrix documents implementation state, not marketing availability. Only a
successful API probe may move a capability to `SUPPORTED`.

| Domain | Capability | Quick Resto | iiko | Stage 1 storage/contract |
|---|---|---:|---:|---:|
| Scope | organizations/venues | unknown | `BLOCKED` — reader and Raw/ACDM replay implemented; live account probe pending | yes |
| Scope | terminal groups/terminals/stores | unknown | `BLOCKED` — terminal-group/alive Raw/ACDM implemented; individual terminals and stores remain unimplemented | yes |
| Realtime | current business shift | unknown | unknown | yes |
| Realtime | open orders/current total | unknown | unknown | yes |
| Restaurant | sections/tables | unknown | `BLOCKED` — reserve reader and Raw/ACDM replay implemented; live scope probe pending | yes |
| Menu | products/groups | existing historical path | `BLOCKED` — revision-aware reader and Raw/ACDM replay implemented | yes |
| Menu | variants/options | unknown | `BLOCKED` — iiko sizes normalize and replay as provider-neutral variants | yes |
| Menu | modifiers/rules | unknown | `BLOCKED` — simple/grouped modifier Raw/ACDM replay implemented | yes |
| Menu | stop lists | unknown | `BLOCKED` — product/size stop-list Raw/ACDM replay implemented | yes |
| Orders | historical orders/items/payments | existing historical path | unknown | yes |
| Commands | create/update/close/cancel | unknown | unknown | ledger only |
| Webhooks | realtime events | unknown | unknown | event inbox only |
| Inventory | warehouses/stock/documents | partial historical path | not implemented; planned for Stage 9 | yes |
| Loyalty | customers/wallets/coupons/programs | unknown | unknown | contract only |

“Unknown” is intentional until a real account probe succeeds. Provider API
documentation or a user-interface feature alone is not enough evidence.

The complete official iikoCloud operation inventory is maintained in
`backend/docs/integrations/iiko-api-matrix.md`.
