# Governed Autonomy

## ADR-018 Configuration And Timed Overrides

### Physical Override Verification

Run `PYTHONPATH=.:.. /absolute/backend/venv/bin/python scripts/verify_operator_override.py --live`
from `backend`, using the backend interpreter explicitly rather than an active AI
environment. This explicitly actuates only a new isolated Mininet/OVS campus.
Requires Docker, pinned `nanfo-emulation:operator-paths-adr018` image
`sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c`, Bubblewrap
user namespaces, and no other running lab. It never rebuilds the image or resets
shared infrastructure. PostgreSQL/Redis/Neo4j/lab containers and all processes are
UUID-owned; migrations run through0016 only in the disposable PostgreSQL instance.

API/Autonomy/Intent processes run in read-only mount sandboxes with private `/run`
and `/tmp`, no Docker socket and no journal/output write authority. Only Intent's
command mailbox is writable. The existing journal is read directly, not copied or
rewritten to fabricate enrollment; opening it for write and creating a results-file
are tested to fail. Docker commands occur only in the operator verifier.

Latest updated-image evidence (2026-09-10):
`/tmp/opencode/operator-override-verification-1j3zdsiz/result.json`.
The six-case run took274.307833s, retained4 capture directories (maximum8), and
removed all4 owned containers/volumes and5 API/worker processes. Both incumbent
aliases remain `31c749ef7962`; no image rebuild, source/model/AI/frontend change,
shared database or root-service modification.

| Updated-Image Case | Trigger To Backend Verified | Additional Actual Evidence |
| --- | --- | --- |
| 60s expiry plus Autonomy worker restart | 6.446863s | Held flows not reinstalled |
| STOP during pending restoration | 6.060760s | Explicit override return cannot clear STOP |
| Expiry during capture | 6.407527s | Expiry21:31:10.827179Z, lab receipt21:31:11.476625Z (+0.649446s); capture partial |
| STOP during capture | 6.201908s | STOP21:31:33.279048Z, lab receipt21:31:33.765191Z (+0.486143s); capture partial |
| Lab restart while holding | 6.419123s after expiry | Original completed receipt retained; fresh obsolete-cancel/current-run no-mutation proof |
| Actor revocation | 8.233985s | New execution403, recovery without actor impersonation |

Every case independently read all five switches:10 owned flows before,0 after,
active=null, ping3/3. Capture interruptions were observed from real tcpdump/probe
children and runner responses; neither publishes new successful evidence or leaves
children behind. Baseline/final captures each succeed; final has24 sightings.
STOP overlap is scheduled by reading the persisted next check after the completed
Intent lease elapses, never by altering a lease/status/receipt. The prior attempt
`operator-override-verification-tiahh09s` correctly failed when capture finished
before STOP cancellation arrived; it is retained, not relabeled success.

Actual lab restart21:31:49.137817Z ->ready21:31:57.485110Z changed run
`00ea91fd-b107-40dd-8763-efbe566006ec` to
`863a8397-10fc-44ff-a6da-a17bb9ce9baa`. Backend remained holding/completed until
expiry, then received cancelled21:32:48.310942Z with `recovered_obsolete=true`,
`current_run_id`, `no_mutation_verified=true`, `mutated=false` and fresh readback
hash. Original execution/run/hash identity stayed fixed. No indefinite restoring.
Six jobs/six verified cancellations, zero remaining exclusion or model inference.
Actual interval gaps3.073796s/3.031337s; training remains not_requested.
Final aggregate backend1,858 passed/50 opt-in skips. Ruff0.15.6 passed ONLY the
edited verifier/test scope; this is not a claim that baseline repository lint passes.

Earlier incumbent-image physical evidence (2026-09-10):
`/tmp/opencode/operator-override-verification-qtqweffq/result.json`.
Image: `sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9`.

