# Measured Experiment Transport

ADR-011/013/014. No backend, API, manual mailbox, torch or training runtime is added
to the lab. Operator-owned disposable containers must not share the lab slot.
Do not delete a manual `.journal.json` to permit experiments. Reconcile manual
control first; an existing journal deliberately blocks experiment startup.

## Operator Lifecycle

From the repository root:

```bash
python emulation/control.py build
python emulation/control.py experiment-start --mode sdn
python -m emulation.experiment_smoke --episodes 2 --steps 2 --window 5
```

Startup explicitly passes `--experiment` to the standalone runner, disables
manual control and waits up to 90 seconds for the experiment socket. The named
container is `nanfo-experiment`, network mode is `none`, and no port is exposed.
The fixed client command for the separate AI environment is:

```bash
docker exec -i nanfo-experiment python -m emulation.experiment_client
```

Supply one JSON document on stdin, close stdin, and consume one JSON document on
stdout. Diagnostics are not mixed into the response. The client connects only
to `/run/nanfo/experiment.sock` (0600). Requests are limited to 4096 bytes;
responses to 1 MiB; client timeout is 60 seconds; request watchdog is 45 seconds;
idle owner watchdog is 300 seconds. No user-specified socket, path, executable,
interface or shell command is accepted. Duplicate JSON keys and nonfinite
numbers are rejected. A lost response is not replay-safe: stop the owner rather
than retrying a transition.

There is no successful-response replay cache. Reusing a cached step request,
including its identical action, is rejected without another measurement or
mutation. Reset has no caller request ID, so it must never be retried after an
ambiguous transport failure (a completed/truncated episode allows a fresh reset).
Keep the returned episode identity and latest acknowledged index for close.

`close` verifies routing cleanup and ends the server; the container automatically
removes itself after namespace/process teardown. For emergency operator shutdown:

```bash
python emulation/control.py experiment-stop
```

Use `--mode ospf` on startup and smoke for the real FRR baseline. The same client
is used, but mode cannot change during a server lifetime. FRR uses separate L3
subnets, bandwidth/index costs and one next hop; both flows follow kernel OSPF
routes. Requested actions are recorded but ignored in OSPF mode, never used to
pin a route. Observation `previous_action` is the actual read-back foreground
route. Evidence includes kernel next hops and the explicit comparison limitations.
Passive OSPF path changes are detected by actual kernel readback and reset route
age; they are never attributed to the ignored requested action. If the path
differs at the end of a window, the transition truncates. Congestion can drop
OSPF control packets as well as workload packets; the 1s hello/10s dead policy
can therefore reconverge under sustained saturation. This is a baseline failure
outcome, not a reason to pin routes or silently accept a mixed-path window.
The dead interval was raised from 4s after two live saturated runs detected
mid-window reconvergence; both rejected runs remain in the append-only traces.

## Exact Requests

All ten fields are required; unknown fields are rejected. Default measurement
window in the smoke CLI is 5 seconds. Wire callers supply the value explicitly.

Reset:

```json
{"version":1,"command":"reset","episode_id":null,"step_index":null,"seed":1000,"scenario":"path0","action":null,"mode":"sdn","window_seconds":5,"episode_steps":2}
```

Reset produces an actual initial measurement at index 0, not a decision. Save
its server-generated canonical UUID as `episode_id`. Step 1:

```json
{"version":1,"command":"step","episode_id":"UUID-FROM-RESET","step_index":1,"seed":null,"scenario":null,"action":1,"mode":"sdn","window_seconds":5,"episode_steps":2}
```

Use indices 1 through `episode_steps` once each. `seed`/`scenario` may be null on
step/close or repeat the reset values. Window and episode length must repeat
exactly. Action 0 is access1/dist1/access2; action 1 is access1/dist2/access2.
Holding the current route verifies it but never reinstalls it. Active episodes
cannot be reset; finish or close. A terminated/truncated episode can be reset.

