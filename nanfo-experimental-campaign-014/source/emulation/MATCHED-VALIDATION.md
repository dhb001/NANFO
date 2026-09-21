# ADR-013 Matched Lab Handoff

## Frozen Contract

Implementation and live verification completed 2026-09-09. Scope: `emulation/**`
only. No AI training, backend, frontend or production authorization changes.
Exact V3 deltas are in [EXPERIMENT.md](EXPERIMENT.md#matched-v3-adr-013).

- Source SHA256: `cce8e05a862bff244eac3efe53f43d60856423d9c8b23a54c31be5fbcafade02`
- Shared matched/OSPF spec hash: `5ece436bfa8b41fd868dfc87dc5152848d038e25511c6dadee1e64a420b1cbe9`
- Built/verified image: `nanfo-emulation:campus-small-v1`
- Image ID: `sha256:72b267fdcb6f197d0ffe4960389e238ea093fac61b3f95751cf98edfefd098ad`

Image includes the executing code/tests; this handoff documentation was written
after live validation and is not part of the hashed executable source set.
The actor contract must add `path_capacity_mbps / 20`, use V3 stationary phase
semantics, accept `matched`, and freeze its own feature/action/reward versions.
Do not load stale V2 models. Scenario/seed/index remain evidence, not actor inputs.

## Live Evidence

Train-only matrix: two decision windows per cell, two-second post-control
windows, seeds 1000/path0 and 1001/path1, all three policies on both conditions.
One actual FRR lab instance; explicit route cleanup between methods. No selection
of only favorable scenarios. Reset warmup windows excluded from these means.

| Policy | path0 Goodput Mbps | path1 Goodput Mbps |
| --- | ---: | ---: |
| Constant route 0 | 1.7344 | 6.1188 |
| Constant route 1 | 5.9121 | 2.4257 |
| Actual OSPF | 1.7403 | 6.1188 |

Both route-optimality gates passed with >2 Mbps advantage. These are short
action-effect checks, NOT held-out policy qualification or statistical evidence
of trained-policy superiority. Sender lifetime includes control/transitions;
the first constant1 decision starts from reset's route0. Thus transition goodput
can exceed a degraded path's instantaneous 2 Mbps limit. No counters are capped
or relabeled steady-state measurements. Actual sender-rate validation, full
window coverage, concurrent ping, unique UDP delivery, per-interface counters,
queue samples, capacity readback and both-direction policy readback all passed.
Nominal OSPF costs intentionally do not track the exogenous HTB degradation.

Artifacts in `emulation/output/`:

- `experiment-matched-matrix.json`: all 18 raw measured windows.
- `experiment-matched-matrix-summary.json`: matrix means, episode IDs and hashes.
- `experiment-smoke-matched-f9f91bf4-4487-4bff-9096-be55941c342d-summary.json`:
  public JSON transport, alternating routes in both scenarios; 4 decisions,
  2 reset windows, 16 invalid/repeated request rejections, cleanup passed.
- `experiment-smoke-ospf-1badd979-2e11-410c-84ce-f192a457a949-summary.json`:
  same public transport/scenarios; 4 decisions, 2 resets, 16 rejections, actual
  OSPF route0 despite requested actions, cleanup passed.
- Both smoke summaries carry the exact image ID above. Matrix direct-run image
  provenance is null rather than fabricated; the public transport closes that gate.
- `experiment-ospf-readiness.json`: actual FRR neighbor/RIB/IP89 and all-pairs
  probes from the latest OSPF start. Individual UUID window files retain routes.

All 72 emulation tests ran: host 66 passed/6 expected dependency/live skips;
built pinned image 70 passed/2 opt-in live skips. New tests cover stationary
paired schedules, V3 hashing, actual-capacity normalization, strict HTB text
readback, hold behavior, all six bidirectional rules/routes, foreign ownership
refusal and partial-install restoration. Ruff check and format passed.
The live matrix and public smokes separately exercised actual FRR forwarding,
probe/delivery, both explicit routes, readback and restore. Legacy SDN fault and
FRR link-failure opt-in suites were not rerun in this bounded V3 check.

## Commands

No experiment owner remains after verification. The built image is ready; start
one mode at a time (manual mailbox disabled by the operator command):

```bash
python emulation/control.py experiment-start --mode matched
# AI transport:
docker exec -i nanfo-experiment python -m emulation.experiment_client
# Send reset/step/close version-1 JSON; mode="matched", scenario="path0" or "path1".
```

Close through the protocol after collection. If the owner is still active and
needs explicit shutdown, use `python emulation/control.py experiment-stop`.
Start the independent baseline with `experiment-start --mode ospf` and send
`mode="ospf"`. Balanced smoke, which closes its owner itself:

```bash
python -m emulation.experiment_smoke --mode matched --episodes 2 --steps 2 --window 2
```

Standalone full action-effect matrix (no other lab owner may be running):

```bash
docker compose --project-directory emulation -f emulation/compose.yaml run --rm --no-deps --entrypoint python lab -m emulation.verify_matched
```

This implementation launched no learning campaign. The coordinating AI campaign
must predeclare its train/validation/test ranges and stay within ADR-013's initial
20-minute collection budget. Historical checkpoints/results were not deleted.
