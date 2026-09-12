# ADR013 Review Corrections

This is a post-campaign validation/display correction, not a new campaign or an
amended result. No historical artifact, reward, counter, contract, checkpoint,
fingerprint or frozen source file is rewritten. Both saved pilots remain unqualified;
there is no useful-model or eventual-success claim.

## Seed Binding

The original validator accepted demand within broad ranges when observations and
evidence agreed. That allowed a coherent request/response/summary seed relabel, or
coherently changed demands, despite refreshed evidence digests.

The current validator independently reconstructs `seeded-stationary-capacity-v3`
after checking that exact supported spec: a private `random.Random(seed)`, foreground
`round(uniform(5.8,6.2),3)` followed by background `round(uniform(1.8,2.2),3)`, fixed
background path0, scenario-derived capacities and the current phase index. The
phase and observation targets must equal these values exactly. Measured achieved
rates still use their original counter derivations and generator tolerance. No
seed or reconstructed future data enters the actor.

Tests reject coherent 2600->2998 relabeling, including full session labels and
rehashed JSONL, and demand changes with consistently rebuilt counters/rates/rewards
inputs. Producer parity is exercised independently via the lab's pure schedule
function for matched/OSPF, low/path0/path1, boundary seeds and reset/step/horizon.
The runtime validator does not import or execute emulation code.

This is consistency checking, not attestation. Two seeds can collide after the
producer's three-decimal rounding; no observation-only check can distinguish
identical materialized inputs. Fabricated internally consistent evidence still
requires trusted provenance/ownership controls, not just hashes.

## Pressure Swap

The saved acceptance gate swaps path capacities/utilization/queues while retaining
previous action, foreground delivery/deficit, RTT and elapsed route age. These are
coupled measurements, not independent knobs. The resulting synthetic observation
can contradict the retained route/outcome and actual OSPF background placement;
it is not necessarily reachable under the benchmark. A useful policy using those
relationships can therefore fail the swap gate. It is not a sound causal necessity
test merely because the numerical input is schema-valid.

**The old gate, threshold and saved qualification results are unchanged.** Exact
historical replay uses only the fingerprinted frozen source for audit, with its
known validator weakness; it is not approval to admit new evidence. The two pilots
also independently failed measured directional choices (route0 on every validation
decision), so this finding is not evidence that either is useful. A candidate
improvement remains OPEN. A future separately versioned acceptance plan should
predeclare reachable balanced interventions and distinguish measured dependence
from diagnostic perturbations. No replacement gate or relaxed threshold is added
here, and no holdout is accessed or reused for tuning.

## Receiver Cutoff

Existing `loss_fraction` / report "UDP loss" means **delivery deficit at bounded
receiver cutoff, not eventual packet loss**. The fixed post-sender drain is 250ms;
100 queued 1200-byte packets take 480ms at 2Mbps even without protocol overhead
(about 500ms with overhead). Some not-yet-delivered packets may be counted in the deficit.
The counters do not distinguish eventual drops from delivery after receiver cutoff.
Goodput and the unchanged reward also inherit that cutoff.

Newly rendered reports append this clarification to the existing per-session
`limitations` list. Historical JSON/Markdown outputs are not rewritten; this note
supersedes their "UDP loss" interpretation, not their numerical values. There is
no new `measurement_semantics` field and no change to `ProducerQualification`,
checkpoint, reward or backend dossier schemas, avoiding unknown-field importer
breakage. Backend/emulation files are untouched. A future drain/counter correction
requires a new producer measurement spec/version and fresh predeclared evidence.

## Compatibility

Current `evidence.py` and `cli.py` source hashes now differ from campaign001.
The existing exact-source checkpoint loader must reject those old bundles under
the current runtime; there is no fallback or edited source map. The old contract
hash and `seeded-stationary-capacity-v3` remain intact for historical interpretation.
A future campaign must explicitly freeze a new campaign/client acceptance spec
version and hashes before collection; do not silently reuse the old plan as if
these checks or future gate/drain changes had been present during collection.
No new campaign spec is declared or authorized by this correction.

Read-only verification command (does not write bytecode into the stored snapshot):

```bash
ai-engine/.venv/bin/python ai-engine/scripts/audit_adr013_review.py ai-engine/artifacts/adr013-001
```

It verifies the saved artifact fingerprints, validates existing measurements using
the hardened seed check, replays both saved gates with the original source, and
checks that the current loader refuses historical source drift. It does not rerun
training, create qualification artifacts or modify stored snapshots.

Verified: **275 tests passed**, Ruff lint/format and `git diff --check` passed.
The read-only audit verified **122 historical file fingerprints**, accepted all
**220 recorded windows** with reconstructed seed demands, reproduced both saved
`qualified:false` gates exactly, and confirmed current-source rejection for both
old checkpoints. One existing Gym unbounded-observation-space warning remains.
