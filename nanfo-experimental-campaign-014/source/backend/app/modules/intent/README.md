# Manual Lab Execution (ADR-010)

No new endpoints. Existing `POST /api/v1/intents/execute` accepts strict boolean
`manual_approval` and `cancel`, both defaulting to false. Execution acceptance is
HTTP 202, domain status `execution_started`, with durable metadata under
`execution_provenance`. Inspect domain status even for HTTP-success responses.

## Enable and Run

Run from `backend`, with existing database/Redis configuration supplied by the
operator. Backend API and worker run unprivileged. Do not mount a Docker socket.

```bash
PYTHONPATH=..:. poetry run alembic -c alembic/alembic.ini upgrade head
PYTHONPATH=..:. poetry run python scripts/run_execution_worker.py
```

Migrate the intended deployment database only after review. Tests below instead
upgrade random disposable schemas and never upgrade the shared application scope.
Migration 0011 owns only `intent_executions` and `intent_outbox`; 0012 belongs to
the independent audit workstream.

Required control configuration:

| Setting | Default / Requirement |
| --- | --- |
| `EXECUTION_MODE` | `demo`; new lab dispatch requires `emulation` |
| `EMULATION_CONTROL_ENABLED` | `false`; separate explicit opt-in |
| `EMULATION_BINDING_PATH` | Absolute trusted operator binding file |
| `EMULATION_SNAPSHOT_PATH` | Absolute fresh lab observation file |
| `EMULATION_COMMANDS_PATH` | Absolute pre-created worker-writable/lab-readable directory |
| `EMULATION_RESULTS_PATH` | Absolute pre-created lab-writable/worker-readable directory |
| `EMULATION_EXECUTION_TIMEOUT_SECONDS` | 120; allowed 10..300 |
| `EMULATION_EXECUTION_LEASE_SECONDS` | 15; allowed 5..60 |
| `EMULATION_EXECUTION_POLL_SECONDS` | 1; positive, at most 2 |
| `EMULATION_CONTROL_MAX_BYTES` | 1048576; results bound; normalized commands fit lab's 8192-byte bound |

The mailbox directories must be separate from each other, telemetry output, and
the trusted binding directory. Symlink path components are refused. The worker
does not provision directory ownership or permissions. The lab needs the same
canonical binding digest through its operator configuration, not a session token.

`PYTHONPATH=..:.` makes the checked-in, pure-data `emulation.topology.manifest()`
available. No protocol driver is imported by backend execution. The requesting
actor and binding actor both need current `write:config` and `execute:rollback`
capabilities plus writable workspace membership. Inventory references are checked
through Network services. Jobs persist actor/time/plan approval, not JWTs or session
credentials; logout does not revoke durable approval, but actor disablement or
capability/membership revocation blocks first dispatch.

## Plans and Evidence

ADR-017 adds optional `simulation_id` to execute, without changing the lab command
schema or making model evidence mandatory for existing manual operations. Unreleased
migration0014 adds immutable `intent_executions.simulation_evidence`: exact scoped
reference, plan/current-network/input/checkpoint/output digests and original expiry.
The Simulation owning service validates it at acceptance and again from the worker's
fresh `prepare_plan` snapshot before first publication; every evidence field must
equal the persisted approval. Changing/dropping references on replay conflicts.
Dispatch authority and delayed filesystem callbacks cannot outlive evidence expiry.
Cancellation ignores expired evidence and keeps its existing independent permissions.

`execution_provenance.approved_plan` deep-copies only the hash-matching persisted
command plan, never editable intent input; corrupted/missing plans project as null.
Invalid commands fail before dispatch or remain uncertain after possible dispatch.
Configured model admission does not prove graph/action correspondence, packet
traversal, physical safety or autonomy authorization. Full fields/hash rules and
non-actuating disposable verification: `../simulation/README.md`.

Validate with the existing endpoint and a bound `network_id`:

```json
{
  "action": "reroute_path",
  "scope": {"source_host": "h1", "destination_host": "h3"},
  "constraints": {
    "operation": "reroute",
    "paths": [["access1", "dist1", "access2"]]
  }
}
```

`reroute_path` defaults to `reroute`; `throttle_qos` defaults to `shape`.
Routing supports one complete simple path or two internally disjoint paths for
`multipath`. Omitted weights normalize to ones. `shape`, `police`, and `restore`
use empty paths/weights, as required by the lab mailbox. QoS rates are 1..20 Mbps
and additionally bounded by the trusted observed fabric capacities. DSCP is an
optional strict integer 0..63; unknown fields/actions are rejected. Lab discovery
must reject unavailable SELECT/meter/queue features before mutation. Validation
does not claim discovered controller capabilities or simulation/model evidence.

Commands and results use exactly ADR-010 v1 fields, UUID filenames, canonical
SHA256 of sorted compact seven-field plan JSON (including nulls), and the original
run/binding/plan/deadline/fence identities. Recovery never increments a wire fence
or blindly republishes execute; database lease fences are independent CAS tokens.
Cancel changes only the command `operation`, retaining every approved identity.

Required command metadata `dispatch_expires_at` (UTC) is set once by the initial
dispatch CAS and committed before publication, not at acceptance. It is bounded by
remaining local authority, the DB lease, the action deadline, and five seconds.
It never extends on renewal/recovery/cancel and is excluded from the plan hash.
The lab MUST enforce `now < dispatch_expires_at <= now + 5 seconds` before preparing
a new journal action, after blocking discovery/readback. Once durably prepared,
continuation follows the original action deadline; compensation and cancellation
remain allowed after dispatch expiry. Result fields are unchanged. Pending DB plan
metadata has no dispatch expiry and cannot be sent as a command.

