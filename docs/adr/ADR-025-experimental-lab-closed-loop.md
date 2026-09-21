# ADR-025: Bounded Experimental Lab Closed Loop

- Status: Accepted under the user's explicit selection of experimental lab autonomy
- Date: 2026-09-20

## Decision

Implement a separate operator-launched **experimental-lab** controller connecting
fresh measurements, the ADR024-qualified unchanged-weight model, configured-model
simulation admission, explicit lab authorization, actual routing, independent
readback/traffic verification and keep/compensate decisions. This is empirical,
bounded software-lab operation, not formally calibrated autonomy. Existing
`monitor`, `recommend`, `autonomous`, SafetyShield and qualification requirements
remain intact; no production readiness flag or safety certificate is synthesized.

## Scope and authority

Only new disposable network-disconnected labs, exact image/source/model pins,
declared device/route IDs and preregistered operational scenarios are allowed.
Preserve original weights, frozen source trees, prior evidence and shared services.
One process family owns the lab action surface; measurement code and a second
driver must never compete for routing. A qualified-runtime instrumentation wrapper
may surround unchanged routines, with its own source fingerprint and scope
equivalence evidence; never call a modified image the qualified original.

Operator policy is strict versioned protected configuration, hash-pinned before
acquisition: actor/scope, lab/container identity, model registry, permitted routes,
maximum observation age, minimum dwell, action/window count, action duration and
experiment expiry, explicit simulation assumptions/objectives and verification
thresholds. Current actor authority, STOP and expiration are checked before each
new mutation. Shutdown/revocation does not revoke exact-owned restoration authority.
Timeouts are operational bounds, not mathematical guarantees of completion.

## Persistence and integration

Autonomy owns new `experimental` modules and, if needed, migration0028 after0027
for dedicated experimental controls/journals. Expose an operator CLI/status/stop/
recover interface initially; no new public REST mode, socket event or frontend
state enum is authorized. Use current owning Identity/Network service contracts
for authorization, Telemetry evidence pins for referenced rows and Simulation's
pure evaluator for numerical predispatch admission. Keep lab authority/configuration
outside inference. Inference runs confined in the independent frozen AI environment.

Persist proposal, observation/model/simulation hashes, approved bounded command and
rollback identity before I/O. Leases, fencing, exclusive lab ownership and immutable
request IDs prevent concurrent/replayed changes. After uncertain dispatch, reconcile
or restore exact owned state; never replay an execute just to obtain an answer.
Restart recovers prior ownership before admitting new work. STOP is durable and
dominates queued actions. Plan-changing retries require new explicit admission.

## Measurement and acceptance

Preregister fresh unused operational seeds, finite scenarios, baseline comparators,
failure cases and thresholds before collection. Keep all attempts and negative
results. Verify exact selected route with independent readback and actual goodput,
probe loss/RTT, timestamps and count provenance. Missing metrics remain unavailable.
Keep route only while measured policy checks pass; restore on expiry, verification
failure, STOP, revoked actor, stale data or uncertain controller state.

Required cases: both directional congestions, fixed0/fixed1 and heuristic matched
baselines, stale/delayed measurements, STOP, current authority revocation, route/link
failure, controller disconnect, process restart, ambiguous result and partial apply/
compensation. Do not label predispatch rejection as rollback or fixture mutation as
measured effect. Report per-case and paired metrics, decision/action/recovery latencies,
scope limitations and cleanup. Final success requires a real joined loop, not the
previous separate recommendation and manual-driver results.

Parallel agents own disjoint core/driver/verification files; privileged campaigns
are serialized by the common lab lock. Independent review precedes final acceptance.

## Internal comparator and bootstrap clarification (approved 2026-09-20)

The same experimental controller may run preregistered `model`, `fixed0`, `fixed1`
and `heuristic` policies. Baseline records identify their actual policy and retain
null model qualification, probabilities and critic value; they never impersonate
PPO inference. Every policy uses identical current authorization, numerical
simulation admission, bounded execution, measured verification and exact recovery.
This expands only the private experimental protocol, not public modes or APIs.

The controller journal UUID and original measured episode UUID are separate.
Snapshots retain the original episode UUID and raw history unchanged. A protected
measurement identity or a committed authoritative receiver bootstrap receipt binds
them. Campaign reset is an explicit journaled bootstrap mutation before read-only
observation. Original baseline ownership is committed before reset, and recovery
retains that capability even if no action reaches preparation. Wrapper equivalence
and adapter source identities are independently pinned; benchmark qualification
does not become a formal calibration or wrapper safety certificate.
