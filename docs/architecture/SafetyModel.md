# Conditional One-Step Safety Model

Authority: ADR-012 and `docs/features/Autonomy.md`. Implementation is confined to
`backend/app/modules/autonomy/safety.py`. These are synthetic arithmetic and
contract checks, not installed physical calibration, authorization, or evidence
of successful network intervention. Production dispatch remains disabled.

## Public Interface

```python
SafetyShield(
    policy: SafetyPolicy | dict | None = None,
    calibration: TrustedCalibration | dict | None = None,
)

SafetyShield.evaluate(
    observation: SafetyObservation | dict | None,
    proposed_action: SafetyAction | dict | None,
    alternatives: list[SafetyAction | dict] | None = None,
    *,
    state: SafetyState | dict | None = None,
    now: float,
) -> dict
```

This synchronous, side-effect-free evaluator does no I/O, neural training, API
handling, worker scheduling, persistence, authorization or dispatch. Constructor
configuration errors raise Pydantic `ValidationError`; malformed runtime evidence
returns `no_dispatch`. Missing constructor policy or calibration always refuses.
All input models are defined in the same module and expose Pydantic JSON schemas.
Public models are `AllowedPath`, `DemandRoute`, `SafetyPolicy`,
`TrustedCalibration`, `QueueObservation`, `DemandObservation`, `SafetyObservation`,
`QueueBounds`, `CandidateBounds`, `SafetyAction`, and `SafetyState`.
`SafetyModel` is their strict base; `EvaluationClock` validates the evaluator clock.
The provider helper is
`safety_input_digest(observation: SafetyObservation | dict, routes: list[DemandRoute | dict]) -> str`.
Numeric quantities are strict finite floats (integer JSON numbers are accepted as
numeric values, but booleans and strings are not); counts are strict integers.
Fields name their units: bytes, bytes/second, seconds, Unix timestamp seconds,
or bytes squared. Null measurements, NaN, infinity, negative physical quantities,
unknown fields and inconsistent intervals are rejected. Negative drift budgets
are permitted as an explicit stricter policy.
Sequences are bounded to signed 64-bit nonnegative integers. Action-rate limits
cannot exceed the 10,000-entry history contract; other scope lists allow at most
256 entries and evaluation accepts at most 255 alternatives.

Return keys:

- `decision`: `accept`, `project`, or `no_dispatch`.
- `selected_action`: complete validated candidate, retaining action and route IDs,
  or null. No new route/action is synthesized, including a supposed safe hold.
- `reason`: machine-readable outcome.
- `checks`: per-candidate blockers and available model certificates. Common evidence
  failure instead produces a common check with null action ID.
- `certificate`: selected conditional model certificate, or null.
- `validity`: `{valid: bool, conditional: true}`; never an authorization token.
- `expires_at_unix_seconds`: exclusive dispatch deadline, or null.
- `drift`: before/next Lyapunov values, upper drift and budget in bytes squared.
- `envelope`: threshold and per-egress next-queue upper bounds in bytes.
- `guidance`: recheck before dispatch, or refuse and reconcile/seek operator review.

All candidates with valid schemas are evaluated. The proposed candidate wins if
admissible; otherwise the lexicographically smallest admissible alternative action
ID wins, independently of alternative input order. IDs must be unique. Invalid
candidate schemas do not prohibit a separately valid alternative. Model checks and
rate/dwell/hysteresis checks are distinct: a model certificate in a rejected
candidate's checks does not make that candidate dispatchable.

## Trust Boundary

`TrustedCalibration` is a server-owned, versioned installation record injected by
trusted backend code, not a `calibrated=true` field accepted from an API payload.
Its network/run, provider/model/calibration identity, validity interval, complete
egress/demand scope and minimum uncertainty margins constrain every evaluation.
The default has no installation record. Unit fixtures explicitly inject test-only
records and do not close the physical calibration gate.

