# Finite-Buffer Fluid v1

## Units and State

All quantities of traffic/queues are **bytes**, including fractional fluid bytes.
Mbps is decimal megabits/second. For tick length `dt` milliseconds:

```text
offered_f(t) = demand_mbps_f(t) * dt * 125
capacity_l(t) = capacity_mbps_l * dt * 125
```

Each declared directed link has one finite shared buffer, a per-flow queue and a
separate unattributed initial-background queue. Each flow queue stores `(B,M)`:
remaining bytes and the sum of source-injection timestamps weighted by those bytes
(`byte*ms`). This represents a perfectly mixed fluid population, not FIFO packets.
It preserves aggregate residence moments through admission, service and propagation.
No traffic uses undeclared routing, no shortest path is guessed, and no random hidden
demand/background is generated. Seed is provenance only in v1.

## Tick Ordering

For tick `t`, start time `t*dt`, end time `(t+1)*dt`:

1. Release pipeline entries due at the start to their declared next link (or final
   destination). Add source demand, injected at the start boundary.
2. For every link in stable ID order, admit simultaneous arrivals proportionally
   into currently free buffer space **before** servicing that tick. Reject overflow.
   Existing queued bytes are not displaced; a zero-sized buffer rejects all arrivals.
3. Serve the admitted/old queue population proportionally across every flow and the
   initial background. All links see their tick-start arrivals, never another link's
   same-tick service. Service completes at the tick end boundary.
4. Schedule service into propagation at due tick `t+1+ceil(delay_ms/dt)`. At the end
   boundary, release due final-destination/background deliveries for horizon metrics.
   Due intermediate-hop entries remain in the pipeline until the next tick starts.
5. Recompute/check conservation and append one trace record. Stop at exactly the
   declared horizon without an implicit drain interval; residual queue/inflight is
   reported, not counted as loss or delivery.

Admission for link free space `F` and incoming total `A` is
`a=min(1,max(0,F)/A)` (1 when `A=0`). Admit `a*B`, `a*M`; drop `(1-a)*B`.
For total queued bytes `Q`, service fraction is `s=min(1,C/Q)` (0 when `Q=0`).
Each `(B,M)` contributes `(s*B,s*M)` to propagation, retaining `((1-s)*B,(1-s)*M)`.
This is stable deterministic proportional service and admission, not max-min fairness,
strict priority, TCP congestion control or FIFO scheduling.

Background starts with each link's `initial_queue_bytes`, shares buffer/service, and
exits after that link's propagation. It is never assigned to a configured flow. Its
own `initial=delivered+queued+inflight` baseline is reported per link, separately
from source offered demand and all flow goodput/loss/latency calculations.

## Metrics and Objectives

On delivery of `(B,M)` at modeled time `T`, add `B*T-M` to the flow's cumulative
delivered residence moment. `latency_ms=sum(delivered residence moments)/delivered bytes`.
This is actual end-to-end residence **within the mixed-fluid approximation**, including
every modeled queue/service tick and tick-rounded propagation. It is not a sum of
instantaneous `queue/capacity` estimates, measured RTT, packet percentiles or the
latency of bytes that remain queued/dropped. Delivery-conditioned latency is censored
by finite duration; use delivery ratio and residual bytes alongside it.

```text
loss_pct = 100 * dropped / offered             (null without offered)
delivery_ratio = delivered / offered           (null without offered)
throughput_mbps = 8 * delivered / (elapsed_ms * 1000)
latency_ms = delivered_residence_byte_ms / delivered  (null without delivered)
link utilization = served_bytes / capacity_bytes_per_tick
```

Flow histories are cumulative at each boundary; link service/arrival/drop histories
are per tick. `risk_gate=passed` only when horizon complete and loss <= maximum,
delivered-weighted latency <= maximum, goodput >= minimum. Missing objective metrics
block; no risk score or default successful gate is fabricated. Computation still
completes if objectives fail. Objectives do not bound physical-network risk.

## Conservation and Numerical Limits

Every tick and checkpoint verifies per flow:

```text
offered = delivered + dropped + queued + inflight
queued = sum(its per-link queues)
inflight = sum(its pipeline entries)
```

Background verifies its independent initial baseline and pipeline sum. All inputs
must be finite. Python IEEE-754 double arithmetic uses fixed sorted iteration order,
with comparison tolerance `rel_tol=1e-10`, `abs_tol=1e-6 bytes`. No rounding-to-integer
or forced conservation residual correction hides numerical errors. Values below zero
beyond tolerance reject the checkpoint. Hashes are SHA256 of canonical sorted compact
JSON with no NaN/Infinity. Checkpoints include model/input identity and their own digest;
changed input, broken hash, invalid route/buffer/pipeline or conservation reject.
These hashes detect accidental corruption, not malicious trusted-database rewriting.

Bounded batches deep-copy state and preserve queues, moments, pipelines, counters and
history. No state depends on worker batch size, lease, pause duration or wall clock.
Canonical input sorts links/flows by ID while preserving path/demand order. The output
digest excludes only its own hash field and all operational timestamps.

Coarse-tick limitations are intentional: burst admission occurs before service,
minimum service residence is one tick per hop, propagation rounds upward, queues are
perfectly mixed rather than FIFO, and no packetization/retransmission/ACK/routing
convergence/wireless contention is modeled. Smaller tick choices change the model,
its input hash and workload basis; they are not interchangeable comparisons.
