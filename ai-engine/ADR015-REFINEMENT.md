# ADR015 Refinement Campaign

Completed at512 transitions/32updates; no checkpoint met the meaningful validation
improvement gate. Final seeds unopened, incumbent retained. Full measured outcome:
[ADR015-RESULTS-001.md](ADR015-RESULTS-001.md).

## Boundary

Implementation is isolated in `scripts/refinement/`. No code in `src/nanfo_routing/`
or original ADR014 artifacts is edited. The ADR014 default checkpoint remains
`5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`.
The original copied package is loaded under `_nanfo_adr014_frozen`, and its original
loader independently checks source, metadata, runtime, hashes and restricted
tensors. Warm-start copies model tensors only, not optimizer state or old samples.
Incumbent evaluation on V5 is explicitly a transfer experiment from its V4 image.

No backend, emulation or frontend implementation changes belong to this workstream.
No API, database, event, production provider or autonomous activation is added.

## Locked Design

`plan.py` is the executable preregistration, frozen in `artifacts/adr015-002/plan.json`
before any measurement. One configuration: original separate32-unit actor/critic,
16 measured inputs, two actual routing actions, unchanged reward including -0.05
route penalty; LR0.0005, gamma0.9, entropy0.01, fresh model RNG45. No second candidate
configuration or validation-driven hyperparameter changes.

- Profiles: balanced, moderate0, moderate1, severe0, severe1, overload, path0, path1.
- Windows2s, horizon4, episode-index modulo eight-profile sampling.
- Original reserve train1800..1999; recovery consumes1808..1999 after excluding
  failed instrumentation seed1800 and unused1801..1807. At least256, at most512
  fresh transitions remain available (192 reserved episodes,768 transitions).
- Checkpoints/validation128,256,384,512; only >=256 eligible for selection.
- Validation2800..2815: each profile twice, candidate plus five controls.
- Final3600..3623: each profile three times, all six policies exactly once.
- Prior attempted ledgers and actual summary seed lists checked for overlap. Unused
  old reserved train ranges are not misrepresented as consumed observations.
- Validation requires reward gain strictly >0.02 OR >=25% route-change reduction
  from a positive incumbent rate. All/anchor/lowload groups separately require
  delivery >=97% incumbent, RTT <=110% incumbent+2ms, reward >=incumbent-0.02;
  lowload switches cannot increase. No candidate outage passes these gates.
- Highest eligible validation reward wins, earliest checkpoint on a tie.
- Final requires the validation-selected endpoint's paired-seed95% bootstrap CI
  lower>0 plus nonregression margin CI lower>=0 in all/anchor/lowload groups.
  Lowload route-increase CI upper<=0. Bootstrap20000 draws, fixed RNG15015.
- These small grouped samples and sequential policy order limit generalization;
  repeated windows are not treated as independent seed replicates.

## Evidence

V5 strict request/data types preserve all raw fields and the unchanged observation
contract. Exact seeded draws are independently reconstructed from the inspected
release profile arrays. The adapter explicitly compiles two unchanged raw-check
blocks from the hash-verified original validator because it was monolithic; it
does not call V3 schedule admission, relabel a scenario or rewrite a V5 spec to V4.
It checks raw timings, both UDP flows, queues/counters, actual routes, verified
22-interface drain and V5 Full-neighbor/bidirectional routing-health evidence.
Every evaluation is reconstructed from its raw JSONL and checkpoint inference.
Invalid windows fail closed, never enter PPO and never become invented rewards.

New checkpoints contain parent source/spec/checkpoint hashes, V5 contract and
spec, runtime, refinement source hashes, fresh training seeds/counters, evidence
hashes and plan hash. Original artifacts are inventoried and checked unchanged.

## Operation

Run from `ai-engine/` only after the lab owner's completed V5 release:

```bash
.venv/bin/python scripts/refinement/campaign.py preflight --release artifacts/adr015-release.json
.venv/bin/python scripts/refinement/launch.py artifacts/adr015-release.json
.venv/bin/python scripts/refinement/campaign.py status
.venv/bin/python scripts/refinement/campaign.py stop
systemctl --user status nanfo-adr015-refinement.service
journalctl --user -u nanfo-adr015-refinement.service
```

One new output directory, no automatic restart or second test ledger. systemd
runtime cap at most14400s, `TimeoutStopSec=120`, control-group kill, no restart, bounded
memory/tasks; internal work deadline reserves120s for cleanup. Startup checks the
actual systemd properties. ExecStopPost verifies captured container ID, exact name,
image and campaign label before cleanup. No cleanup by name alone, broad prune,
host namespace cleanup or competitor termination. Each transport/stage is bounded.

Budget admission uses the maximum observed seconds/episode with35% headroom,
remaining stage/final episode counts and startup allowances, rather than repeatedly
reserving completed work. Below256 only execution/resource failure can stop;
optional extensions beyond256 must leave the full six-policy final reserve.
If validation fails, final seeds remain unopened and incumbent remains default.
Even a passing final produces human-review eligibility, not automatic deployment.

## Execution Record

- Original `adr015-001` stopped on a strict JSON logger rejecting a tuple-valued
  actor decision after reset and one actual decision on seed1800. Zero PPO updates,
  zero validation/test attempts; captured owner cleanup completed. All failed
  raw lab files and the original preregistration are retained unchanged.
- Corrected decision serialization to an explicit list; recovered once into
  `adr015-002` from the same verified incumbent, not partial weights or old samples.
  Recovery manifest records failed plan/evidence hashes and excludes consumed seed.
- Both attempts share the original deadline Unix1789051260.7651231. The recovery
  systemd cap was reduced to3h57m32s, not a new four-hour allowance.
- Independent replay accepted48/48 V5 campaign-profile instrumentation windows
  across matched/OSPF. Lab-owner release separately passed54/54 including `low`.
- Full AI suite324 passed (one existing Gym infinite-Box warning), scoped Ruff
  passed. Includes candidate PPO weight movement/roundtrip, strict V5 raw evidence,
  seeded profile replay, checkpoint-actor substitution rejection, minimum256
  eligibility, full512 control flow, six-method single final and no-quality no-test.
- Actual campaign completed all512 transitions and all four validation checkpoints;
  modest improvement missed frozen effect-size gates. No final test or promotion.
