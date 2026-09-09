# ADR-010: Durable Manual Lab Execution

- Status: Accepted for user-requested completion-plan Steps 5 and 6
- Date: 2026-09-09

## Scope and Safety Policy

Extend ADR-009 only for explicitly approved manual changes inside its disconnected,
disposable campus lab. This is not production deployment or a claim of simulation
validation. ADR-008 continues to block all production control until real risk
evaluation exists. Demo mode remains non-actuating. Execution requires emulation
mode, separate opt-in `EMULATION_CONTROL_ENABLED`, current actor capabilities
`write:config` and `execute:rollback`, writable tenant membership, a matching
operator binding, a fresh lab run, and `manual_approval=true` in the execution
request. The approval is persisted with actor/time/immutable plan digest. Never
infer approval from mode, confidence score or an arbitrary validation-check string.

## Public Contract

Keep existing validate/execute/detail routes and canonical envelopes. Extend
ExecuteIntentRequest with `manual_approval: bool=false`, `cancel: bool=false`.
Cancel requests are authenticated against the same tenant and return existing
execution lifecycle data; cancellation after dispatch requires reconciliation/
rollback, not an assumption that a timed-out action never ran.

Validated `intent` shape for executable lab plans:
`{action:"reroute_path"|"throttle_qos",scope:{source_host:"h1".."h4",
destination_host:"h1".."h4"},constraints:{operation:"reroute"|"multipath"|
"shape"|"police"|"restore",paths:[[switch_name,...]],weights:[positive_int,...],
rate_mbps:positive_number|null,dscp:0..63|null}}`.
Paths are complete source-access to destination-access simple paths using observed
links. Reroute needs one path, multipath two paths; absent weights means equal.
Shape/police rates and selectors must be bounded by trusted capabilities; DSCP is
an optional explicit traffic classifier. Restore compensates the last matching
owned policy, never deletes arbitrary switch rules. Reject unknown parameters,
unsupported VLAN/wireless actions and unsupported group/meter features explicitly.

Execution acceptance returns HTTP 202 with `execution_started` and durable job
metadata. Detail exposes execution ID, phase, deadline, verification, rollback,
failure/uncertainty and immutable action digest via `execution_provenance`.
No learned confidence is claimed. Only actual readback can produce completion.

## Module Ownership and Worker

Intent owns new PostgreSQL `intent_executions` and `intent_outbox` tables. Use
versioned Alembic migration 0011. Unique execution per intent and workspace-scoped
request identity prevent concurrent dispatch duplication; reused keys with another
request fail 409. Preserve existing historical rows, not destructive deduplication.
Acceptance and its immutable outbox event commit together. Terminal state and
terminal event commit together. Outbox events retain their event_id/timestamp on
retry and reuse the four existing intent lifecycle names. Actor and binding checks
use owning services; Intent must not query Network tables.

A dedicated unprivileged asyncio worker is approved for this bounded I/O state
machine (exception to generic Celery guidance; no heavy ML/report work added).
It polls PostgreSQL, atomically claims leases, rechecks authorization before
dispatch, renews fenced leases/Redis per-lab locks, and recovers expired leases.
Never hold a DB transaction while awaiting the lab. Lab-side journal and operation
serialization prevent an old worker from applying a duplicate action. Recovery
reuses command identity and reconciles actual state instead of blind redispatch.

## Lab Transport

Operator-provisioned `emulation/commands` is worker-writable/lab-read-only;
`emulation/results` is lab-writable/worker-read-only. Both are separate from
telemetry output and trusted binding. No socket/network endpoint or Docker socket
is exposed. Strict bounded JSON file transport, atomic replacement/fsync and
symlink refusal. Only fixed UUID-named command/result files; no caller executable,
shell fragment, filename or arbitrary interface. The lab's legacy code remains
isolated and trusted; privileged containers are not a hostile-code sandbox.

