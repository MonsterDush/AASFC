# POS Integration Layer v0.4 — Stage 4

Stage 4 adds the first iikoCloud provider implementation without changing
historical Quick Resto imports, financial reads, payroll or canonical read
flags.

## Implemented read-only foundation

- iikoCloud v1 `apiLogin` and v2 `apiKey + appId + clientSecret` bearer
  authorization with a 55-minute local refresh boundary;
- credentials and bearer tokens are never included in provider diagnostics;
- organizations and multi-organization scope discovery;
- terminal groups, sleeping groups and `is_alive` state;
- revision-aware `/api/1/nomenclature` reader;
- product groups, product categories and products;
- iiko sizes exposed as provider-neutral product variants;
- simple modifiers, grouped modifiers and product modifier rules;
- payment, order, discount, cancellation, removal, tips and marketing
  dictionaries kept separate from order facts;
- product/size stop-list entries scoped by terminal group;
- restaurant sections and nested tables through the reserve read endpoint;
- encrypted Raw-first persistence for the selected organization and terminal
  groups before any ACDM write;
- deterministic, idempotent normalization into organization, venue, terminal
  group, catalog, variant, modifier, payment type, section, table and stop-list
  ACDM entities;
- offline replay of every implemented Stage 4 entity from the stored Raw object
  without another iikoCloud call.

The focused bundle registers discovery, read and operational adapters under
provider code `IIKO`. Current shifts and open orders intentionally remain
blocked for Stage 5; historical orders remain blocked for Stage 6; write
operations remain blocked for Stage 7.

## Evidence boundary

Contract fixtures validate official response shapes, but the repository does
not contain a complete encrypted iiko credential set or an approved demo
scope. Therefore Stage 4 capabilities remain `BLOCKED` in the documentation
until the same calls succeed against the selected live organization. The
adapter changes a capability to `SUPPORTED` only in the result of an actual
successful call.

The Raw-first contract is covered independently of the external stand: a
repeat import does not duplicate Raw or ACDM rows, canonical relationships are
preserved, credentials are excluded from Raw, and a deleted canonical payment
type can be reconstructed from its encrypted Raw object. The synchronization
does not change `IntegrationConnection.read_mode`; legacy financial and payroll
reads remain untouched.

The official schema snapshot inspected on 2026-09-21 contains 328 operations
across 327 paths. Every operation is classified in
`backend/docs/integrations/iiko-api-matrix.md`; the matrix can be regenerated
with `backend/tools/generate_iiko_api_matrix.py`.

## Remaining Stage 4 acceptance gate

Run the bounded read-only probe after iiko issues the demo/API access required
for authorization. The probe must use the explicitly selected organization and
terminal groups, store only allowlisted encrypted Raw payloads, verify the ACDM
row counts and relationships, and leave `read_mode=LEGACY`. No capability
should be enabled merely from an OpenAPI description or fixture.