Injection is a trust boundary, not cryptographic authentication: matching IDs alone
do not establish provenance. The caller MUST obtain observations and candidate
bounds directly from the authenticated calibrated provider, bind the full action
(including demand-to-route assignments) to its bounds, and prevent client/model
payloads from becoming trusted policy, calibration or actuation history. This
module cannot detect a lying authenticated provider or establish omitted traffic.
Calibration must establish complete egress scope, complete demand attribution and
the dynamic inequality below, including background traffic, upstream bursts,
cross-traffic, scheduler contention, downstream effects, queue measurement error
and transition/delay behavior. Generic port utilization is insufficient.

Observation, bounds, candidate and state must share the same network/run/snapshot;
bounds and state must share the queue observation timestamp exactly. Bounds also
bind action identity and policy version. `CandidateBounds.input_sha256` is required:
the trusted provider computes it with `safety_input_digest` on the observation and
demand routes actually used to derive the bounds. The evaluator recomputes and
compares it, rejecting mutated queues, capacities, demand/source data or routes
even when snapshot/action IDs are reused. It hashes validated JSON with sorted keys,
compact separators, UTF-8 encoding and demand routes sorted by demand/route IDs;
observation list order is retained. The selected certificate retains this digest.
Never recompute the provider's digest in an API adapter merely to make changed
inputs pass. A hash is not a signature: trusted acquisition of the entire bound
record is still mandatory, including its horizon, delay and numeric bounds.
Policy versions must identify immutable server configurations.
Calibration scope is exact, not just a subset of supplied
egresses/demands. Unknown/unattributed demands, duplicate or omitted identities,
counter resets, future/stale timestamps, sequence replay or run mismatch refuse.
Run resets require a newly reconciled trusted context; never reset the sequence
watermark to reuse pre-reset evidence.

Each demand selects a configured permitted route, whose directed egress chain must
connect its observed source and destination without cycles. All egresses, including
unselected ones, require bounds. Summed demand arrival upper bounds along each
route must not exceed that egress's supplied arrival upper bound. This is a
necessary consistency check, not a proof of counterfactual traffic attribution.
Arrival/service lower bounds must not exceed their upper bounds; service upper
(therefore also service lower) cannot exceed observed capacity. Service uncertainty
width and additive model error cannot undercut installed calibration minima.

## Model and Proof

Fix an observed nonnegative queue vector `q` over a complete finite egress set,
an action `a`, a positive horizon `dt`, nonnegative arrivals `A_i`, guaranteed
service lower bounds `S_i`, and nonnegative additive errors `E_i`. Units are bytes
for queues/errors and bytes/second for arrival/service. The REQUIRED provider
assumption, for the full interval starting at the observation, is:

```text
0 <= q_actual_next_i <= U_i
U_i = max(0, q_i + (A_i - S_i) * dt) + E_i
```

This is an explicit bounded fluid, one-step *model assumption*, not something
deduced from aggregate counters. Arbitrary total arrival/service bounds do not
alone justify it: arrivals late in an interval can invalidate subtraction of
earlier unused service. Calibration must establish suitable within-interval
dynamics/service guarantees or absorb the discrepancy into `E_i`. Bounds must
cover the pre-actuation interval, old/new route transition and all permitted
delays, not assume the proposed action was already active at observation time.

For fixed positive `Q` and finite configured drift budget `B`, define:

```text
V(q) = (1/2) * sum_i q_i^2
D_upper = (1/2) * sum_i (U_i^2 - q_i^2)
```

The model checks require `q_i <= Q`, `U_i <= Q` for every egress and
`D_upper <= B`. Since squaring is monotone on nonnegative reals,

```text
0 <= q_actual_next_i <= U_i <= Q
V(q_actual_next) - V(q) <= V(U) - V(q) = D_upper <= B.
```

This proves conditional envelope preservation and the configured one-step drift
budget. An initially violated envelope is not labelled preserved even if an action
would reduce its queues. Threshold and drift checks are independent. `B=0` is the
default; a positive budget explicitly permits bounded positive one-step drift.
No measured actual queue or performance improvement is fabricated.

