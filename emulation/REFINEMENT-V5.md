# ADR015 Stationary Refinement V5

Scope is `emulation/**` only. No AI/backend/frontend edits, training, checkpoint
selection, production activation or claim of model improvement. The incumbent
remains the default. V5 is an explicit transfer/generalization environment, not
silent checkpoint compatibility. Read this schema before adapting the AI client.

## Version And Profiles

`mode=matched` and `mode=ospf` automatically select envSpec `version=5`,
`name=nanfo-matched-stationary-routing`,
`schedule_version=seeded-stationary-profiles-v5`. Outer JSON request/response
`version=1` and its exact fields remain unchanged. Profile is the existing
`scenario` field; there is no extra mode name or request profile/version field.
SDN remains envSpec v4 with its original scenario set and dynamic workload draws.
Reject unknown profiles and `alternating`/`burst` in matched/OSPF. No `anchor0/1`
aliases: `path0/1` are the original anchors. `low` retains its original demands,
not the new balanced low-demand semantics.

| Scenario | Path0 Mbps choices | Path1 Mbps choices | Foreground uniform Mbps | Background uniform Mbps |
| --- | --- | --- | --- | --- |
| low | 20 | 20 | 5.8..6.2 | 1.8..2.2 |
| path0 | 2 | 20 | 5.8..6.2 | 1.8..2.2 |
| path1 | 20 | 2 | 5.8..6.2 | 1.8..2.2 |
| balanced | 20 | 20 | 3..5 | 1..2 |
| moderate0 | 6 | 20 | 8..10 | 1..3 |
| moderate1 | 20 | 6 | 8..10 | 1..3 |
| severe0 | 3,4,5 | 12,13,14,15,16,17,18,19,20 | 7..10 | 1..3 |
| severe1 | 12,13,14,15,16,17,18,19,20 | 3,4,5 | 7..10 | 1..3 |
| overload | 6,7,8 | 6,7,8 | 10..12 | 2..3 |

All units above are decimal Mbps. `profiles` in the full hashed envSpec contains
every explicit choice array and demand range, not shorthand ranges. Exact replay:

1. Construct Python `random.Random(seed)`, integer seed in `0..2147483647`.
2. Draw foreground with `round(rng.uniform(*profile["offered_mbps"]), 3)`.
3. Draw background with `round(rng.uniform(*profile["background_mbps"]), 3)`.
4. Follow `capacity_draw_order`: `[0,1]` except `severe1=[1,0]`. A singleton
array returns its element without consuming RNG state; otherwise `rng.choice`
selects from the full listed array. Severe direction pairs mirror capacities
exactly for equal seeds; background stays on path0, so outcomes need not mirror.
5. Repeat the same capacities, foreground, background and `background_path=0`
for `episode_steps+1` records with `phase_index=0..episode_steps`. No other draw,
profile mixing, action-conditioned workload or per-window resampling occurs.

The schedule phase still has exactly `phase_index`, `background_path`,
`offered_mbps`, `background_mbps`, `path_capacity_mbps`. `schedule_draws` declares
the algorithm in the spec. The full episode array is saved in each UUID schedule
artifact; metadata/future schedule are not actor inputs.

## Observation And Evidence

The 16-feature actor contract and two-action map are unchanged. No profile, seed,
phase or health feature is added to observations. Raw observation fields remain:
`path_utilization`, `path_queue_packets`, `latency_ms`, `loss_fraction`,
`goodput_mbps`, `offered_mbps`, `actual_offered_mbps`, `background_mbps`,
`previous_action`, `seconds_since_change`, `path_capacity_mbps`.
The parent AI implementation owns flattening/normalization and tensor validation.

`path_capacity_mbps` is verified actual HTB service, not nominal topology bandwidth.
Each value applies independently to rate AND ceil on four interfaces (both
directions of both serial inter-router links). Repeated service is not additive
capacity. Hold windows only read classes; reset changes the existing `5:1` class,
not leaf limits/delay or OSPF cost. Allowed integer rates are exactly
`2,3,4,5,6,7,8,12,13,14,15,16,17,18,19,20`; reject booleans/floats/other rates.
Before/end class readbacks include eight unique interfaces. Utilization divides
measured bytes/time by the relevant actual capacity. `pathInterfaces()` also
reports shaped capacity after configuration, not hardcoded 20.