This is a coordinated receiver change: do not enable control or run the live
verifier with an old lab image. Backend checks and flock do not close a process
pause after the final check before rename; expired receiver-side authorization
does. Backend unit tests exercise that exact pause against the reference contract;
actual lab enforcement requires the separate lab implementation and verification.

`execution_provenance` contains `execution_id`, `phase`, `plan_hash`,
`binding_digest`, `run_id`, `deadline`, approval actor/time, `verification`,
`rollback`, `failure_reason`, `uncertain`, `blocks_lab`, and `cancel_requested`.
Cancellation actor/time (`cancelled_by_user_id`, `cancellation_requested_at`) are
separate from immutable approval actor/time. Job `org_id` is resolved through the
owning Workspace service and carried in all execution outbox audit payloads.
Phases include `accepted`, `dispatching`, `cancelling`, `completed`, `failed`,
`cancelled`, and `uncertain`. Unresolved state remains `execution_started` and
excludes new lab execution even after leases expire. Verified cancellation maps
to the existing `execution_failed` lifecycle event/status, not a new event name.

Completion requires matching result identity/time, `readback_verified=true`, a
readback SHA256, successful probe counts for the approved host pair, and the exact
verification flags `config_readback_and_reachability=true` and
`traffic_effects_verified=false`. Rollback
requires `verified=true` and its readback SHA256. Worker records actual result
objects unchanged apart from canonical timestamp serialization. Confidence stays
zero/unavailable; historical unverified baseline success remains suppressed.
`completion_scope=configuration_readback_and_reachability` explicitly does not
certify operation-specific throughput, QoS effectiveness or SELECT distribution.
`traffic_verification.status=not_performed` for this bounded command contract;
the opt-in live verifier runs separate classified/unclassified workloads.

## Durability and Limits

Acceptance commits intent state, unique job, and immutable full event envelope
together. Terminal transitions commit state and outbox together. Workspace request
hash uniqueness and one-job-per-intent exclude duplicates; a partial unique lab
index excludes unresolved successors. Outbox retry preserves event ID, timestamp,
and payload bytes; XADD/DB-ack failures are at-least-once, not exactly-once.
Per-execution sequence numbers prevent later events overtaking any unpublished
predecessor, including a predecessor leased by another publisher.

Worker claims use PostgreSQL row locking/leases/CAS, plus renewable token-checked
Redis lab locks. No DB transaction spans a wait for lab results. Separate outbox
polling continues while execution waits. Mode/control disablement prevents new
dispatch but does not disable reconciliation or compensation of accepted work.
Renewal calls have bounded timeouts and a local monotonic expiry watchdog. Each
mailbox check/replace holds an execution-specific `flock` on a no-follow lockfile;
lockfiles are never unlinked while active. Delayed filesystem threads recheck local
authority, and no execute publication can replace an existing cancellation.

Silence, malformed/mismatched results, failed rollback, and insufficient evidence
do not release lab exclusion. A crash after recording possible dispatch but before
file publication eventually requests cancellation with the same identity rather
than assuming no mutation. A lab `mutated=false` response without independent
readback is conservatively insufficient: operator investigation is required.
Failed/cancelled results can safely release exclusion only with verified rollback
or `no_mutation_verified=true`, `readback_verified=true`, `mutated=false`, a boolean
`deadline_expired`, and a valid actual-state readback SHA256. This no-mutation
result has `rollback=null` and requires no probe. Bare `mutated=false` never
certifies safety. A database-confirmed
cancel before any possible dispatch is independently safe without lab mutation.
There is intentionally no force-unblock API and no automatic database row deletion.
The lab journal additionally enforces owned-policy restore, operation serialization,
hold-down and action-rate bounds. Backend tests do not certify privileged driver
readback, traffic effects, host power loss, or every filesystem/process-kill boundary.

## Tests

```bash
PYTHONPATH=..:. poetry run pytest tests/unit/test_intent_lab.py tests/unit/test_intent_execution_worker.py -q --no-cov
PYTHONPATH=..:. poetry run pytest tests -q --no-cov
```

For real migration/transaction/lease/outbox tests, supply `INTENT_TEST_DSN` (a
SQLAlchemy PostgreSQL DSN with permission to create a disposable schema) and
`INTENT_TEST_REDIS_URL` through the operator environment, not command arguments:

```bash
PYTHONPATH=..:. poetry run pytest tests/integration/test_intent_execution_postgres.py -q --no-cov
```

These tests migrate a random `intent_test_<uuid>` schema through 0011 and remove
only that schema. Redis uses a random `intent-test:<uuid>:` prefix and removes
only those keys. No shared consumer group or unrelated live data is drained.

Full authenticated API -> independent worker -> real lab verification:

```bash
PYTHONPATH=..:. poetry run python scripts/verify_execution.py --live
```

This operator-only verifier requires a free lab lifecycle slot, the built lab
image, PostgreSQL permission to create/drop its disposable database, and Docker
permission to create dedicated Redis/Neo4j/lab containers. It migrates only its new
database through 0012, runs actual workload/readback and crash/compensation checks,
and removes only its resources. A busy lab is never stopped. Sanitized evidence
is written under `/tmp/opencode/execution-verification-*/result.json`.