Command v1: `{version:1,execution_id:UUID,run_id:UUID,binding_digest:sha256,
plan_hash:sha256,fence:positive_int,deadline:UTC,dispatch_expires_at:UTC,operation:"execute"|"cancel",
plan:{operation,source_host,destination_host,paths,weights,rate_mbps,dscp}}`.
Plan hashes use sorted compact JSON with all seven fields present, nulls included.
Command file `<execution_id>.json`; result `<execution_id>.json`.
Result v1 includes matching version/execution/run/binding/plan identities, fence,
`status:"completed"|"failed"|"cancelled"|"uncertain"`, `verification:object`,
`rollback:object|null`, `failure_reason:string|null`, `completed_at:UTC`.
Only terminal results are published. Internal journal persists prepared before-state,
phase, deadline and after-state before mutations/acknowledgment. Duplicate commands
with changed identity/plan are rejected. Stale run/deadline/fence cannot authorize
new changes. Lost response recovery returns the recorded result after reconciling
journal/actual state. Ambiguous or failed rollback blocks further lab mutations.

### Short Dispatch Authorization (Review Amendment)

`dispatch_expires_at` is required on the wire, no later than `deadline`. Acceptance
stores pending plan metadata without this field; only the first dispatch CAS sets
and commits it together with dispatch possibility, before file publication. It is
derived from remaining monotonic worker authority, bounded by the DB lease and a
fixed maximum five-second window. Later renewals, recovery and cancellation never
change it. Plan hashes exclude this transport metadata. Result fields are unchanged.

The lab MUST require `now < dispatch_expires_at <= now + 5 seconds` and the action
deadline before preparing a NEW journal operation, rechecking after potentially
blocking discovery/readback immediately before preparing that operation. Missing,
expired or overlong authorization cannot initiate mutation. Return verified
no-mutation evidence only after actual reconciliation. Once prepared durably within
the authorization window, that operation may continue under its original action
deadline independently of the sender lease; compensation/reconciliation and cancel
remain allowed after dispatch expiry. Journal duplicate identity includes the
immutable dispatch expiry. Host and disconnected container share the same UTC
clock; this protocol is not approved for independently skewed clocks.

Sender locks/expiry checks alone cannot close a pause after the final check before
rename. Receiver enforcement is mandatory before this amendment is deployable;
backend-only tests do not certify the lab boundary. No blind redispatch or refreshed
authorization is permitted on recovery.

## Real Driver and Verification

Protocol mechanics stay under `emulation/`. Rerouting uses separately owned higher
priority OpenFlow rules; multipath uses supported SELECT groups and verified bucket
references; policing uses supported meters; shaping uses actual bounded Linux/OVS
queues without destroying unrelated Mininet qdiscs. Capability discovery, explicit
matches and return traffic handling precede mutation. Coordinate baseline Ryu
rules so they cannot bypass or erase owned policies. Capture actual before-state,
barrier/error acknowledgment and independent readback; verify traffic effects.
Compensation restores only owned state and verifies it. This is not atomic packet
history rollback. Hold-down/action-rate limits apply per lab and traffic selector.

## Event Recovery and Deployment

Fix Redis consumer recovery using pending reclaim and unique consumer identities.
Do not mark dedup before handlers succeed. Add per-handler replay protection where
effects require it; Audit owns durable event identity via migration 0012. Poison
messages go to DLQ with ACK only after durable DLQ publication. Preserve unknown
event handling; no new domain event name is invented. This is at-least-once, not
universal exactly-once. Outbox scope is execution lifecycle, not a retrofit of every
historical module producer. Telemetry source sampling is not made crash-durable.
Explicitly constrain the API to one active realtime process with a lease/guard
until cross-process websocket fanout exists. Separate execution worker may restart
independently. Global recovery must not drain unrelated live data during tests.

## Verification

Require actual reroute/group/shaping/policing/restore checks, failed-action
compensation, duplicate/concurrent request exclusion, worker restart/lost result
recovery, authorization revocation, deadline/cancel handling, outbox retries and
pending-entry reclaim. Use disposable migrated DB scopes/groups for fault tests.
No action is successful merely because a request file was created. Report any
unimplemented action or unreproduced crash boundary as a limitation, not completion.