`flow_order=["h1->h3","h2->h4"]` applies to `udp_sent`, `udp_received` and
`actual_offered_mbps`. Each actual rate is `sender.bytes*8/sender.duration_seconds/1e6`
and must be within 20 percent of its phase target independently. UDP payload is
1200 bytes; bytes must equal packets times 1200; receiver counts must be in
`0..sent`, with valid sequences and complete sender/receiver lifetimes. Foreground
observation actual offered is element 0. Goodput is actual received foreground
bytes divided by actual foreground sender duration, including control/drain service
in its numerator. No promised delivered rate or capacity-derived delivery is used.
RTT remains foreground ICMP RTT; complete positive-probe zero-reply outage has null
RTT, not invented latency. Late received packet counts remain `[null,null]`.

Added raw evidence `routing_health_start` and `routing_health_end`, each exactly
`{start,end,neighbors,paths}`. Times are monotonic; `neighbors` contains fresh FRR
JSON for every router; `paths` contains `h1->h3`, `h3->h1`, `h2->h4`, `h4->h2`
kernel route walks. Full peer/interface identities and exact bidirectional paths
are required before load and at end under load. Background must remain actual FRR
path0 in both modes. Matched controls only foreground policy routes; OSPF ignores
requested actions and must remain actual path0. Drift truncates with incomplete
measurement, without waiting/retrying until a favorable result.

FRR nominal costs, single-next-hop policy, hello **1s**, dead **10s** are preserved.
Two-second windows are shorter than the dead timer: fresh sampled Full state and
route checks do NOT establish continuous adjacency health or a convergence SLA.
Control traffic competes in the same queues/counters; no priority treatment or
baseline-disadvantaging timer/cost retuning is introduced.

V4 verified drain is unchanged: all senders exited, both receivers alive, all 22
leaf queues empty in two complete sweeps separated by at least 80ms, within a
3-second maximum. Failure retains partial evidence but invalidates delivery/loss.
100-packet queue bounds remain unchanged even at the 2 Mbps anchors.

## Operation And Preservation

Historical replay uses `nanfo-emulation:adr014-v4` pinned by its original image ID,
spec and source hashes in `ADR015-V4-PRESERVATION.md`. Never rebuild that tag or use
the V5 workspace spec to validate old observations. New code intentionally has no
V4 matched branch; the old image contains the exact old source/runtime.

`NANFO_EMULATION_IMAGE` selects an existing image tag or immutable image ID in both
Compose and `control.py experiment-start` provenance lookup. Use immutable IDs for
collection. `control.py build` refuses an image override to protect pinned images.
Build the working tag, validate, then tag the actual ID `nanfo-emulation:adr015-v5`.
Set the same override when invoking Compose directly. Do not rebuild for handoff.

The bounded verifier is `python -m emulation.verify_refinement` inside one isolated
owned FRR container with `NANFO_LAB_IMAGE_ID` equal to its inspected immutable ID.
It writes a unique `output/adr015-smoke-UUID/` directory before startup, preserving
all original raw artifacts and fixed-name historical readiness/smoke files. Plan:
seed **15100**, all nine profiles in listed order, matched then OSPF, one reset
plus two decisions `[1,0]`, 2-second windows, 600-second collection deadline,
container wall deadline with cleanup reserve. This is instrumentation-only seed
space: do not recycle these observations for model selection or held-out testing.
Failures are retained, not silently retried. Original `verify_matched` remains.

The verifier checks exact independent seed replay, all capacity classes, both
actual offered rates, unchanged observations, fresh health, initial/decision drain,
episode routing cleanup, source/spec/image provenance, and per-artifact hashes.
Host and Docker unit suites run separately. No competing training until this lab
release is complete; parent AI must explicitly read/pin V5 before its own campaign.

