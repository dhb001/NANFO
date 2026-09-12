# Step 7 Live Validation

## Environment Spec V2 Follow-Up

The earlier gates below describe v1 observations. Review follow-up keeps the
outer wire version 1, adds required nullable `actual_offered_mbps`, and publishes
environment spec version 2 with current source/image provenance. Scheduling is
unchanged and explicitly documented as sampled POMDP, not a Markov guarantee.
No AI files were edited and no training was run by the emulation owner.

- Image: `sha256:a9721d734aac37319794ba4756302c5162c075887cfd297075bf2dd03f324c6f`.
- Spec hash: `972ff6e8dc3a434db889f53a809ce0309e2d138bb4f16dd2d49dd2e50b7ad127`.
- Source hash: `b38d36ca9bbe47feddc8976263cb30e4817e8cc62c5de1ffa9213eae2020e98f`.
- Build: 66 tests collected, 64 passed, two opt-in fault gates skipped. New tests
  verify source sensitivity, exact hash recomputation, actual-rate reward ratio,
  no-reply outage with null RTT, malformed/missing evidence and nonpositive windows.
- SDN: two repeated-seed episodes, four decisions and two reset windows, 16
  protocol rejections, cleanup verified, 33.87s. Artifact:
  `output/experiment-smoke-sdn-402a5b5c-0ce1-4e2b-9476-173880b39700-summary.json`.
- FRR: same counts, cleanup verified, 21.94s. Artifact:
  `output/experiment-smoke-ospf-6a49155a-9485-451c-a645-c5e4b422e2f1-summary.json`.
- Both live traces passed the AI agent's new `validateMeasurement` evidence
  validator, including source/spec hashes, actual rates, phase relationship,
  intervals, queue/counter derivation and action readback. No neural runtime or
  actor was invoked. All 12 windows were complete; no live outage was induced
  in this follow-up (the outage branch was unit-tested).
- Target two-second windows measured 2.009..2.099s. Actual foreground offered
  rates were 9.2967..11.3317 Mbps. SDN separated-path RTT was 28.00..31.17ms,
  loss 3.01..3.87%; FRR shared-path RTT was 54.27..63.18ms, loss 21.13..33.23%.
  These shorter-window results include proportionally greater control overhead
  and must not be compared as identical intervals to the earlier five-second run.

Exact new fields and censoring caveats: `EXPERIMENT.md`, Environment Spec V2.
Old checkpoint/observation hashes are incompatible; AI history/provenance changes
remain AI-agent-owned. The image/source hashes above supersede the older release
image below. This follow-up report itself is host-side and not image-bound.

Validated 2026-09-09. Scope: `emulation/` only. No neural training, shared schema
edits, manual journal removal, backend/frontend edits, or Step 5/6 driver changes.

## Gates

- `python emulation/control.py build`: 64 tests collected, 62 passed, two opt-in
  live tests skipped during image build. Both live tests subsequently passed.
- `ruff check emulation`, `ruff format --check emulation`, scoped diff whitespace:
  passed.
- SDN alternate: two repeated-seed episodes, four decisions plus two initial
  windows, 16 rejected invalid/duplicate requests, cleanup verified, 49.22s.
- OSPF alternate: two repeated-seed episodes, four decisions plus two initial
  windows, 16 rejected invalid/duplicate requests, cleanup verified, 40.59s.
- SDN heuristic: two episodes, 12 decisions plus two initial windows, 24 rejected
  requests, cleanup verified, 102.28s. Real host discovery remained fresh beyond
  the previous 60s expiry. Held routes were verified without reinstalling.
- FRR: 14 Full directed adjacencies, 36/36 all-pairs ping replies, two captured
  OSPFv2 packets, real kernel failover onto dist2 in 0.282s after local link-down,
  and restoration to dist1. This local carrier-down result is not a remote
  dead-timer convergence bound.
- Fault gate: deleting an owned route during load truncated the measurement,
  retained null UDP results, verified cleanup, and allowed a successful reset.
- Actual AI `RoutingEnv(DockerTransport())` reset/two steps/close passed against
  the final image: 47-element state, finite rewards 0.83205/0.82716, correct Gym
  horizon truncation. No AI files were edited. Both baseline traces also passed
  the AI strict response schema (22 measurement/error envelopes per mode).

## Measured Results

