# ADR016 Balanced Long Refinement

Implementation is isolated in `scripts/refinement_long/`. No completed ADR014 or
ADR015 source/artifact, core routing package, emulation, backend or frontend is
modified. The default remains ADR014; no autonomous provider/promotion is enabled.

## Frozen Contract

- Parent: ADR015 candidate512 SHA256
  `50437cbc01c9ed029f40875943fbfe6d6c89f0fe7ccebf90a5a3e71e6780d75f`.
- Exact historical source-verified loader validates original metadata/runtime and
  restricted tensors. Warm-start copies model tensors only into NEW Adam/RNG46,
  with counters reset to zero. Old optimizer/moments/samples are not resumed.
- Same16 measured features/actions/reward, LR0.0005, gamma0.9, lambda0.95,
  entropy0.01, clip0.2, four epochs, max gradient norm0.5, route penalty0.05.
- Rollout/minibatch32/32: eight four-step episodes, all eight profiles once per
  update. Every update records profile order, raw rollout, gradients and before/
  after model tensor hashes. No heuristic replacement of the learned actor.
- New versioned runner namespaces: train10000..19999, validation20000..29999,
  test30000..39999. Chosen train10000..10511 yields2048 fresh transitions;
  validation20000..20063 and final30000..30127. Core historical split validation
  stays unchanged; no global patch or fake seed remapping.
- Profiles repeat balanced, moderate0, moderate1, severe0, severe1, overload,
  path0, path1; window2s, horizon4. The unchanged strict V5 evidence adapter
  reconstructs exact seeded phases, raw measurements, drain and routing health.
- Pinned V5 image unchanged:
  `sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9`.
- Training starts immediately in128-transition sessions. Validation only at1024
  and2048. Each checkpoint evaluates all seven methods on64 seeds: incumbent,
  candidate512, constant0, constant1, heuristic, OSPF and new candidate.
- Evaluation sessions contain eight seeds, one per profile. Cyclic Latin-square
  method ordering counterbalances each complete seven-block cycle; residual
  eighth/sixteenth blocks are explicitly frozen, not claimed perfectly balanced.
  Controls are remeasured at both checkpoints rather than using stale prior means.

## Qualification

Against incumbent, retain ADR015 mean reward gain strictly>0.02 OR at least25%
switch reduction from a positive baseline rate. Also require progress against
candidate512: reward delta strictly>0 OR at least25% switch reduction. Against BOTH
references separately, all/anchor/lowload mean delivery>=97%, RTT<=110%+2ms,
reward>=reference-0.02, lowload switches cannot increase, candidate outages fail.

After2048, select highest qualified validation reward, earliest checkpoint on tie.
No qualified checkpoint means final seeds remain unopened. If admitted, seven
methods run once on128 fresh final seeds. The endpoints selected on validation
must each have paired-seed bootstrap95% CI lower>0 against their respective
reference. Grouped margin CI gates remain unchanged. No final-based retuning,
restart, failed-step replay or automatic promotion. Confidence is not an improvement.

## Bounds And Integrity

One24h systemd user service, RuntimeMaxSec86400, no restart, TimeoutStopSec180,
CPUQuota200%, MemoryMax2GiB, TasksMax128. Lab ownership reuses captured container
ID plus exact campaign label/name/image checks; lab2CPU/768MiB/256PIDs, no network,
no exposed port. ExecStopPost performs exact owned cleanup, never broad removal.

Campaign work deadline reserves180s. Remaining-work admission models all remaining
training, both remaining validation passes and final collection, using1.25 times
the maximum observed session-average episode seconds (initial25), plus each
session's startup/cleanup allowance (minimum30s, measured with25% headroom).
Final reserve is at least8h. Initial modeled total79380s leaves7020s headroom.
Startup/cleanup is not double-counted as per-episode cost. Budget shortage stops
explicitly rather than consuming the final reserve or pretending completion.

Output is monitored against4GiB with64MiB headroom and50000-file ceiling after
every episode and before child commands. This is monitoring, not a filesystem
quota. Raw sessions have64MiB log limits and bounded transport/stage deadlines.

Preflight checks failed/successful ledgers and raw files in AI artifacts and lab
output/results. Historical metrics are never admitted to training; only seed
identity and file digests are inspected.3435 files are pinned, including the1437
ADR014 inventory and all ADR015 files. Large inventories are explicitly chunked
to retain the strict JSON parser's object bounds. Source hashes and runtime are
checked during collection. Elapsed time and completed-round/update counts survive
post-stop cleanup without being reset or falsely marked failed.

## Commands

From `ai-engine/`:

```bash
.venv/bin/python scripts/refinement_long/runner.py preflight
.venv/bin/python scripts/refinement_long/launch.py
.venv/bin/python scripts/refinement_long/runner.py status
.venv/bin/python scripts/refinement_long/runner.py stop
systemctl --user status nanfo-refinement-long-001.service
journalctl --user -u nanfo-refinement-long-001.service
```

Output: `artifacts/adr016-001/`. Do not relaunch an existing output directory.
Stop file is polled between bounded transitions. Service stop also invokes owned
cleanup. `status.json`, `ledger.json`, `initialization.json` and each session's
`evidence.jsonl`, `audit.json`, `summary.json` expose actual progress. Every completed
128-transition session saves a separate checkpoint; an active run is not a result.

Tests before launch: full AI336 passed (one existing Gym infinite-Box warning),
including explicit namespace rejection, historical split preservation, parent
tensor transfer/new optimizer, actual PPO movement, checkpoint roundtrip, balanced
session collector, both-reference gates, counterbalancing, budget, no-replay,
cleanup and terminal-duration regressions.

## Live Milestone

Verified2026-09-10 after first complete session; campaign is **ACTIVE**, not qualified
or promoted. No launch failure/recovery occurred.

- Unit: `nanfo-refinement-long-001.service`, active/running, restart=no.
- Service entered active2026-09-10 17:59:23 UTC; systemd runtime cap ends no later
  than2026-09-11 17:59:23 UTC, with180s bounded stop/cleanup timeout.
- Frozen measurement clock started2026-09-10 17:59:38 UTC after15s read-only
  preparation. Internal work deadline2026-09-11 17:56:38 UTC and hard deadline
  17:59:38 UTC; systemd's earlier cap remains authoritative.
- Campaign label: `org.nanfo.training.campaign=a74a85b5fb8a4d57895f50b5695b3c93`.
- Completed `train-0128`: seeds10000..10031,128 measured on-policy transitions,
  four32-transition updates, each eight profiles exactly once. Raw audit passed;
  protocol cleanup and captured-ID cleanup verified.
- First gradient norm1.544510126; first model digest changed from
  `79a968117a9fbcdab6a2c22687bdafc3cd2dbca3b257276623980652f784438d` to
  `4ddbe5b948fbdb40730a1dc356be9bf228c43cf04716ad3f1156b82cfb5db5b9`.
- Checkpoint `artifacts/adr016-001/candidate-0128.ptz`, SHA256
  `f06570e4e9c3ba32e7242e21efe621e06dfafd4681faeac4135b068cb0527b7c`;
  fresh-process restricted load verified128 transitions/four updates.
- Original session container
  `b6426d93296fab3b268e6461a0f86ddf817d3f2a47fe33ae04db483113d6cf97`
  verified absent. Next session `train-0256` started in a new owned container.
-3435 historical hashes rechecked unchanged. Validation and final attempts zero.
  Incumbent/default unchanged; live `status.json` supersedes these milestone counts.