The implementation computes exact rational expressions over the validated binary
floating-point inputs for comparisons, avoiding cancellation and floating-point
overflow false acceptance. Serialized queue, Lyapunov and drift bounds round
outward; expiry rounds inward. Unrepresentable certificate values refuse and no
NaN/infinity appears in results. Serialized before/after values are rounded
independently: use the provided outward-rounded drift, not their subtraction.
This establishes numerical conservatism only for supplied input values; physical
measurement precision and uncertainty belong in the calibrated bounds.

## Time Validity

Let `t0` be the observation timestamp, `L` the candidate's upper actuation delay,
`F` the policy freshness limit, `D` its permitted total observation-to-actuation
delay, and `t_end=t0+dt`. Requirements are:

```text
0 < dt <= configured max_dt
t_end <= bounds.valid_until
t_end <= calibration.valid_until
calibration.valid_from <= t0 <= now
now < expires = min(t0 + F, t0 + D - L, t_end - L)
```

The horizon is observation-anchored, not `now + dt`; waiting cannot extend a proof.
The provider must support the entire declared horizon, not just time of dispatch.
The executor must recheck expiry, provenance, run/snapshot sequence and current
authorization under its serialization lock immediately before actuation. This
module certifies an endpoint only, not every instant inside the interval.

## State and Oscillation

`SafetyState` comes from fresh trusted durable executor history, separately from
queue/model evidence. It contains active demand routes, when that route assignment
became active, last applied time, a complete dispatch-time window, and the last
evaluated snapshot sequence. History must cover the entire configured rate window;
future, duplicated, unordered or inconsistent times refuse.

Every dispatched candidate, even one retaining the same routes, consumes action
rate allowance. Route changes also require elapsed minimum dwell. A positive
hysteresis margin requires an explicitly evaluated incumbent-route candidate with
valid model evidence over the SAME horizon, and checks
`V(U_incumbent) - V(U_candidate) >= margin` in bytes squared. The incumbent need
not be safe: its numeric bound supplies comparison evidence, not a safe fallback.
Absent incumbent evidence blocks a switch when hysteresis is enabled.

Evaluation never updates applied times, dispatch counts or route-since time.
Repeated refusals therefore cannot restart a hold-down period. The caller must
persist evaluated sequence watermarks and atomically reserve dispatch slots before
execution, retain conservative unresolved-dispatch history, and only update active
routes from reconciled application evidence. A stale or forged state can invalidate
these gates; the evaluator is not a distributed lock or replay database.

## Limits and Infeasibility

For a queue above the reflection boundary, the increment bound is
`(A_i-S_i)*dt + E_i`. Positive uncertainty therefore requires a *robust* service
margin: `S_i-A_i > E_i/dt` for a strictly negative individual increment. Nominal
service above nominal arrivals is insufficient when its calibrated lower bound
and positive error are considered. At reflection, `U_i=E_i`, not zero. In
particular, positive error at an empty queue can make zero-budget certification
infeasible even when the physical queue might remain empty.

If every permitted action has overload, excessive error, nonpositive robust
service margin, a threshold violation, or insufficient rate/dwell evidence, the
admissible set may be empty. The response is `no_dispatch`, not an assertion that
holding is safe or that the network has become stable. Reconciliation, operator
intervention or a separately governed traffic-control mechanism may be necessary.

Strict negative drift outside a target set requires a separately established
uniform condition such as `D_upper <= -epsilon` there, existence of an admissible
action at every step, and continued validity of all modeling/execution assumptions.
Repeated conditional certificates can establish sampled envelope invariance only
if those assumptions and complete inter-step coverage hold at every step. This
implementation proves neither global queue stability nor a continuous-time neural
adaptation law, PPO convergence, probabilistic confidence, arbitrary-campus safety,
intersample safety, or real measured benefit. Positive budget alone is not a
negative-drift stability theorem. Physical calibration and a live authorized,
verified intervention remain explicitly open ADR-012 acceptance gates.

The training campaign stopped at its quality gate with no qualified model (user
handoff, 2026-09-09). These synthetic safety tests do not qualify a checkpoint or
replace physical calibration. AI, emulation and training artifacts are outside
this module's implementation scope and remain untouched.
