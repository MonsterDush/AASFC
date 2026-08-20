# Production rollback drill — 2026-08-20

## Scope and safety

The protected GitHub Actions `Rollback` workflow was used against production.
The target was the immediate parent of the active `main` release, so the drill
changed application code only and did not downgrade the database. Production
Environment approval was required. A roll-forward to the original current SHA
was prepared and executed immediately after the rollback observation.

- original and recovered release: `b88960459144103da43c73f82b513f5f83c22ae5`
- rollback target: `a60b19ec951d83a3014682445af9b80a1281234e`
- rollback run: <https://github.com/MonsterDush/AASFC/actions/runs/32379273355>
- recovery run: <https://github.com/MonsterDush/AASFC/actions/runs/32379473585>

## Measured result

The rollback activation step started at 14:18:52 UTC and public smoke reported
the prior release ready at 14:19:03 UTC. The observed application rollback RTO
was therefore approximately 11 seconds, excluding the human Environment
approval wait.

The workflow subsequently failed while writing release metadata. The checked-out
older Alembic tree could not resolve the newer database revision
`c8e1f4a7b2d9`, even though the application rollback and smoke had succeeded.
This was a metadata-path defect, not a failed application rollback. It also
confirmed why rollback must never automatically downgrade the database.

The protected roll-forward job ran from 14:33:15 to 14:34:48 UTC, or 93 seconds
of machine execution excluding approval. Final production readiness returned
database `ok` and the original release SHA
`b88960459144103da43c73f82b513f5f83c22ae5`.

## Corrective action

`ops/deploy/release.sh` now treats the database revision table as a compatible
fallback when the checked-out Alembic graph cannot resolve a newer revision.
Release metadata also records `duration_seconds`, and deploy/rollback logs print
elapsed time. This preserves audit metadata after a backward-compatible
application-only rollback instead of turning a successful recovery red.

Regression contracts require the fallback, elapsed duration, protected
production workflow, and public smoke. After this corrective release first
reaches production, the next quarterly rollback drill should confirm that the
entire workflow, including metadata, finishes green.

## Outcome

Application rollback and roll-forward were both practically exercised, timed,
and recovered without database downgrade or Git history rewrite. The discovered
post-smoke defect has a code fix and documented follow-up. No production data
restore was needed.

