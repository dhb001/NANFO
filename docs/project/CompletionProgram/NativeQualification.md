# ADR024 native FRR qualification: design and parent handoff

## Q1/Q2 installation integration — current handoff

**This section supersedes the earlier explicit-v2-installation refusal below.**
V2 installation, provider mapping and receiver enforcement are now implemented.
No installation/trust was created and no native lab was launched. ContinuousAI
owns the current exclusive campaign; parent owns the next serialized native run.

### Supported runtime contract

`nanfo.calibrated-safety/v2` preserves each original reviewed queue profile:
physical capacity, nominal service-upper rate, burst bytes, nominal shaper metadata,
lower-service semantics, arrivals and error. It binds the exact v2 configuration,
minimum measurement horizon and independently accepted service derivation. V1
serialization/configuration/report shapes and semantics are retained.

Installation has a single **fixed dispatch horizon H = configuration.dt_seconds**.
Acquisition windows can lie in `[min_dt_seconds,H]`. No shorter or longer action
can reuse this installation; a different H requires a separately pinned/reviewed
installation. At exactly H every layer uses the same mapping:

```
S_upper = min(physical_capacity, outward(nominal_upper + burst/H))
S_lower = original_lower    if actual-departures
S_lower = 0                 if busy-period-available
```

`runtime_service_bounds` is shared by loaded-calibration action checks, installed
profile validation, provider evaluation and wire-command checks. Raw nominal and
physical fields are not changed. Exact `SafetyShield` arithmetic is unchanged.
No positive available service is promoted to future departures. A genuinely
accepted future actual-departure/dynamics guarantee must be submitted as an
explicit `actual-departures` profile with fresh scoped review; past busy traces
alone cannot do that.

The calibration loader verifies both the original measured service campaign and
its conservative runtime projection (lower=0 for available service), using the
same Q, B, arrival/error and holdout criteria. If the latter fails, installation
refuses with `conservative_runtime_network_validation_failed`. This is proof/
policy infeasibility, not an unimplemented mapping. Live provider evaluation again
uses the mapped values and the unchanged policy; no_admissible remains valid.

V2's global `min_service_uncertainty_bytes_per_second` is the inward-rounded
**minimum** of exact per-queue mapped widths at H. Global `min_error_upper_bytes`
is the minimum original per-queue error. Every queue's **full** original error
and mapped width remains enforced by exact profile checks. Using the maximum as
a global minimum would reject heterogeneous widths. V1 retains its original
rules; no old calibration or digest is regenerated.

Enforcement path:

1. `load_trusted_calibration` reconstructs accepted campaign, all guarantee
   references, service source evidence and (where applicable) accepted busy traces.
2. `IndependentInstallationValidator` matches original profiles, explicit version,
   source reference, fixed/minimum horizon, policy Q/B, execution/route bindings
   and exact global floors.
3. `ValidatedInstallation.assert_reviewed_execution` rechecks v2 profiles, not just
   routes, at the existing authority/read checkpoints. Provider maps at fixed H.
4. `AutonomousCommand.validate_installed_service` checks the installed hash and
   exact mapped queue values/horizon. `ReceiverJournal.checkpoint` invokes it for
   v2 before device mutation, followed by existing authority re-evaluation and
   final clock/exclusion checks. Loaded-calibration action validation also refuses
   horizon/profile mismatches.
5. Recovery remains independently ownership/fence checked; expired dispatch
   evidence does not disable exact compensation.

Two small trust-plumbing edits are required for actual composition and included:
`execution_settings.ExecutionClientConfig` and `autonomous_frr_receiver.ReceiverConfig`
accept protected `accepted_service_semantics_sha256` and
`accepted_native_backlog_sha256` sets, default empty, and pass them to the loader.
They do not derive these sets from producer evidence. Existing empty client-config
serialization stays unchanged. No new public API or autonomous wire fields.

### Parent-only sealed zero-arrival native epoch protocol

This is a precise **route-table transition/compensation** qualification, not a
nonzero adaptive-traffic, receiver-probe-success or deadline guarantee:

1. After ContinuousAI releases exclusivity, parent takes the host experiment lease,
   allocates fresh isolated namespaces/private outputs and pins kernel, image,
   source, PID/start/inode, interfaces, qdisc tree and controller ownership. Record
   source-level seal hook placement and all bypass exclusions before admitting
   evidence. No shared namespace or historical queue may be reused.
2. Establish OSPF routes/neighbor entries while unsealed, then **freeze routing
   daemon/controller writers** under independent ownership while retaining native
   kernel forwarding state and namespace keeper processes. Pin complete route/rule
   dumps, OSPF selected paths and ARP neighbor entries. Pausing daemons without
   preserving kernel routes is not equivalent; verify actual state afterward.
3. Install an all-ethertype pre-enqueue seal on **every one of the 22 directed
   egresses**, including hosts; no ARP/OSPF/probe exemption. Use a separate,
   explicitly reviewed seal table so the existing instrument's exact table
   comparison remains valid. Seal before declaring epoch start. Record seal
   readback and counters, remove all unreviewed tc/XDP/raw/offload bypass paths,
   and fence CAP_NET_ADMIN writers except the narrowly owned route mutator.