Close after index 2:

```json
{"version":1,"command":"close","episode_id":"UUID-FROM-RESET","step_index":2,"seed":null,"scenario":null,"action":null,"mode":"sdn","window_seconds":5,"episode_steps":2}
```

Close also permits null identity/index before the first reset. It returns
`data:{closed:true,cleanup_verified:true,episode_id:string|null}`.

Windows are finite numbers in 2..10, decisions integers in 2..64, seeds integers
in 0..2147483647, actions integers 0/1 (booleans are not integers). Scenarios:
`low`, `path0`, `path1`, `alternating`, `burst`, `overload`. Each seeded schedule
materializes `episode_steps + 1` phases before reset measurement. The seed changes
offered inputs, never measured outputs. Split ranges belong to AI artifacts:
training 1000+, validation 2000+, test 3000+; the caller must keep them disjoint.

## Verified Drain V4 (ADR-014)

This release supersedes **all** fixed-250ms drain descriptions below. All modes
now emit `environment_spec.version:4`. Matched and OSPF have exactly the same
spec and hash; SDN retains its distinct workload/observation semantics, but uses
the same new drain implementation. No old-spec compatibility path is provided.
Historical V2/V3 output is retained unchanged as cutoff delivery-deficit evidence.
The outer wire version remains 1. No actor observation fields are added or removed.

Exact new/replaced semantic fields (also returned in every raw reset/step):

```json
{
  "version": 4,
  "drain_version": "post-sender-termination-verified-leaf-queues-v4",
  "drain_max_seconds": 3.0,
  "drain_poll_interval_seconds": 0.08,
  "drain_empty_observations": 2,
  "drain_queue_scope": "all topology link endpoints, both directions, including hosts and alternate paths; single leaf netem per interface",
  "drain_completion": "all senders exited; receivers alive; two consecutive complete zero-byte/zero-packet queue sweeps separated by at least drain_poll_interval_seconds; completed within drain_max_seconds",
  "drain_timeout": "truncate with measurement_complete=false; retain final endpoint totals and partial queue evidence; no valid loss/goodput outcome",
  "late_received_packets": "unavailable (null per flow); workers publish final totals only, no drain-begin streaming counter; never inferred from queue backlog",
  "goodput_denominator": "actual foreground sender duration; delivered numerator includes service during control and verified drain",
  "latency_measurement": "foreground ICMP RTT during load; not UDP RTT"
}
```

`drain_seconds` is removed. Unchanged matched schedule/control version strings
remain `seeded-stationary-capacity-v3` and
`source-specific-linux-policy-routing-and-end-readback-v3`: only measurement
drain semantics changed, not OSPF costs, topology, shaping, demand or route policy.

After both UDP senders exit successfully, record
`senders_stopped_monotonic_seconds`, signal ping to stop, and begin queue drain
with both receivers alive. Every one of the topology's **22 egress interfaces**
is checked, including all host-facing and alternate/core-path links. Each read
must have exactly one valid leaf netem with zero bytes AND packets for an empty
sweep. Any nonempty sweep resets the consecutive-empty count. Missing/invalid
queues or receiver exit fail closed. Reads and sleeps share the 3-second deadline;
a read timeout kills its owned `tc` child promptly. Scheduler/child-cleanup
overrun is recorded with the actual end time and always truncates, never reported
as within-cap verification. Receiver shutdown/final-counter collection occurs
after the drain interval and can add up to a socket timeout of delivery service.

Evidence fields:

- `drain_begin`, `drain_end`: monotonic seconds bounding actual queue verification.
- `drain_duration_seconds`: actual end minus begin, not a nominal duration.
- `drain_status`: `verified_empty`, `timeout`, or `unverified`.
- `drain_error`: null on success; bounded failure reason otherwise.
- `drain_queue_interfaces`: exact ordered interface inventory.
- `drain_sweeps`: number of completed or cap-interrupted sweeps.
- `queue_begin`, `queue_end`: first and last (possibly partial on failure) sweep
  maps, keyed by interface; each has `backlog_bytes`, `backlog_packets`,
  `monotonic_seconds`, and `raw_leaf_qdiscs` from actual `tc -s -j` output.