| Scenario | Actual Timing | Physical Result |
| --- | --- | --- |
| 60s expiry, Autonomy SIGKILL/restart midhold | enrolled20:49:24.908595Z; killed20:49:30.329306Z; restarted20:49:37.722778Z; verified20:50:31.216137Z (expiry+6.307542s) | 10 owned flows ->0, active=null, monitor returned |
| STOP during pending expiry restoration | expired20:50:49.250930Z; STOP20:50:49.479662Z; verified20:50:55.632424Z (STOP+6.152762s) | 10 ->0, return_blocked; explicit return preserves STOP |
| Actor membership revoked after enrollment | revoked20:51:06.527945Z; verified20:51:14.654392Z (+8.126447s, before60s expiry) | 10 ->0, return_blocked; new execution403; cancellation actor=null |

Independent `ovs-ofctl dump-flows` across all five switches and namespace ping
show3/3 replies before/after every case. Journal/command identity and action count
remain unchanged except `operation=cancel`; flow durations/counters continue across
worker death with no reinstall. Exactly3 approved jobs,3 verified cancellations,
zero remaining exclusions, zero model diagnostics. Config PUT uses only operational
interval3s and empty training; actual worker gaps3.087494s/3.046758s, stale PUT409.
Total149.688682s; all4 owned containers/volumes and5 processes removed/stopped.

An earlier run verified expiry/revocation but failed when the harness attempted to
re-add a soft-deleted member (existing membership API500). The harness now schedules
revocation last and does not alter membership implementation or erase that evidence.
Physical bounded-campus restoration is verified; production autonomy, training and
model diagnostic inference are not claimed by this verifier.
Aggregate backend regression after the physical run and verifier tests:
1,856 passed/50 opt-in skips; scoped Ruff and whitespace checks passed.

Migration `0015` follows `0014` and creates ONLY Autonomy configuration revisions
and timed overrides. The model-diagnostics workstream owns `0016`, with
`down_revision = "0015"`. No model, AI, emulation or frontend files are owned by
this configuration/override implementation. No new event or WebSocket channel.

All six new routes use `success/data/meta/errors`. Reads require current
`read:telemetry`; writes require both `write:config` and `execute:rollback`, plus
current writable organization membership. Global permissions do not bypass a
ReadOnly membership. REST never returns the server recovery capability.

### Configuration Contract

- `GET /api/v1/autonomy/configuration?network_id=UUID` returns `network_id`,
  `workspace_id`, `revision`, `control_revision`, `operational`,
  `requested_training`, `effective_training`, `training_status`,
  `effective_training_status`, `safety_merge`, `history`, `history_limit`.
- `PUT /api/v1/autonomy/configuration` requires `network_id`,
  `expected_revision` (the configuration revision, NOT the control revision),
  nonblank `reason` (1..1000 characters), `operational`, `training`.
- `operational`: strict integer `max_observation_age_seconds` (1..30, default30),
  `decision_interval_seconds` (1..3600, default10), `min_route_hold_seconds`
  (3..3600, default3), `max_changes_per_minute` (1..10, default10).
- `training.reward_weights`: at most32 lowercase identifier keys, finite signed
  numeric values -100..100. An empty map means no requested training settings.
  Requests are retained only; no training job or frozen-model weight is modified.
- `training_status`: `not_requested` or `retraining_required`.
  `effective_training` is null and `effective_training_status` is
  `model_owned_unavailable`; requested weights are never mislabeled effective.
- `history` contains newest100 immutable entries: `revision`, `actor_id`, `reason`,
  `operational`, `training`, `content_sha256`, `created_at`. PostgreSQL rejects
  UPDATE/DELETE. Conflict is409 `CONFIGURATION_REVISION_CONFLICT`.
- Configuration changes increment the independent control revision and invalidate
  in-flight cycle claims without changing mode, STOP, model or approvals. The
  worker actually uses the stored interval and observation age, plus route hold
  and complete trailing-minute dispatch history gates. Calibrated certificates
  remain mandatory: tighter configured gates only add restrictions, never replace
  calibrated policy (`safety_merge=stricter_than_calibrated_policy`).

### Override Contract

- `GET /api/v1/autonomy/overrides?network_id=UUID` returns `network_id`,
  `control_revision`, `overrides` (newest100), `history_limit` (100).
- `POST /api/v1/autonomy/overrides` requires `network_id`, `intent_id`,
  `execution_id`, `expected_revision` (control revision), `reason` (1..1000),
  `duration_seconds` (strict integer1..3600), `return_mode`
  (`monitor|recommend|autonomous`). Returns201 with an OverrideResponse.
