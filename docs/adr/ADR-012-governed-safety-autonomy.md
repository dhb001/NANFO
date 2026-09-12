# ADR-012: Governed Safety and Autonomous Loop Boundary

- Status: Accepted for user-requested completion-plan Steps 9 and 10
- Date: 2026-09-09

## Constraints

Preserve the active frozen training campaign: do not edit ai-engine Python sources,
dependencies, lab sources/image or campaign artifacts; do not start a competing lab.
Implement in Backend-owned Autonomy module and frontend only. Production dispatch
remains disabled. Online learning is always disabled. No claim of PPO convergence,
Lyapunov stability of an arbitrary campus, or proactive measured benefit is made.

## Safety Model

Use an explicit one-step, bounded fluid queue model in BYTES for each affected
egress: q_next <= max(0,q + arrival_upper*dt - service_lower*dt) + error_upper.
All bounds must be supplied by a trusted versioned provider, with observed queues,
capacity, freshness, traffic attribution, connectivity and action identity; generic
port utilization alone does not establish counterfactual arrival/service bounds.
For a fixed positive queue threshold Q and V(q)=sum(q_i^2)/2, certify only predicted
one-step envelope preservation q_next<=Q and drift <= a configured budget (zero by
default). Strict negative drift outside a target set is a separate conditional
property, not inferred from weight clipping or empirical decreases. Model mismatch,
missing bounds, stale data, excessive delay or infeasible overload yields refusal,
not a synthetic safe prediction. Maintain explicit per-candidate checks/evidence;
project onto an admissible candidate if present, otherwise return no-dispatch with
hold/reconcile guidance. Rate/hold-down and permitted-path constraints also apply.

This establishes a conditional discrete-time certificate under stated bounds; it
is not the proposal's continuous-time neural adaptation proof. Neural adaptation
is not invented as a stand-in for justified dynamics. Tests must distinguish
bounded numeric logic from real bound calibration, which remains an open gate.

## Autonomy Module and API

Autonomy owns PostgreSQL `autonomy_controls` and `autonomy_decisions` (migration
0013 after 0012). Existing modules are accessed via public services, no cross-table
queries. Approved new surfaces in the existing canonical envelope:

- GET `/api/v1/autonomy?network_id=UUID`: authorized scope/mode/status/gate reasons
  and bounded latest decision history; read:telemetry and active membership.
- PUT `/api/v1/autonomy`: `{network_id, expected_revision:nonnegative_integer, mode:"monitor"|"recommend"|"autonomous",
  expected_revision:integer>=0, checkpoint_sha256:null|string, approval_expires_at:null|UTC}`. Requires
  write:config + execute:rollback, current writable org membership. Autonomous
  selection requires exact operator-configured checkpoint qualification, compatible
  observation provider and calibrated safety model. Missing gates return 409 and
  do not change mode; no user-supplied model path, fake risk bounds or confidence.
  Revision is taken from the latest GET; a request predating STOP fails 409 and
  cannot clear the latch. No automatic retry/reapproval after revision conflict.
  `expected_revision` is mandatory and matched under the control write lock after
  readiness I/O against both the captured server revision and current persisted
  revision. An absent control has revision 0. A stale PUT returns 409
  `AUTONOMY_REVISION_CONFLICT`, preserving any newer stop latch; clients must
  refresh and require a new explicit user action, never silently retry.
- POST `/api/v1/autonomy/stop`: `{network_id}`. Persist emergency-stop latch before
  attempting cancellation of any Autonomy-owned execution via existing Intent
  cancellation service, never an unrelated manual execution. Stop never clears
  itself; explicit mode change is required, subject to gates and unresolved work.

Status distinguishes requested mode, actual readiness, blocked reasons, online
learning=false, last observation/decision, model hash and active execution ID.
Changing to monitor never authorizes a route change. Recommendation mode records
non-actuating proposals only. Approval is bounded in time and scoped to actor,
network and model; current permissions and emergency latch are rechecked each cycle
and immediately before any accepted dispatch.

Safety acceptance retains the complete selected action, routes, certificate,
calibration/input identity and exclusive expiry, not merely an admissible boolean.
The durable executor must recheck those bounds under its receiver lock. Outstanding
execution verification occurs before current operator authorization; compensation
requires separately governed exact-owned server recovery authority. Missing recovery
authority records operator_recovery_required and retains exclusion, never impersonates
the revoked approving user or synthesizes manual approval.

## Pipeline

One reusable service cycle: observe -> validate provider contract/freshness ->
qualified frozen inference -> safety -> approval -> durable execution -> verify.
Typed provider/inference/executor interfaces separate test doubles from installed
production integrations. Never encode ordinary telemetry as experiment PPO input.
Default installed observer may expose ADR-009 health and scope, but must report
`observation_contract_incompatible` for V2 experiment inference. Until an approved
compatible provider and bound calibration are installed, autonomous mode stays
unavailable. A `best.json` pointer is not qualification or safety confidence.

No automatic setting of ADR-010 `manual_approval=true`. Autonomous execution needs
distinct server-owned authorization understood/rechecked by the durable executor.
If that authorization adapter is absent, gate `autonomous_executor_unavailable`
blocks dispatch. No no-op executor can produce a completed decision. A separate
bounded I/O worker processes enabled network records, catches failures per cycle,
persists diagnostics and rate limits. Model training is never run inside this worker.

Safety assessments retain the actual structured SafetyShield certificate, full
selected action/routes, scoped observation, policy/calibration/state inputs and
canonical observation/proposal/calibration/action hashes. Acceptance validates
the binding and certificate and checks its exclusive expiry before and after
the executor callback, not merely the generic telemetry freshness limit.
The immutable authorization persists canonical safety/action JSON and hashes in
the decision transaction. The future receiver MUST recheck trusted calibration,
exact selected action, hashes, expiry and separate authority under its dispatch
lock. Hashes bind content, not provider authenticity or physical calibration.

Outstanding owned execution is verified read-only by exact persisted identity
before checking the old actor. Revocation, expiry or stop requires compensation
through a separately governed server-owned recovery interface, never synthesized
old permissions or manual approval. No recovery adapter is installed: unresolved
work records `autonomous_recovery_unavailable` / `operator_recovery_required`
and retains exclusion. Explicit user STOP can still request cancellation through
the public Intent service using the stopping user's current authority. Automatic
recovery adapters need independent receiver-side ownership/fence checks; this
ADR does not introduce a public system-cancel endpoint or an authorization bypass.

Qualification must bind checkpoint, completed measured validation, comparable
spec/schedules and baselines. Minimum three rounds/144 trained transitions and
best mean > better constant baseline +0.02 are necessary but not safety proof.
Current active training artifacts are read-only; no automatic deployment of latest.

## Closure Gates

Automated tests: drift math, unsafe projection/refusal, missing/stale/delayed data,
overload, hysteresis/repeated rejection, cross-tenant/RBAC, approval expiry/revocation,
emergency stop before dispatch, uncertainty and replay protections. Frontend shows
real readiness, mode and blockers, no success from enqueue alone.

Do not mark Steps 9/10 end-to-end complete until bounds are physically calibrated,
model/provider qualification exists, autonomous executor authorization is wired,
and a live controlled scenario demonstrates verified intervention and timing.
Current scope may finish the tested fail-closed foundation while leaving those
gates explicitly open rather than interfering with ongoing training.