4. Account for packets already between the seal and qdisc enqueue: a userspace
   sleep, sender shutdown, endpoint-zero poll or empirical drain maximum is **not
   a barrier**. Require a reviewed kernel synchronization/barrier proving all
   pre-seal in-flight enqueue work is complete, or retain installation blocked.
   Once that barrier and zero backlog across the full native queue scope are
   established, leave seals installed for the entire epoch. Do not reset qdiscs
   in-window or claim their zeroed counters prove the barrier.
5. Acquire raw native/ns baseline under the seal. The mathematical domain is
   `A=0`, `S_lower=0`, `q(t)=0` for an exactly established empty epoch. Sensor E=0
   is permitted **only** by the proved invariant/exact accounting, not because
   observed residuals happened to be zero. If E>0 and B=0 then the unchanged
   shield may refuse: preserve the refusal. Nonempty draining epochs additionally
   need the genuine burst-aware departure bound and exact accounting.
6. On parent-authorized isolated native driver evaluation, call existing
   `LinuxFRRDriver.prepare`, journal the prepared resources, then `apply` with the
   independent ownership/deadline checkpoint. Retain every exact route/rule add,
   partial-state prefix and post-apply native dumps/path resolution. Tables19110/
   19111 must match `resources(action)`/`read_owned(complete=True)`. Enumerate path
   union and verify background paths from actual kernel route resolution.
7. **Do not call this successful `LinuxFRRDriver.verify`: it emits ping probes.**
   The sealed regime deliberately drops those probes, and the existing receiver's
   `valid_readback` requires successful replies. Use the driver's read-only
   inventory/path checks for this separately labelled experiment, then existing
   `compensate` under its recovery checkpoint. Preserve exact restored dumps,
   empty reserved tables and restored paths. Do not fabricate probe3/3 or change
   receiver acceptance. If testing receiver behavior under seals, its expected
   result is probe failure followed by verified owned compensation, not `verified`.
8. Keep the seals until evidence is complete and owned namespaces are destroyed.
   Unsealing ends the theorem. Retain all failures, uncertain mutations, cleanup
   identities and raw before/after counters. Rebuilding the routing state or
   thawing daemons belongs to a new epoch, not a continuation of the old proof.

The new v2 service installation no longer has a software mapping blocker. Genuinely
external gates are authentic preregistered native measurements, independent source/
accounting/service/arrival/dynamics review and accepted digests, enforceable writer
exclusivity and seal/in-flight barrier, runtime/model equivalence, and (if demanded
by installation) a hard transition-completion guarantee. Ordinary Linux userspace
timeouts do not supply the latter. Sealed readback/recovery cannot establish
nonzero adaptive benefit or RF qualification. The separate bfifo/control-traffic
observer adapter remains outside this HTB/netem v2 installation change.

## Q1 / Q2 / Q5 revision — explicit offline v2 semantics

This section supersedes the original schema/timestamp limitations below where
explicitly described. **No native lab or receiver run occurred during this
revision. Recovery campaign exclusivity is respected; next run belongs to parent.**

### Q1: actual departures versus available service

`NetworkQualificationConfig` v1 retains its original acceptance:
`departures >= service_lower * dt`, including idle and draining windows. The
default `service_lower_semantics="actual-departures"` now names this restriction.
No old idle-window failure becomes a pass by changing defaults.

Explicit `nanfo.network-qualification-config.v2` additionally supports
`busy-period-available`. This is intentionally a **full-window continuously busy
gate**, not a general service-curve evaluator for windows that become idle.
Every queue/window needs `native_backlog_evidence` whose exact digest the
independent reviewer accepted separately. Replay requires:

* a retained native source reference and a complete ordered mutation trace;
* exact sample, egress, full measurement digest, start/end times and counters;
* zero lost events and exact byte accounting (nonzero measurement error refuses
  this first implementation rather than pretending uncertain polls prove busy);
* strictly positive backlog initially and after **every** enqueue/dequeue/
  accounted-backlog-drop event, exact final backlog, and exact event totals.

The accepted digest is the review trust boundary for native trace authenticity,
completeness and instrumentation semantics. The software independently recomputes
the byte trajectory; it cannot authenticate an untrusted author by their own
flags. Endpoint polling is insufficient. `drop` in this trace means bytes removed
from the accounted queue, not pre-enqueue policer/tail rejection. Those drop
semantics must match the referenced counter derivation.

Only after this gate does available service imply actual departures over that
**measured** busy interval. Idle or fully drained windows still refuse; no
`min(q0+arrivals, service*dt)` shortcut. The original endpoint/dynamics/drift gates
remain unchanged. The queue bound still needs the independently reviewed
within-interval theorem and all predecessor/transition arrivals.

### Q2: burst-aware upper departures with independent physical capacity

V2 requires `min_dt_seconds` and `service_semantics_evidence: ArtifactRef`.
`verify_network_campaign(..., evidence_store=..., accepted_service_semantics_sha256=...)`
requires a separate accepted derivation digest and verifies its exact bytes before
any v2 acceptance. This source obligation covers kernel hierarchy, rate/ceil,
burst/cburst, quantum, timestamp/counter accounting and the physical-capacity
meaning. Missing trust refuses; merely putting a reference in the campaign fails.