- `POST /api/v1/autonomy/overrides/{override_id}/cancel` has no body; it
  idempotently requests restoration and returns200, NOT verified completion.
- `POST /api/v1/autonomy/overrides/{override_id}/return` requires
  `expected_revision` (fresh control revision) and nonblank `reason`.
  It requires prior verified restoration and returns the real return outcome.
- OverrideResponse exact fields: `override_id`, `network_id`, `workspace_id`,
  `intent_id`, `execution_id`, `actor_id`, `reason`, `duration_seconds`,
  `return_mode`, `prior_mode`, `prior_revision`, `hold_revision`,
  `checkpoint_sha256`, `prior_approval_expires_at`, `prior_approved_by_user_id`,
  `command_sha256`, `plan_hash`, `binding_digest`, `run_id`,
  `configuration_verified_at`, `evidence_scope`, `status`, `reasons`,
  `cancellation_id`, `cancellation_requested_at`, `cancelled_by_user_id`,
  `restoration_attempts`, `verification`, `restored_at`, `return_requested_at`,
  `return_requested_by_user_id`, `return_reason`, `returned_at`, `expires_at`,
  `created_at`, `updated_at`. IDs are UUID strings, timestamps timezone-aware ISO;
  optional approvals/cancellation/return/verification fields are null until known.
- Status is `holding|restoring|restored|return_blocked|returned`. `holding` is
  NOT a live forwarding claim: `evidence_scope=historical_configuration_readback`
  and `configuration_verified_at` identify the enrollment evidence. The browser
  may display a countdown but must never infer restoration from elapsed time.

### Recovery Operations

Enrollment adopts an already completed manual Intent execution for the same actor,
network and workspace. Intent validates the exact persisted command, a <=30-second
configuration readback receipt and current operator journal ownership. It rejects
restores, cancelled/uncertain jobs, superseded/restored policies, blocked/obsolete
journals and mismatched hashes. The operator must make the existing bounded
`EMULATION_RESULTS_PATH/.journal.json` readable to the backend through an appropriate
read-only deployment mount/ACL; unavailable private journal access fails409. Do not
make the producer journal writable to the API or weaken filesystem permissions.
No execute command is published or replayed during enrollment. The receipt remains
historical; this does not claim continuous live verification.

One unresolved override per network and one enrollment per execution are enforced
by unique indexes. Enrollment atomically holds monitor mode and invalidates worker
claims. Outstanding holds/restoration block regular mode changes and dispatch.
The independent loop in `scripts/run_autonomy_worker.py` scans every second even
when full Autonomy inference is unavailable/stalled. It checks actor authority at
most every2seconds and uses DB-time CAS leases. Expiry, cancellation, revocation or
STOP triggers server compensation without impersonating any user. Keep the existing
Intent execution worker running: Autonomy requests cancellation; Intent owns durable
publication, Redis actuation locks and exact-command readback.

Intent's public `IntentOverrideService.restore_override(reference)` accepts only
an exact persisted restoring enrollment and its opaque capability, revalidates
Intent-owned identity, and requests cancellation of THAT execution only. It cannot
authorize execution, supply a plan or broaden authority. Intent and Autonomy each
query only their own tables. Retries retain the same execution/cancellation ID;
cancelled-but-unknown results reacquire reconciliation rather than silently unblock.
Only matching terminal cancelled evidence with verified rollback/no-mutation allows
release. Missing transport, concurrent lab ownership or unverified outcomes remain
`restoring` with attempts/diagnostics; operator reconciliation may be required.

After verified restoration, the worker attempts the previously approved return once.
Restart between restoration and return is recoverable. STOP/revision/model/approval
changes block it. An explicit return can use a refreshed revision but NEVER clears
STOP. Autonomous return also needs this actor's original unexpired model approval,
all live readiness providers and a fresh compatible observer; historical inference
is insufficient. Missing deployed providers produce `return_blocked` and monitor,
not fake activation. Refresh before a new explicit return; never auto-retry409 with
a replacement revision. The original `/autonomy` explicit mode-change workflow is
the only existing STOP-clear mechanism after unresolved recovery has finished.

### ADR-018 Verification