- `drain_empty_observations`: consecutive empty sweep evidence, each with
  `start`, `end`, and complete `queues`; exactly two on success, separated by at
  least 80ms from first end to second start. Queue reads are sequential, not a
  claim of an atomic simultaneous topology snapshot.
- `late_received_packets`: `[null,null]`, foreground then background. The field
  `late_received_unavailable_reason` is exactly
  `workers publish final totals only; no drain-begin counter`. No invented late
  count, packet-counter stability claim, or queue-to-UDP attribution is made.

Both raw UDP final totals are retained even if drain verification fails. Such a
window is truncated, `measurement_complete:false`, with loss/goodput unset, not
a valid zero-loss outcome. Successful windows retain all transition/service
delivery and all undelivered packets in the final loss fraction. Goodput and
actual offered rate both use actual sender lifetime as denominator, not the
requested post-control window or drain duration. A separate full-departure-period
analysis may use raw sender start through receiver finish, but must apply the same
definition to both modes and must not discard the original delivery/loss counts.
Latency stays labeled **ICMP RTT**; no UDP echo RTT was added.

The smoke verifier checks executing spec/source hashes against workspace sources,
actual Docker image identity, complete initial and decision observations, and raw
two-empty-sweep evidence. Release validation and exact pinned identities:
[DRAIN-V4-VALIDATION.md](DRAIN-V4-VALIDATION.md).

## Matched V3 (ADR-013)

The version labels in this foundation section are historical; the V4 drain
section above overrides them. Workload and routing semantics remain unchanged.

This section supersedes the historical OSPF-versus-SDN comparison and V2 workload
description below for `matched` and `ospf` only. `sdn` retains the V2 schedule and
observation semantics. All previous artifacts remain historical; source hashes
change and stale checkpoints must not be treated as compatible.

Both new modes instantiate the same `OSPFNetwork`: actual zebra/ospfd processes,
graph, /30 addressing, interface names, nominal costs, single-next-hop policy,
queues, foreground h1->h3 and background h2->h4. Background follows actual OSPF
in both modes. `ospf` ignores requested actions; `matched` installs only exact
h1/h3 source/destination /32 rules in both directions. Tables/priorities 19110
and 19111 must be empty before acquisition. Every router on the full explicit
path receives its next hop, including the destination access router. Main-table
OSPF routes are never replaced. Hold verifies without reinstalling. Change uses
break-before-make and counts traffic in the gap. Cleanup removes exact owned
rules/routes, refuses foreign entries, verifies empty ownership and restoration
of original foreground/background paths. No broad rule or route flush exists.

`routePath` walks actual `ip route get DEST from SOURCE iif INGRESS` results
(source host omits iif). Installation/end gates verify both foreground directions
and unchanged background paths. Concurrent real foreground ICMP and unique UDP
receiver counts provide probe/delivery evidence, not a computed SPF substitute.

Only `low`, `path0`, `path1` are accepted in V3. Balance `path0`/`path1` in the
caller curriculum. Each episode samples foreground uniform(5.8,6.2) Mbps and
background uniform(1.8,2.2) Mbps once, rounded to 3 decimals. The same seed has
exactly the same schedule across methods. `path0` degrades path 0, not selects it:
capacities are `[2,20]`; `path1` uses `[20,2]`; `low` uses `[20,20]`. Both directions
of both inter-router links on a path use that rate/ceil. Existing owned HTB classes
are changed before reset measurement only. Every window verifies actual class
rate/ceil at start and end; held windows do not reconfigure queues. Nominal link
costs stay frozen before this exogenous shaping. OSPF is deliberately not told
about effective capacity degradation. This benchmark is against static nominal
OSPF costs, NOT capacity-aware OSPF, ECMP, or every possible routing baseline.