Each bound adds optional `service_upper_burst_bytes` (default **0**) and
`shaper_nominal_bytes_per_second`. The latter is recorded metadata, never the
physical capacity. For each admitted `h_min <= dt <= H`, both checks must pass:

```
departures <= service_upper_rate * dt + service_upper_burst_bytes
departures <= independent_physical_capacity * dt
```

The second check is **not loosened**. If qdisc dequeue accounting or virtual-link
scheduling admits bursts above that instantaneous capacity, its physical-boundary
semantics have not been established and the campaign fails. Do not raise capacity
to an observed peak or nominal-plus-burst equivalent. V1 rejects nondefault v2
fields instead of silently adopting the new behavior. Tests reproduce 200 bytes
in 0.125s at nominal1000B/s: v2 burst evidence permits the shaper inequality with
an independently supplied10000B/s physical bound; physical1000B/s still fails.
Those are analytical test values, not a reviewed lab capacity.

### Exact runtime mapping still needed (installation explicitly refused)

The unchanged runtime stores `CalibratedQueue.service_upper_bytes_per_second`
without burst/min-horizon fields, and `IndependentInstallationValidator.validate`
compares it directly with campaign nominal rates. Accepting a v2 installation
through that path would erase semantics. Therefore `load_trusted_calibration`
and `LoadedCalibration.validate_action` explicitly refuse v2 with
`v2_runtime_service_mapping_not_installed`. A passing v2 campaign is **offline
measured acceptance only**, never an installed shield.

The pure `shield_service_upper(config,bound,h)` documents/test-checks a possible
mapping for actual-departure semantics:

```
shield_upper(h) = min(physical_capacity, outward(rate + burst/h))
h_min <= h <= H
```

Before enabling it, owner integration must version `SafetyInstallation` /
`InstalledAction` / `CalibratedQueue`, preserve nominal+burst+physical fields,
and change **all** of these together:

1. `CalibratedSafetyProvider.evaluate`: map at the exact observation-anchored
   candidate horizon, retain physical capacity in `QueueObservation`, bind source
   derivation and original v2 configuration digest.
2. `IndependentInstallationValidator.validate`: compare original profiles and
   exact horizon-mapped values, not nominal rate versus equivalent rate.
3. `LoadedCalibration.validate_action`: enforce both minimum and maximum horizon,
   source scope, predecessor/route map, mapped upper and unchanged lower/error.
4. `TrustedCalibration.min_service_uncertainty_bytes_per_second`: derive a bound
   that covers all installed horizons (e.g. supremum over the admitted horizon
   set), or restrict installation to one explicitly reviewed fixed horizon.
5. Receiver final checkpoint and observation provider: bind that same mapping,
   capacity boundary and horizon; neither may silently use nominal shaper rate.

Past busy-period evidence cannot guarantee that a **future** queue stays busy.
`shield_service_upper` refuses `busy-period-available` entirely. That mode needs
a future busy-domain proof plus the within-interval dynamics theorem, or a
separate service-curve-capable shield contract; the current shield is unchanged.

### Q5: raw integer clocks and canonical observation identity

New `emulation/native_qualification_causal.py` acquires v2 HTB/netem captures with
raw integer wall/monotonic nanoseconds at endpoint and individual read boundaries.
Original raw nft/tc JSON and derived seconds are retained, and replay requires the
seconds to be the exact declared projection of those integers. No old artifact
is converted to v2 or retrospectively supplied with invented integer clocks.

`native_qualification_clock.py` defines one deterministic canonical rule:
floor UTC to a microsecond; if the datetime's binary64 timestamp would be in the
future relative to raw integer ns, move one further microsecond back. The binding
retains raw wall/monotonic endpoint ns, ISO datetime, binary64 seconds, an
outward-ceiled quantization uncertainty in ns, and SHA256 of the full unmodified
raw capture. The error covers both datetime quantization and float projection;
it is not an arbitrary equality tolerance.

`scripts/native_qualification_observation.passive_causal_observation` constructs
the passive observation and detached v2 envelope from **that same** raw capture.
It uses the canonical datetime and attaches `native-capture:<sha256>` evidence.
It sets freshness/compatibility false: existing identity, feed freshness and
model admission owners must perform their checks. `causal_frames.safety_frame`
recomputes the binding/digest, checks exact datetime equality, independently
replays raw ns/counters and requires quantization uncertainty within configured
clock error. It also requires byte error to cover at least
`physical_capacity * quantization_uncertainty`; additional read-skew/accounting
errors still need their own reviewed coverage. The original v1 serialization
shape/instrument digest and exact-alignment checks remain intact.

V2 causal config explicitly records nominal HTB rate separately from physical
capacity. Raw class rate is checked against nominal; the safety observation
retains physical capacity. A detached internal validation view adapts the old
replayer's misnamed HTB `capacity` field; no raw capture, class rate, stored
measurement or actual capacity is rewritten. HTB ceil/burst source guarantees
still belong to v2 independent service evidence, not this nominal-rate check.