`tests/unit/test_autonomy_operator_controls.py` covers bounds, signed finite requested
weights, actual operational gates and read-only current journal enrollment.
`tests/integration/test_autonomy_operator_postgres.py` uses migration0015 and an
isolated UUID schema for immutable config, interval use, capability rejection,
replay exclusion, CAS/restart, expiry, revocation, cancelled-unknown retry,
STOP/return races and live-return blockers. No shared database is migrated/reset.

Live HTTP/independent-worker verifier passed with requested/retraining separation,
revision409, scoped empty overrides, rejected missing execution and zero execution
jobs: `/tmp/opencode/autonomy-verification-6bsvbujm/result.json`.
This verifies backend orchestration, not physical lab rollback or production autonomy.

Final workstream checks: full backend1,845 passed/49 opt-in skips;
disposable migration0015 transaction suite20 passed; scoped Ruff and
`git diff --check` passed. Full suite command:
`PYTHONPATH=.:.. poetry run pytest tests -q --no-cov` from `backend`.

ADR-012 owns this fail-closed Step 9/10 foundation. It is not end-to-end autonomous
control certification. Production dispatch and online learning remain disabled.

## Installed Behavior

- Monitor persists scoped ADR-009 telemetry health, timestamps, provenance and
  unavailable/stale reasons. Only explicitly non-synthetic emulation records are
  exposed. Empty history is reported as unavailable, not invented measurements.
- Recommend is non-actuating. With injected qualified inference and calibrated
  safety it persists a proposal; deployed missing providers persist blockers.
- Autonomous PUT returns 409 without changing mode while any required provider,
  qualification, calibration, or executor authorization is absent.
- Stop commits its latch before public Intent-service cancellation of the exact
  owned intent/execution. Enqueue is not verified cancellation. Unknown outcomes
  retain exclusion; explicit mode change cannot clear unresolved execution.
- Mode PUT requires `expected_revision` from GET. Both captured server revision
  and current locked revision must match; stale requests cannot clear newer STOP.
- Outstanding execution is verified before old-actor authorization. Compensation
  retries require a separately governed server-owned recovery provider. Deployed
  recovery returns `autonomous_recovery_unavailable` and `operator_recovery_required`,
  retaining exclusion instead of impersonating revoked users.
- Current identity permissions and network/workspace membership are checked through
  public Identity/Network services. No Autonomy SQL reads another module's tables.

Installed blockers: `observation_contract_incompatible`,
`qualified_checkpoint_unavailable`, `frozen_inference_unavailable`,
`calibrated_safety_unavailable`, `autonomous_executor_unavailable`.

The user-reported stopped training002 result is UNQUALIFIED: three rounds/144
transitions, best mean 0.4915357 versus better constant 0.4909349 (required strictly
greater than 0.5109349), heuristic 0.53758, stop reason
`low_quality_no_advantage_over_constant`. These are handoff evidence, not a runtime
qualification manifest. This module does not read mutable training pointers, import
AI code, train, fabricate confidence, or set `manual_approval=true`.

## Contracts

`schemas.py` is the concrete OpenAPI/frontend source for `AutonomyResponse`,
`DecisionResponse`, `Observation`, `Proposal`, `SafetyAssessment`, `Verification`,
`SetAutonomyRequest` and `StopAutonomyRequest`.

Approved endpoints use the canonical `success/data/meta/errors` envelope:

- `GET /api/v1/autonomy?network_id=UUID&history_limit=20` (history 1..100).
- `PUT /api/v1/autonomy` with network, monitor/recommend/autonomous mode, optional
  exact lowercase checkpoint SHA-256 and timezone-aware approval expiry, and
  mandatory `expected_revision` (strict integer >=0, never bool/string/null).
- `POST /api/v1/autonomy/stop` with network ID.

Responses distinguish mode, readiness, blockers, provider status, emergency latch,
approval actor/expiry, cancellation state, active execution, observation and bounded
decision history. Evidence and measured values are nullable/unavailable when absent;
no constant "confidence" is returned. Approval duration is at most one hour.