Exact contract delta, outer request/response version still **1**:

- Request/data `mode` additionally accepts `matched`; V3 rejects dynamic scenarios.
- Observation adds required `path_capacity_mbps`: two positive read-back Mbps
  values, or nullable elements on failed acquisition. No other observation field
  changes. Normalize these by nominal 20 Mbps in the AI feature contract.
- `path_utilization` uses each path's actual read-back shaped capacity, not 20
  Mbps. It still includes all traffic/protocol overhead and counter intervals.
- `evidence.environment_spec.version` is **3**, name
  `nanfo-matched-stationary-routing`; both modes have identical spec/hash. Added
  spec keys: `modes`, `scenarios`, `capacity_policy`, `demand_policy`,
  `background_policy`, `ospf_cost_policy`, `capacity_observation`, `route_policy`.
  Existing schedule/control/observability descriptions are replaced for V3.
- `evidence.phase` adds `path_capacity_mbps`; phase index still advances but
  exogenous demand/capacity do not. `workload_advanced_before_action` is always
  false in V3; other `phase_relationship` keys retain their types/meaning.
- Evidence adds `capacity_readback` and `capacity_readback_end`: eight rows with
  `node`, `interface`, `port_no`, `capacity_mbps`, parsed `classes`, and raw `tc`
  text. Fields can be absent when failure precedes acquisition.
- Matched `route`/`route_end` contain `changed`, `path`, `actual_action`, `policy`,
  `strategy`, and `readback:{owned,paths}`. `owned` is keyed by `node:table` with
  actual `rules`/`routes`; `paths` contains all four h1/h3 and h2/h4 directions.
- `source_files` adds `matched.py`. Existing source/spec canonical SHA256 and
  actual-image provenance rules remain unchanged. Historical V2 artifacts are
  preserved, not silently migrated. No emulation reward function is added.

Live validation, frozen hashes, readiness evidence and ready-to-run commands:
[MATCHED-VALIDATION.md](MATCHED-VALIDATION.md).

## Exact Responses

Envelope: `{version:1,ok:bool,error:string|null,data:object|null}`.
Protocol rejection has `ok:false,data:null` and causes no transition. A workload
failure returns `ok:true` with `data.truncated:true` and `evidence.error`; it is
not a valid training transition. Uncertain cleanup shuts down the owner.

Reset/step data fields:
`episode_id`, `step_index`, `mode`, `seed`, `scenario`, `terminated`, `truncated`,
`observation`, `evidence`.

Observation fields and units:

| Field | Meaning |
| --- | --- |
| `path_utilization` | Two fractions, busiest egress direction of each path's four inter-switch ports |
| `path_queue_packets` | Two peak sampled leaf-netem queue lengths; no HTB double counting |
| `latency_ms` | Actual foreground ICMP mean RTT during load |
| `loss_fraction` | 1 minus unique foreground UDP receiver packets / actual sender packets |
| `goodput_mbps` | Actual foreground received payload bits / sender duration / 1e6 |
| `offered_mbps` | Seeded foreground target rate |
| `actual_offered_mbps` | Required nullable field: validated foreground sent payload bits / actual sender duration / 1e6 |
| `background_mbps` | Seeded background target rate |
| `previous_action` | Current verified/read-back route, 0 or 1 |
| `seconds_since_change` | Monotonic elapsed time since actual route change |