| Run | RTT ms | UDP loss | Foreground Mbps | Peak queue packets |
| --- | --- | --- | --- | --- |
| SDN congested path0 | 64.71..66.31 | 27.82..34.22% | 7.45..7.51 | 100 |
| SDN moved to path1 | 24.09..25.79 | 1.34..1.46% | 9.16..9.17 | 6 foreground, 9 background |
| OSPF shared path0 | 65.00..66.21 | 21.63..34.00% | 7.28..7.49 | 100 |

Requested five-second post-control windows measured 5.003..5.098s in SDN and
5.018..5.080s in OSPF. SDN route-change control took 0.679..0.694s; hold/readback
took 0.167..0.170s. OSPF readback took 0.023..0.052s. UDP totals include control
time, and interface counter durations additionally include startup/drain/readback.
These are short functional measurements, not statistical policy comparisons.

## Artifacts

All paths below are relative to `emulation/output/` (ignored runtime evidence).

- `experiment-smoke-sdn-b7cc5d45-d67c-4f0a-9e3f-77b73d67044f-summary.json`
- `experiment-smoke-ospf-2f15cbd7-014b-412d-acee-0cb3efae0ded-summary.json`
- `experiment-smoke-sdn.jsonl`, `experiment-smoke-ospf.jsonl`: append-only history,
  including rejected protocol requests and failed runs.
- `experiment-<UUID>-schedule.json`, `experiment-<UUID>-00.json` etc.: frozen
  offered schedules and raw observation/readback/counter/queue/UDP/probe evidence.
- Heuristic episode UUIDs: `8d9a2118-b23b-4db9-8a39-7aec27c6bb37`,
  `efd2b646-a364-4522-b464-6e04ec671bd0`.
- `experiment-ospf-readiness.json`, `experiment-ospf-reconvergence.json`.
- `experiment-fault-trace.json`: live deletion, null truncation, reset and close.

## Failures And Limits

- Earlier SDN heuristic reset failed on expired host attachments. Fixed using
  real cyclic discovery probes outside the measurement interval, not fake host
  records or bypassed driver checks. Failed episode:
  `229b5fdc-3a92-433c-a34b-74d678089995`.
- Two saturated FRR runs using a 4s dead timer changed path mid-window and were
  correctly rejected: `4872da11-39f4-4be5-aebb-cafc91725e00` and
  `69eb9725-a25d-416d-82f8-ef71010c89ff`. Final explicit policy uses 1s hello/10s
  dead, no ECMP or route pinning. Long saturation can still cause reconvergence;
  mixed-path windows remain invalid. A restoration test initially assumed Full
  adjacency meant completed FIB update; its bounded FIB wait was corrected.
- Windows 2..10s, decisions 2..64, generator tolerance 20%, window overrun
  tolerance 2s, request watchdog 45s, client timeout 60s, idle watchdog 300s.
- Request limit 4096 bytes; lab response limit 1 MiB. Actual responses passed the
  AI transport/schema's smaller bounds. Unknown/duplicate fields, nonfinite
  values, boolean integer fields and identity/order violations reject.
- No replay cache: duplicate steps reject without executing twice. Lost reset
  responses are ambiguous because reset has no caller request ID; stop/restart
  rather than retry. Successful close terminates the entire owner.
- Queue maxima are sampled, not continuous. Nonzero protocol overhead can appear
  on idle paths. Missing measurements remain null and truncate, never zero-fill.
- FRR uses Linux L3, distinct /30 subnets and shared OSPF-selected background;
  SDN uses OVS L2 and scoped background placement. They are not identical dataplanes.
- Container budget: two CPUs, 768 MiB, 256 PIDs, isolated network, privileged
  namespace lab only. HTB emitted existing large-quantum warnings; shaping and
  real traffic gates passed. No production or policy-superiority claim.

## Release Lifecycle

Final runtime image: `nanfo-emulation:campus-small-v1`,
`sha256:87fb02e4aa6c966e602fba2d3513292c9ea3c826332d7d5e02d160ff888e0bcc`.
The final image includes all runtime changes; this host-side report was added
after build. See `EXPERIMENT.md` for exact requests and reproducible gate commands.

Use the handed-off fresh SDN container `nanfo-experiment` within 300s. The fixed
transport is `docker exec -i nanfo-experiment python -m emulation.experiment_client`.
Do not run another smoke against it while the AI agent owns it. After AI close,
start a new owner with `python emulation/control.py experiment-start --mode sdn`
(or `ospf`). For uncertain state use `python emulation/control.py experiment-stop`
before starting again. Never remove a manual journal to acquire the slot.