The normal owner remains `nanfo-experiment`: close acknowledges routing cleanup
and ends the server, then container removal disposes FRR/namespaces. Emergency
stop is `python3 emulation/control.py experiment-stop`. Never use host `mn -c`,
global `pkill`, broad Docker removal or delete old artifacts. All operator Docker
calls and in-lab commands have finite timeouts; the transport retains its 45s
request/300s idle watchdogs. Unique smoke directories do not alter the normal
single-owner transport or add an application API/database/event contract.

## Validated Release

Validated 2026-09-10; lab released with no training started. Do not rebuild this
image for handoff. Documentation below was added after the successful build and
does not change the runtime source/spec hash.

- Image tag: `nanfo-emulation:adr015-v5`
- Pinned image ID: `sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9`
- Matched AND OSPF spec SHA256: `42c9c9177f3d35915c9858b2894e5146c74a6d1614ebc25bfbc00b6ba39057c3`
- Runtime source SHA256: `2d48ff1f987f626380624e3c817f217a8700ac3b33592de414b3337cdfc614b6`
- Smoke directory: `output/adr015-smoke-8e424505-cc49-40bb-afae-ee91d5045028/`
- Summary SHA256: `fce560ea5237fb63b0610fdd78292d04c09675fc5ccf592cfb11d12c79178386`
- Frozen plan SHA256: `f45b7abadd5c95e3dc2987af1aefbb2cfc3b27bc761dae92717c7b29374698aa`

Host suite: 81 run, 75 passed, 6 runtime/opt-in skips. Docker build suite: 81 run,
79 passed, 2 opt-in fault/reconvergence skips. Ruff check/format and scoped diff
whitespace checks passed. Preserved V4 image was independently executed without
privileges to reproduce its exact original spec and source hashes. V5 executing
spec was likewise checked against the workspace after the live run.

Live: **54/54 windows passed**, 18 resets and 36 decisions, all nine profiles in
both modes. Total 246.690 seconds. Verified drain range **0.214524..1.196757s**,
including original 2 Mbps anchors. No truncations, no profile retries, no changed
queue limits, no changed OSPF timers/costs. Seed15100 capacities for severe0/1
were `[4,14]`/`[14,4]`; overload `[7,8]`. Other capacities match their fixed table
rows. Both per-flow actual offered rates passed every window. These measurements
do not prove every seed/capacity combination, long-duration convergence, model
generalization, no-switch behavior or superiority.

Summary inventories 74 SHA256-verified JSON artifacts: predeclared plan, readiness,
18 schedules and 54 raw windows. Host audit rehashed every file successfully.
Each raw window includes the full V5 envSpec, exact profile arrays/draw schema,
phase and all actual evidence. Existing output files were not overwritten.

The successful live invocation used the inspected working image ID above:

```bash
timeout --signal=TERM --kill-after=25s 650s docker compose -f emulation/compose.yaml run \
  --rm --no-deps --name nanfo-adr015-smoke --entrypoint /usr/bin/tini \
  -e EMULATION_CONTROL_ENABLED=false \
  -e NANFO_LAB_IMAGE_ID=sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9 \
  lab -- python -m emulation.verify_refinement
```

Afterward `docker ps -a` for `nanfo-adr015-smoke` and `nanfo-experiment` returned
no containers. Routing cleanup and network close passed; the removed disposable
container released owned FRR/workload processes and namespaces. No unrelated
container/service was changed. The verifier directly exercises the environment,
not a fresh live Unix-transport fault campaign; prior transport tests remain.

For the parent agent's separately authorized V5 campaign:

```bash
export NANFO_EMULATION_IMAGE=sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9
python3 emulation/control.py experiment-start --mode matched
# Client must pin the full V5 spec/hash, consume reset observation, then step/close.
# Use a new owner with --mode ospf for the paired baseline.
```

No campaign is running at release. Parent AI owns the frozen training/validation/
test plan, reserves different seed/profile combinations, reads `profiles` rather
than assuming v4 ranges, and verifies parent checkpoint/architecture/finite tensor
values before explicit transfer. A matching 16-dimensional tensor alone is not
semantic compatibility or evidence of improvement.