Unavailable metrics are null, never invented zeros. Missing/malformed probe evidence,
incomplete path counters or queue samples truncate. A valid complete window with
positive ping sent count and zero replies is a measured service outage, not a
missing instrument: RTT remains null, `service_outage:true`,
`latency_censored:true`, `latency_timeout_ms:1000` in evidence. The configured
timeout is a censoring/penalty reference, not a measured RTT (ping ends when load
ends, so its last probes can be administratively censored earlier). Valid UDP
counts are still mandatory, and zero UDP delivery must not be inferred from ping.
Zero loss is valid only with actual
positive sender counts; zero delivered UDP bytes is measured zero, not a missing
counter. The generator must achieve its target rate within 20% or truncate.
Reward delivered/offered ratio must use `goodput_mbps / actual_offered_mbps`, not
the configured target rate. Both rates use exactly the same foreground sender
duration, so the ratio equals received bytes / actually sent bytes.

## Environment Spec V2

Outer requests/responses remain `version:1`. The observation extension above is
required; old checkpoints/feature contracts must not silently accept this change.
Each reset/step, including truncated responses, includes:

- `environment_spec`: constant semantic fields with integer `version:2`, name
  `nanfo-sampled-routing-pomdp`, schedule/control/drain versions, interval meanings,
  timeout/tolerance values, `source_files` filename-to-SHA256 map and `source_sha256`.
- `spec_hash`: SHA256 of ASCII JSON of the whole spec with sorted keys, compact
  separators and nonfinite values forbidden. No episode identity/seed is hashed.
- `provenance:{source_sha256,lab_image_id}`: digest of executing source files and
  actual Docker image ID supplied by operator `control.py`. Direct runner starts
  without that operator metadata report null image ID, never an invented hash.
- `phase_relationship:{action_observation_phase_index,measurement_phase_index,
  workload_advanced_before_action,state_and_reward_share_measurement}`. At reset:
  `{null,0,false,true}`; at step k: `{k-1,k,true,true}`. `phase` remains the current
  measured workload, not a future actor input.
- `measurement_complete`: true only after all interval/counter/probe/queue,
  achieved-rate, route readback and applicable cleanup gates pass; false on failure.
- `service_outage`, `latency_censored`: booleans after validated measurements,
  null when unavailable; `latency_timeout_ms` is 1000 for an outage, otherwise null.
- `control_start_monotonic_seconds`, `post_control_interval:{start,end}` plus
  existing per-sender timestamps, per-interface counter windows and probe duration
  make the differing state/reward component intervals explicit.

`source_sha256` hashes the sorted compact ASCII JSON `source_files` map. Sources
include experiment, workloads, actions, topology, OSPF, measurements, runner,
controller, client, Dockerfile, dependency pins and Compose configuration. The
Docker image ID is outside `spec_hash` to avoid self-referential image hashing;
freeze both in artifacts. These are provenance identifiers, not remote attestation.

Scheduling has NOT been rewritten: action chosen from response k-1 is measured
under newly sampled workload phase k. The same response aggregate is the reward
outcome and the input for the next action, not a separate next-phase sample.
Even path0/path1/low/overload retain per-phase load variation; alternating/burst
add hidden path/load dynamics. This is a reactive measured baseline in a sampled
POMDP, not a guaranteed Markov state or proactive Step 10 controller. AI-owned
observation history can reduce aliasing but cannot establish an MDP guarantee.
Seed, scenario, phase index/relationship, and future schedule must stay outside
the actor's features. No separate `reward_observation` is introduced.

## Measurement Evidence

Foreground h1->h3 and background h2->h4 UDP processes run concurrently.
SDN attachment discovery is refreshed with real cyclic host probes before each
window: experiment-owned forwarding otherwise bypasses PacketIn and lets host
observations expire. These setup probes are outside the counter/load interval.
Both receivers are ready before load. Ping runs during the same load. UDP and ping
start before route-change commands; sender and receiver totals include
break-before-make control overhead, so reconfiguration loss is not discarded.
After readback, a complete requested post-control measurement window runs.
Senders acknowledge their first actual packet before control begins. Both
senders and receivers report monotonic start/end timestamps; all four must
cover the control start and complete post-control window. Route readback is
checked again after that window, while traffic still runs.
The controller's baseline can forward packets between removal and installation;
this is recorded rather than falsely described as a guaranteed outage.