The bfifo collector also exposes `observation_envelope(raw_capture)` with the
same canonical clock rule. Its ARP/OSPF provider adapter remains a separate gate.
The existing frozen-v4 IPC passive observer remains unchanged: it measures a
different interval. A canonical conversion cannot make two independently
acquired observations contemporaneous, and this work does not relabel the v4
feed or fabricate its model input vector.

### Verification and authentic-capture gap

Q1/Q2 tests cover legacy refusals, explicit burst acceptance, physical-capacity
failure, minimum horizon, independent-source trust, missing/lost/idle/misordered/
tampered busy traces, future-service refusal and v2 installation refusal. Q5
tests run the actual new acquisition function with deterministic native-command
doubles through passive construction and registration **without rewriting any
captured timestamps**. Tests also cover unrelated observation times, altered
raw clocks/digests, float projection, zeroed uncertainty and distinct nominal /
physical capacities. Native feasibility now compares the same outward-rounded
IEEE inputs consumed by the shield, fixing a fractional-horizon boundary mismatch.

**Actual native-capture replay has not been completed.** No authentic retained
v2 ns capture was supplied/found, and no live acquisition was authorized during
the exclusive recovery campaign. The explicit read-only opt-in test
`test_retained_actual_native_v2_capture_without_timestamp_rewriting` skips without
parent's `NANFO_NATIVE_REPLAY_ROOT` and `NANFO_NATIVE_REPLAY_RECEIPT_SHA256`.
Parent's protected `replay-receipt.json` must reference exact `instrument` and
`raw_capture` artifacts (path/sha256/size), original `collected_at`, and separately
accepted guarantee/instrument digests. This test consumes retained bytes only;
it never starts a lab, rewrites a fixture, freshens a record or installs trust.

**Status: preparation implemented; no live lab started, no calibration installed.**
Scope is isolated Linux/FRR **software-lab** qualification. Physical RF remains
blocked by absent equipment/survey files. Parent must authorize and serialize the
actual acquisition/receiver run. The queue under study is a Linux qdisc byte
backlog, not the application FIFO used by the earlier campaign.

## Owned implementation

| File | Purpose |
|---|---|
| `emulation/native_qualification.py` | Exclusive-create nft regulator transactions, kernel TBF/bfifo command compiler, read-only raw nft/tc/ip endpoint collector, strict regulator readback comparison |
| `emulation/native_qualification_routes.py` | Exact `linkPlan()` directed egress graph, foreground/reverse/action mapping, externally measured background paths, per-link ARP/OSPF demands, old/new union, exact existing-driver mutation/compensation manifest |
| `backend/scripts/native_qualification.py` | Strict design schema, exact-rational envelope feasibility against a separately pinned `SafetyPolicy`, deterministic whole-session schedule, offline CLI |
| `backend/scripts/native_qualification_capture.py` | Replay original native JSON, counters, byte queues, drops, clocks, conservation and policing diagnostics |
| `backend/tests/unit/test_native_qualification.py` | Unprivileged adversarial/feasibility tests, including unchanged `SafetyShield` acceptance/rejection |

No public API, model weights, historical/frozen experiment files, existing
validator or existing test thresholds are changed. Generated commands are **not
executed**. The compiler never emits an installation, authenticates an attester,
or sets activation ready. Unit-test records are fixtures, never campaign captures.

## Source findings and review boundary

Research inspected:

