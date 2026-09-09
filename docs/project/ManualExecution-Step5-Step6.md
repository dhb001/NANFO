# Steps 5-6: Manual Lab Actions and Execution Recovery

## Delivered Scope

User-authorized ADR-010 implementation, limited to the disconnected campus lab.
Production and demo remain non-actuating. The independent unprivileged execution
worker uses an operator-provisioned file mailbox, never Docker or host switch CLI.
Lab code owns the actual OpenFlow/HTB/meter implementation and durable journal.

- Full forward/return reroute and supported internally disjoint SELECT paths.
- DSCP-aware shaping and policing with bounded 1..20 Mbps rates, plus restoration.
- Explicit manual approval, current request/binding actor checks, fresh topology,
  immutable plan/run/binding identities and five-second dispatch admission window.
- Actual configuration readback, reachability, compensation and verified no-mutation
  outcomes. Ambiguous state blocks later changes rather than inventing rollback.
- PostgreSQL unique jobs, CAS leases, Redis lab locks, serialized monotonic mailbox
  cancellation and retained original command identity on recovery.
- Immutable transactional intent outbox with per-execution publication ordering.
- Redis pending reclaim, post-success handler markers, poison-message DLQ-before-ACK,
  durable audit event uniqueness and versioned topology tombstones against stale replay.
- Mandatory single active API realtime process lease. The execution worker is separate.
- Guided UI actions, approval, bounded polling, same-key retries, cancellation of
  active/completed policies, actual evidence and explicit uncertainty display.

## Live Evidence

Final real API -> worker -> lab run:
`/tmp/opencode/execution-verification-zzs78rob/result.json`.
Command from `backend/`:

```bash
PYTHONPATH=..:. poetry run python scripts/verify_execution.py --live
```

The verifier used real authenticated HTTP, an independent worker process, the
actual controller/switches and isolated PostgreSQL/Redis/Neo4j. Disposable database
migrations through 0012 passed. Owned resources were removed; unrelated/shared
services and data were not changed.

| Check | Measured result |
| --- | --- |
| Baseline TCP | 18.805 Mbps |
| Reroute TCP | 18.689 Mbps; forward/return path counters verified |
| SELECT multipath | 37.798 Mbps; both buckets carried traffic |
| 5 Mbps shaping | 4.758 Mbps classified; 17.713 Mbps unclassified |
| Restore after shaping | 17.712 Mbps |
| 5 Mbps policing | 4.870 Mbps classified; 17.713 Mbps unclassified |
| Restore after policing | 17.708 Mbps |
| Four concurrent submissions | One durable execution |
| Worker death/lost result | Same command identity and journal action count |
| Old A cancelled after restore B and newer C | Verified no-mutation; C preserved |
| Late cancellation/deadline | Verified compensation |
| Terminal event replay | Two identical envelopes, one durable audit row |

Separate lab tests verified injected partial failures, old-run recovery followed
by polling, command/lock-file bounds, cancelled stale dispatch, controller/executor
restart and uncertainty blocking. Evidence is in `emulation/README.md` and
`emulation/output/actions-verification.json`.

## Final Automated Gates

- Backend: 1,359 passed, 8 opt-in infrastructure tests skipped in the default run.
  All eight were separately executed: execution PostgreSQL/Redis 4 passed,
  event/lease/audit recovery 2 passed, telemetry SQL 1 passed, topology Neo4j 1 passed.
- Backend Ruff over app/tests/scripts passed; diff whitespace check passed.
- Frontend: strict typecheck/lint passed; 241 tests passed across 44 files.
- Production build and unchanged bundle thresholds passed: 407.03 KiB total JS gzip.
- Browser: final standalone run 27/27 passed with retries disabled. An earlier run
  concurrent with build/regression had one existing spatial-reference test timeout
  at login navigation (26 passed); no claim that this transient did not occur.
- Lab image: 41 tests passed; host: 37 passed, 4 image-only skips.

## Deployment

Review and apply migrations 0011/0012 to the intended application database before
starting the new code. Live verification migrated only disposable databases; it
did not upgrade the shared deployment. From `backend/`:

```bash
poetry run alembic -c alembic/alembic.ini upgrade head
PYTHONPATH=..:. poetry run python scripts/run_execution_worker.py
```

Configure `EXECUTION_MODE=emulation`, `EMULATION_CONTROL_ENABLED=true`, absolute
binding/snapshot/commands/results paths and the lab's matching binding digest.
Run one API worker. Commands/results must remain separate from trusted bindings;
only the authorized worker may write commands. See `emulation/README.md` and
`backend/app/modules/intent/README.md` for exact setup and recovery requirements.
Neo4j must allow the idempotent projection revision uniqueness constraint or have
it provisioned in advance. No new REST route or websocket channel was added.

## Explicit Limits

One active lab policy at a time, bounded journal capacity, supported campus paths,
and 1..20 Mbps QoS. Ordinary completion means configuration readback and reachability
(`traffic_effects_verified=false`); the rates above come from separate workloads.
Dispatch admission is journal preparation, not an atomic wall-clock guarantee
across arbitrary process pauses/fsync. Full host power-loss and every filesystem
crash point were not certified. Redis persistence configuration still matters.

Delivery remains at-least-once. The transactional outbox covers intent execution,
not every historical producer; reporting/simulation notification crash gaps and
telemetry source-sample durability are not retroactively solved. Failed or ambiguous
compensation requires operator reconciliation; there is no unsafe force-unblock
endpoint. This work does not provide DRL, a simulation evaluator or production control.