GET returns `revision: 0` for an absent control. PUT omission/invalid revision is
422; stale revision is canonical 409 `AUTONOMY_REVISION_CONFLICT` with no mutation.
Frontend must refresh and require explicit user confirmation, not automatically
retry with a newer revision. STOP body is unchanged: `{network_id}` only.

`SafetyAssessment` now includes nullable `selected_action: SafetyAction`,
`certificate: SafetyCertificate` and `binding: SafetyBinding`. The full shield
certificate retains routes, drift, envelope, run/snapshot/input identity and
exclusive expiry. Binding includes scoped observation, policy, calibration,
state and content hashes. `DecisionResponse.authorization` is nullable and
contains immutable canonical safety/action JSON, hashes, expiry and the existing
server-owned execution identity. These are output/provider fields, never PUT inputs.

## Persistence And Worker

Migration `0013` owns only `autonomy_controls` and `autonomy_decisions`. It includes
due-work/history/observing indexes, unique active execution identity and control
constraints. A separate durable acceptance timestamp prevents rejected older
observations from lowering replay protection. No new event names or channels.

Only migrate the intended deployment with operator approval. Shared development
databases are not migrated by the verifier. After migration, run from `backend`:

```bash
PYTHONPATH=. poetry run python scripts/run_autonomy_worker.py
```

The API never starts this worker. Cycles use bounded I/O, database-time leases,
`FOR UPDATE SKIP LOCKED`, per-network acceptance/stop locks and revision/token
fencing. Callback authority is checked again before commit. Actual dispatch still
requires a future executor adapter to atomically enlist durable work and recheck
current server-owned authority, stop/revision, deadlines and the distributed
actuation lock at the receiver. Test providers are not installed integrations.
Acceptance retains and validates the exact structured SafetyShield certificate;
it rechecks exclusive certificate expiry before and after the callback. Executor
`accept(db, authorization)` receives only immutable canonical evidence and the
selected action (including safe projection), not an unbound original proposal.
The receiver MUST check hashes, trusted calibration and expiry again under its
dispatch lock. Readback uses a server-created exact owned `ExecutionReference`;
recovery accepts that reference without any client or impersonated actor fields.

## Verification

```bash
poetry run pytest tests -q --no-cov
poetry run ruff check app tests scripts alembic/env.py alembic/versions/0013_governed_autonomy.py
PYTHONPATH=. poetry run python scripts/verify_autonomy.py --live
```

The opt-in verifier creates dedicated PostgreSQL/Redis/Neo4j containers, migrates
only its disposable database, runs real transaction/lock tests, uses real login and
HTTP with an independent worker, checks monitor/recommend/rejected autonomous/stop,
and asserts zero execution jobs. It never starts a lab or enables actuation. It
removes only its own containers and writes sanitized evidence under `/tmp/opencode`.
Real authority is retained in HTTP checks; transaction tests use explicitly injected
providers/authority, not physical intervention evidence.

Prior verification 2026-09-09 (before revision/certificate/recovery hardening):
full backend suite 1,576 passed/12 opt-in skips; all four new
PostgreSQL tests separately passed in disposable infrastructure; scoped Ruff and
`git diff --check` passed. Final live HTTP/independent-worker evidence:
`/tmp/opencode/autonomy-verification-odmjqg8w/result.json`. Monitor, blocked
recommendation, autonomous 409 with unchanged mode, durable stop, zero execution
jobs and owned-resource cleanup all passed. Full-directory `ruff check .` retains
one unrelated existing import-order finding in migration `0001_initial_schema.py`.

Steps 9/10 remain open for physically calibrated bounds, qualified compatible
inference, server-authorized durable dispatch and a live verified intervention.

Revision/certificate/recovery hardening verification (2026-09-09): 1,601 backend
tests passed with 14 opt-in skips; all six autonomy PostgreSQL tests separately
passed in disposable infrastructure. Scoped Ruff and whitespace checks passed;
full-directory Ruff still has only the unrelated migration 0001 import-order issue.
Live evidence: `/tmp/opencode/autonomy-verification-4c_q51nq/result.json`.
Monitor/recommend, rejected autonomous, stale PUT after STOP, durable latch, zero
execution jobs and owned-resource cleanup passed. No lab was started, shared
database migrated, or training/safety.py/frontend source modified in this hardening.