* [nftables manual](https://netfilter.org/projects/nftables/manpage.html): netdev
  egress is before tc egress; **tc ingress redirects may bypass it**. `create`
  rejects collisions; `add table` alone does not. ARP and other ethertypes traverse
  netdev hooks. A packet accept is not an exemption from later base chains.
* [libnftables JSON schema](https://manpages.debian.org/bookworm/libnftables1/libnftables-json.5.en.html)
  for packet limits, named quotas/counters and exclusive-create transactions.
* [Linux `nft_limit.c`](https://codebrowser.dev/linux/linux/net/netfilter/nft_limit.c.html):
  spinlock-serialized packet tokens, nanosecond credit, cost `floor(1e9/p)`;
  byte bucket capacity is based on **rate + burst**, not simply the burst value,
  and byte costs are truncated. This compiler uses packet limits plus enforced
  maximum skb length to avoid silently treating nominal byte rate as exact.
* [Linux `nft_quota.c`](https://codebrowser.dev/linux/linux/net/netfilter/nft_quota.c.html):
  atomic consumed-byte increment precedes the over-quota comparison. The entire
  packet crossing the quota is dropped. Readback caps `used` at the quota;
  it is not a full offered-byte counter. Separate offered/drop counters are kept.
* [Linux `sch_fifo.c`](https://codebrowser.dev/linux/linux/net/sched/sch_fifo.c.html):
  bfifo enqueues only if `backlog + qdisc_pkt_len(skb) <= limit`.

The browsed source is revision **v6.19-rc8-185-g2687c848e578**. It is research,
**not proof about the eventual running kernel**. Attempts to fetch v6.12 raw
GitHub sources returned HTTP429. Pin and review the actual kernel build/config,
modules, nft/iproute2/FRR versions, userspace source and image digests before using
any derivation. Recheck TBF dequeue/peek/requeue and stats semantics too.

Existing `autonomous_causal.py` counts prequeue bytes without enforcing arrivals,
assumes a netem leaf under HTB, rejects unknown traffic, and blocks qdisc drops
without byte counters. `causal_frames.py` describes exact IPv4/protocol demands,
which cannot encode ARP. Its existing raw validator also rejects a route change
within a window. **Do not feed these new captures into that old frame path or
rename bfifo as netem.** The separate new collector closes the source-capture gap;
a reviewed provider adapter for this new instrument is still needed before
continuous native activation. The generic independent campaign validator accepts
network records, but does not itself reconstruct this new native stream: the
new replay gate must run first, with its report pinned by the independent reviewer.

## Enforced operating domain

Use a newly owned nine-namespace instance of the frozen graph/address plan, all
**22 directed interfaces** (11 links), including the four host egresses. Create
the dedicated table once per namespace. Each egress has six disjoint classes:

1. h1→h3, h3→h1, h2→h4, h4→h2: all IPv4 protocols between the exact address pair,
   including TCP ACKs, UDP load, ICMP probes and fragments;
2. ARP on this directed link;
3. OSPF IPv4 protocol89 on this directed link (host-pair selectors take priority).

Each class gets a maximum skb-length check, a packet token bucket and separate
offered/oversize/excess/accepted **byte and packet** counters. No control-plane
exemption bypasses regulation. Other traffic is counted and dropped; any unknown
traffic invalidates an ordinary qualification window, even if contained. IPv6,
VLANs, tunnel traffic and extra management flows are outside the initial scope.
Quota exhaustion may drop before classification: preserve its global offered and
quota-drop counts, and do not call such a window complete per-demand attribution.

On clean disposable interfaces only, `tc ... add root ... tbf` followed by
replacement of its automatically created child with explicit `bfifo limit L`
provides a real kernel byte queue and finite ceiling. An existing HTB/netem root
causes the initial add to fail. **Parent provisioning must explicitly construct
the new queue domain**; it must not rewrite shared or historical queues.
Changing this queue topology means new runtime/equivalence evidence; the frozen
model is not automatically qualified for it.

TBF is for nonzero measured queueing/load, not a guaranteed minimum service.
Finite bfifo bounds apply to its backlog in `qdisc_pkt_len` units, not total kernel
memory, socket queues, neighboring namespaces, NIC queues, or end-to-end delay.
Pin/disable GSO/GRO/TSO, offloads, size tables, segmentation changes, tc/BPF
redirects, XDP/AF_XDP, raw bypass and flowtable offload. Verify all writer
capabilities and packet paths. `meta length` uses skb bytes: establish equality
or a reviewed conservative conversion to qdisc length and departure counters.
The collector retains links/full rulesets/filter trees, but that alone does not
prove the absence of every bypass or offload. Unknown versions/options fail review.

### Arrival proof: token bucket and its real limitation

For class c, define enforced maximum length M_c, burst b_c packets and nominal
rate p_c packets/s. For the inspected packet-limit implementation:

```
k_c = floor(10^9 / p_c) ns/packet > 0
sigma_c = M_c b_c
rho_c = M_c 10^9 / k_c bytes/s
F_c(t+u) - F_c(t) <= sigma_c + rho_c u
```

The rate calculation rounds outward; `rho` can exceed `M*p`. Bounds sum across
all six classes. No empirical maximum is used. Bucket refresh/reset/replacement
inside an epoch would grant new burst credit and invalidates the proof.

F counts bytes passing the nft hook. It is **not automatically the qdisc arrival
process**: a packet can wait between the hook and enqueue while scheduling stalls.
If a reviewed hard hook-to-enqueue bound J exists, then a safe arrival curve at
the queue is `sigma + rho*(u+J)`. Measurements of J do not prove it. A finite
userspace timeout, CPU affinity, or an observed p99 cannot supply J.

The compiler returns `prequeue_delay_not_proved` if J is absent and there is no
finite-epoch quota. This catches an otherwise easy false guarantee.

### Finite-epoch alternative: no assumed hook-to-enqueue deadline

Additionally enforce an atomic **nonrenewable byte quota C_i per egress** in front
of its classes. For a freshly fenced epoch with no old in-flight packets:

```
total admitted bytes in the entire epoch <= C_i
queue arrivals in any subinterval <= C_i
```

Delayed packets still consume that same lifetime quota. This removes J from the
finite-epoch arrival proof. It permits positive offered and delivered traffic;
it is not an indefinite-service promise. Never reset, clone, replace or replenish
the quota within a capture group. Quota counts offered bytes before class
policing, so rejected traffic may consume the allowance: conservative and visible.
Bound epoch duration/total offered traffic so the kernel atomic consumed counter
cannot wrap. Fresh provisioning and capability fencing, not a readback of capped
`used`, prove no reset. Cross-epoch namespace/queue/in-flight reuse is forbidden.

The ARP/OSPF budget must cover the entire preregistered group. Exhausting it may
break adjacency/reachability; retain the failure and end the group rather than
silently restoring credit. The epoch protocol must provision instrumentation
before allowing traffic; pre-instrument packets cannot be wished away.

## Exact safety obligations, fixed policy and nonvacuity

Let H be the certificate horizon, h_min the minimum campaign measurement window,
q_i the observed byte backlog, delta the maximum accepted sensor span plus clock
uncertainty, and eta_i the reviewed sensor/accounting error. Service lower is
**S_i=0**. No HTB/TBF configured rate or measured departure minimum substitutes.

For the bounded-prequeue-delay variant the conservative compiler uses:

```
a_i = rho_i + (sigma_i + rho_i J) / h_min
E_i = eta_i + sigma_i + rho_i*(delta + J)
```

It deliberately covers the burst both in the fixed arrival-rate contract and in
the observation uncertainty. This is conservative, not a tight fit. For the
finite-epoch variant:

```
a_i = C_i / h_min
E_i = eta_i
```

The existing validator separately checks arrivals `<= a_i*dt`, so a token-bucket
burst cannot be hidden only in E. All acquired windows must satisfy
`h_min <= dt <= H`; the compiler currently supports a fixed certificate H. For
finite epochs, the full quota conservatively covers prequeue delay and growth
during non-atomic observation; eta must still bound stats/accounting discrepancy.

Apply the **unchanged** model/policy:

```
U_i = q_i + a_i H + E_i
D = 1/2 sum_i(U_i^2 - q_i^2)
q_i <= Q, U_i <= Q, D <= B
```

The code does not replace U by `min(U,L)`. `SafetyShield` does not perform that
clamp, and the independent validator must agree with the actual installed model.
It checks exact rational arithmetic and rounds serialized upper bounds outward.
Policy Q/B are read from a **separately pinned existing/reviewed policy file**;
the checker does not invent or raise them from data. Current zero-budget B=0
remains infeasible for nonzero arrivals/errors with S=0. That failure stays a failure.

A **new explicitly reviewed scoped positive B** is permitted by the existing
policy schema/model, but is not inherited authorization from this document.
Before acquisition, review B together with the full egress count, Q, quota,
horizon, uncertainty, minimum throughput and intended scope. Never tune B after
train or holdout. This proves bounded positive one-step drift, not stability.

Concrete arithmetic-only witness used in tests (not an installed or reviewed
policy): one queue, C=65536B, H=h_min=1s, eta=2048B, L=1048576B, Q=262144B,
B=8589934592B². q=0 gives U=67584B and D=2283798528B², so it passes. With the
**same B**, q=131072B gives D=11142168576B² and fails; q=250000B fails Q too.
The test also feeds those exact bounds to the unchanged `SafetyShield`.
For the real 22-egress vector recompute the sum; the single-queue witness is not
permission to reuse its B or claim the full graph passes.

### Is a queue cap enough?

`q<=L` by bfifo is a useful containment fact, but if `L<=Q`, it already proves
that backlog ceiling for every route (potentially by dropping all offered load).
Setting E=L and a generous B adds no evidence of action safety or improvement.
The checker therefore reports whether U<L and blocks an all-cap-only result.
The stronger finite-epoch bound U<L can reject high-backlog/oversized-envelope
changes **before** the cap is reached. Negative controls must demonstrate rejection
with the fixed policy. This still does not show that route1 is safer than route0:
identical worst-case per-egress bounds may admit both or neither. Positive
hysteresis can correctly block switching when there is no proven improvement.
Do not disable it to manufacture a routing advantage.

## Sensor, departures and timing obligations

Raw collection records each command's original JSON, parsed value, wall and
monotonic start/end. Replay rejects raw/normalized divergence, duplicates, missing
reads, changed regulators, foreign nft hooks/tc filters, queue-tree/limit/rate
mismatch, counter resets, backwards/changed clocks and excessive total spans.
It checks arrival diagnostics and byte conservation independently of producer flags.

At each egress:

```
q1 - q0 = admitted_arrivals - departed_bytes - dropped_bytes +/- eta
```

Qdisc `drops` is a packet count, not a byte count. Any change blocks a successful
conservation window until a separately reviewed byte-drop instrument is provided.
Regulator drops are counted separately **before** the qdisc accepted-byte counter;
never subtract them again as qdisc drops. Multi-counter nft dumps are not atomic;
offered/class/drop partitions need packet-trace reconciliation or a reviewed skew
bound, not exact equality asserted on sequential reads. Quota caps plus bounded
read spans supply finite conservative error; making eta comparable to L can
destroy nonvacuity and must be reported, not hidden.

TBF also bursts: `departures <= configured_rate * dt` is not a general guarantee.
For h>=h_min, a source-reviewed token-bucket upper including burst/packetization
and observation skew is needed for the generic validator's service-upper and
capacity checks. Its logical capacity field must honestly identify the reviewed
upper, not silently equate it to the nominal shaper rate. If exact observed
capacity binding forbids that representation, installation remains blocked.
Fresh/nonrenewable total-arrival quota plus finite initial backlog provides a
separate finite departure-volume ceiling, but does not change frozen field semantics.

The kernel's userspace command completion time has **no hard finite guarantee**
from ordinary Linux configuration here. Existing receiver final-checkpoint checks
are necessary but a process can be descheduled after the check and before a
netlink effect. A command timeout is not a proof the effect did not happen later.
Therefore distinguish:

* queue containment/finite-volume bound: independent of scheduler service;
* retrospective measured route/latency qualification: can pass an observed bound;
* future hard dispatch/transition deadline: **unproved**, activation stays blocked
  if the current trust contract requires it. Parent needs an enforceable kernel
  lease/fence-at-mutation implementation or a separately justified hard scheduling
  domain; software watchdog measurements alone are insufficient.

On a timing/read/ownership failure stop new dispatch, retain all raw evidence,
mark any possibly applied operation uncertain and reconcile/compensate through
the existing durable receiver. This is fail-closed **authorization**, not an
assertion that an already submitted kernel change was cancelled atomically.

## Native transitions and exclusive handoff

Foreground action0:
`h1 -> access1 -> dist1 -> access2 -> h3`; action1 replaces dist1 with dist2.
Reverse traffic traverses the reversed route. The native driver uses exact /32
source/destination selectors, tables/priorities **19110 and 19111**, per-hop static
onlink routes, and route-add then rule-add order. `mutation_manifest(action)` calls
the existing pure `resources/command` implementation and enumerates every partial
apply prefix plus reverse compensation; it never runs those commands.

The driver `prepare` requires empty reserved tables. It is not a general
arbitrary-active-action replacement API: test 0→1 through apply, 1→0 through
receiver compensation, and measure 0→0/1→1 holds without a second prepare over
existing resources. Capture every operation/readback, both kernel policy tables,
all router route/rule dumps, foreground/reverse path and native packet traversal.
Background h2↔h4 must come from actual `routePath` readback and remain unchanged.

All old/new path egresses belong to the arrival union. Partial rule states can
fall back to OSPF or form paths outside that union: enumerate every prefix using
actual route resolution and reject the campaign if it leaves the reviewed union,
loops, duplicates packets or changes background routing. Endpoint-only stable
paths cannot prove a safe transition. Static link-local ARP/OSPF demands use one
directed egress each, with their own source/destination identity in execution
binding. They are not remote routed host demands.

Handoff sequence for parent:

1. Hold the host-wide experiment serialization lease. Allocate only new owned
   namespaces, private journals/stores, mounts, image identity and output directory.
2. Stop and join old experiment/manual mailbox/autonomous controllers and workload
   writers; retain owner processes that keep namespaces alive. Prove their death
   by PID/start-time identity, not just an asserted `stopped` flag. Keep FRR daemons
   as declared OSPF/main-table writers; receiver exclusively owns reserved tables.
3. Pin each PID/start_ticks/netns inode, exact kernel/interface inventory and source
   hashes. Acquire `AttachedFRRNetwork`'s shared `.autonomous-frr.lock` in the same
   protected directory. Alternate lock paths are not exclusion.
4. Advisory flock alone does not stop privileged rogue writers. Remove/fence
   CAP_NET_ADMIN from old controllers, close old namespace handles, restrict
   `nsenter`/receiver access and prevent the launcher from mutating after handoff.
   If that capability boundary cannot be established, mark ownership unproved.
5. Attach raw instrumentation and measured feed before workload starts. Preserve
   fresh epoch state. Parent runs acquisition serially; receiver is sole route
   mutator and compensator. The raw collector is read-only.
6. Test second-controller denial, inode/PID reuse, owner loss, STOP, expiry,
   revocation, partial operation interruption and restart reconciliation. Retain
   exact before/after table/path evidence. Release descriptors/leases only after
   owned state is restored or explicitly recorded unresolved.

## Preregistered measured campaign

Before any measurement, independently pin the **complete** protocol, configuration,
native design, fixed policy, raw collector/replayer source digests, source/image
manifest, binding, native action map, traffic recipe, acceptance conditions and
group schedule. Use the existing `AcquisitionProtocol`, `NetworkQualificationConfig`,
`InstrumentExport`, `RawCapture`, `MeasurementAttestation`, and `CampaignManifest`.
The application-FIFO `LocalAcquisitionRecipe` is **not** the native recipe; omit
that optional field and retain the native recipe as independently pinned evidence.

Proposed reserved seeds are 91001/91002/91003 (train) and 92001/92002/92003
(holdout). `preregistered_schedule()` creates six fresh whole-session groups,
eight windows each: (0→0, 0→1, 1→1, 1→0) under sustained traffic, then the same
under admitted bursts. Parent must verify disjointness against historical and
concurrent reserved seeds **before pinning**; these numbers are a proposal, not a
claim that that comparison has occurred. Nonoverlapping windows/groups, fresh
namespace/quota state per group, all planned sample IDs and all failed attempts
are mandatory. No reseeding, dropping failed windows or train-to-holdout leakage.

Before registration choose a positive foreground/background UDP load recipe,
packet sizes/rates/durations, TCP/probe behavior if used, link-local budget and
minimum delivered-byte threshold. Zero delivered foreground/background bytes
fails the ordinary groups. Preserve packet sequence IDs and sender/receiver logs
to measure delivery independently of qdisc departures. Do not use load suppression
as evidence of generalized benefit. For each window retain:

* actual raw nft/ip/tc reads before/after, nft metadata, all controller/timing logs;
* packet captures at each scoped directed link, capture loss counters and native
  sender/receiver sequence logs; missing trace records invalidate trace-based claims;
* action request/dispatch/applied/transition-complete timestamps, all partial native
  rule states, routing/neighbor/FRR adjacency dumps and receiver durable journal;
* nonzero offered/admitted/delivered traffic, regulator/queue drops, conservation,
  queues, delivery latency and read-skew intervals with units;
* native source artifacts by exact SHA256, including failures and cleanup ledger.

Additional separately preregistered **negative-control** sessions: above-envelope
burst, oversize skb, unknown ethertype/flow, quota exhaustion, qdisc overflow,
foreign rules/filter, altered queue limit, counter reset, clock jump, stale read,
invalid route union, concurrent-controller attempt and expired/STOP dispatch.
Expected outcome is containment/refusal with retained evidence. Do not mix these
intentional failures into success calibration and then omit them to pass the
generic validator's all-record acceptance: retain a separately pinned rejection
campaign and report both denominators.

Metrics: all per-action and directed-transition coverage in both splits,
all-record generic validator pass for ordinary groups; all planned negative-control
refusals; foreground/background minimum delivered bytes; per-group measured
latency/delivery/drop/queue summaries; native apply/readback/restore success;
ownership/expiry fault outcomes. Performance comparison should pair frozen OSPF
baseline, fixed action0/action1 and authorized bounded receiver policy using fresh
matched schedules. A successful queue certificate alone cannot supply a benefit
metric. Preregister any benefit margin before acquisition; retain existing model
qualification criteria verbatim rather than inventing easier replacement gates.

### Independent review and installation

The reviewer must independently reconstruct units, byte accounting, transitions,
sensor uncertainty and metrics from raw sources; verify the math and source/runtime
equivalence; rerun native replay and `verify_network_campaign`; challenge the
negative controls; and decide which assumptions are actually enforced. Bind all
eight existing `BoundGuarantee` derivation references to reviewed artifacts:
arrival, service, interval dynamics, transitions/delay, attribution, sensor error,
capacity/scheduler and environment. A self-produced successful report is not trust.

Local attestation must explicitly say **isolated software emulation** and identify
the real software acquisition/reviewer process. The current attestation schema
offers `authenticated-instrument` or `operator-attested`; use the former only with
an actually authenticated instrument identity and protected external receipt.
Do not invent a human signer, equipment certificate or an operator identity.
Trusted attestation/guarantee/runtime hashes come from separate protected review,
not fields supplied by the dossier generator. No local attestation proves RF.

Only after all requirements are met may parent use the existing
`load_trusted_calibration` → `IndependentInstallationValidator` → receiver path.
No synthetic installation, ignored physical/equivalence gate, shortened demand
list, missing reverse/control traffic or `physical_qualified=true` shortcut.

## Offline use and remaining gates

From `backend/` (no network commands are executed):

```bash
poetry run python -m scripts.native_qualification --schema
poetry run python -m scripts.native_qualification --root /absolute/protected/design-root --design design.json --design-sha256 <exact-byte-sha256> --policy policy.json --policy-sha256 <independently-pinned-sha256> --queues design-vector.json
poetry run pytest tests/unit/test_native_qualification.py tests/unit/test_autonomous_causal.py --no-cov -q
poetry run python -m scripts.native_qualification_capture --root /absolute/capture-root --design design.json --design-sha256 <pin> --before before.json --before-sha256 <pin> --after after.json --after-sha256 <pin>
```

Queue-vector inputs to the offline feasibility checker are **design inputs unless
separately reconstructed from authentic raw captures**. Stdout contains command
plans and obligations; exit0 means arithmetic feasibility only. The compiler
emits no deployment artifacts or trust receipts. Parent can call
`capture_endpoint(attached_network, design.model_dump(mode="json"))` after
authorized handoff and persist every returned endpoint before replay. It does
not start a lab or run probes.

| Gate | Current result |
|---|---|
| Packet bucket/quota/byte-queue compiler and raw source collector | Implemented; unprivileged verification only |
| Fixed-policy positive-traffic feasibility and unsafe-state rejection | Tested arithmetic, including unchanged shield; not full-graph qualification |
| Actual nft/tc syntax/readback and source equivalence in selected kernel | Awaiting parent serialized lab; strict JSON normalization may require reviewed version adapter |
| Full-graph fixed Q/B/error/traffic/horizon review and external preregistration | Pending; no reviewed policy fabricated |
| Native measurements, independent raw reconstruction and benefit comparison | Pending actual acquisition |
| Full control-traffic provider-frame integration | Blocked in old IPv4/netem frame path; needs reviewed new adapter |
| Hard native transition completion deadline | Not proved by ordinary Linux/timeout configuration |
| Software-lab trusted calibration/receiver activation | False; existing trust/installation gates remain |
| Physical RF | Externally blocked; outside this campaign |

Parent's next authorized action is one serialized disposable native instrument
compatibility/preflight run, retaining failures, followed by the externally pinned
campaign only after the unresolved mathematical and integration gates are reviewed.

### Local verification record

Preparation ran the native tests plus existing causal, independent-validation,
FRR and final-checkpoint regressions. The initial test run caught a test fixture
that incorrectly connected h2 directly to dist1; the exact-graph validator
rejected it, and the fixture was corrected to use access1. No native result was
generated by these tests. Scoped Ruff and repository tracked-diff whitespace
checks passed. Final test totals are reported in the handoff response.