Background SDN routes use table 1, priority 25000 and cookie
`0x4e414e4600000007`, scoped by ingress and h2/h4 IP/MAC identity in both directions.
Driver routes retain exclusive table-0 ownership and cookie
`0x4e414e4600000001`. Fixture replacement never modifies driver policy or Ryu's
cookie-1 learned forwarding. Both cleanup and installation have readback gates.

Evidence records per-port kernel byte counters and monotonic duration windows,
raw peak qdisc rows/times sampled during load, probe sent/received counts, both
UDP sender/receiver totals, actual offered rates, verified route rules, workload
phase, desired/measured windows, control overhead and episode/transition wall
time. Counter windows include startup/control and 250ms packet drain; they are
not falsely labeled exactly five seconds. Queue peaks are sampled, not continuous
global maxima. Host scheduling, shared CPUs, Ethernet/protocol overhead and probe
traffic affect observations. This is a measured routing experiment, not evidence
of policy superiority or production safety.

## Artifacts

`emulation/output/experiment-<UUID>-schedule.json` freezes each schedule;
`experiment-<UUID>-<index>.json` stores each raw observation/failure.
The smoke CLI writes mode-specific `experiment-smoke-<mode>.json`, append-only
`.jsonl` request/response traces and `experiment-smoke-<mode>-summary.json`.
`--policy alternate` demonstrates real actions; `--policy heuristic` uses lower
measured utilization plus queue/100 pressure, switching only beyond 0.15
hysteresis. OSPF is not this heuristic. Artifacts are ignored runtime output.

`--repeat-seed` repeats the same scenario/seed and verifies identical offered
phases across episodes, not identical noisy measurement outputs. Each smoke also
rejects invalid identities, out-of-order/duplicate steps, altered episode
configuration, boolean actions and excessive windows. Success is published only
after close acknowledges cleanup. OSPF startup additionally publishes
`experiment-ospf-readiness.json` with Full adjacency identities, FRR RIBs, kernel
paths, captured IP89 packets and all-pairs probes.

## AI Owner Handoff

After a smoke or AI command sends `close`, the container exits. Start a fresh
owner for every independent training/evaluation command, including mode changes:

```bash
python emulation/control.py experiment-start --mode sdn
# AI command uses docker exec -i nanfo-experiment python -m emulation.experiment_client
# AI close ends this server, not just the current episode.
python emulation/control.py experiment-start --mode ospf
python -m emulation.experiment_smoke --mode ospf --episodes 2 --steps 2 --window 5 --repeat-seed
```

Within one owner, reset after a completed episode keeps the container and topology
but cleans experiment routing/fixture ownership and creates a new UUID/schedule.
No keepalive or watchdog disabling is needed: send the first reset within 300
seconds of startup and subsequent requests within 300 seconds. If handoff takes
longer, restart explicitly. The lab must remain the only output producer. No
manual journal, backend worker, or neural training was used by these smoke gates.

Opt-in fault and real FRR reconvergence gates (run with no other lab owner):

```bash
python emulation/control.py experiment-start --mode sdn
NANFO_EXPERIMENT_LIVE=1 python -m unittest emulation.tests.test_experiment.ExperimentLiveTests -v
docker compose --project-directory emulation -f emulation/compose.yaml run --rm --no-deps -e EMULATION_CONTROL_ENABLED=false -e NANFO_OSPF_LIVE=1 --entrypoint python lab -m unittest emulation.tests.test_ospf.OSPFLiveTests -v
```

The fault gate deletes an experiment-owned route during traffic, requires a
truncated response with null UDP results and verified rollback, then measures a
successful fresh reset. Trace: `experiment-fault-trace.json`. This is deliberate
fault injection in the disposable lab, never an operator production action.
