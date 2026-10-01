# Successor qualification protocol (ADR-028)

Status: declared, not yet run. Applies only to **new** successor campaigns. Every ADR013–ADR024
result keeps the protocol, gates and labels it was recorded under; nothing here re-evaluates
or relabels historical evidence (ADR-028 §1).

Code: `src/nanfo_routing/successor.py` (`protocol()`, `capacityOracle`, `capacityAwareOspf`,
`evaluate()`). Tests: `tests/test_successor_protocol.py`.

## Why the ADR024 gates are insufficient

ADR024 qualified a model if it beat both constant policies on reward (margin > 0.02, CI lower
bound > 0), beat nominal-cost OSPF on goodput and ICMP RTT, and chose the unimpaired path in a
majority of windows. In the stationary campus lab the shaped HTB capacities are part of every
observation, so the trivial rule **argmax(path_capacity_mbps)** passes every one of those gates:
it always avoids the impaired path (beating the constants, which are wrong in one scenario, and
nominal OSPF, which prefers the impaired `dist1` path) and its direction is always correct.
`test_argmax_capacity_passes_every_historical_adr024_gate` runs the actual ADR024 `assess()` to
show this. The ADR024 gates therefore cannot show that a learned policy adds anything beyond
reading the capacities.

## Protocol elements

- **Capacity baselines.** `capacity-oracle`: argmax of the observed HTB capacity (ties keep the
  previous route). `capacity-aware-ospf`: the path OSPF would select with auto-cost
  `100 Mbps // capacity` (integer, minimum 1; ties prefer the nominal first path). Both run
  through the same matched route actions as the heuristic. The full baseline set is
  `capacity-oracle, capacity-aware-ospf, heuristic, ospf, constant0, constant1`.
- **Whole-profile holdout.** Training, validation and selection use `low, path0, path1,
  balanced, moderate0, moderate1`; `severe0, severe1, overload` are never seen before the test
  and are gated separately.
- **At least five model seeds.** Five or more independently trained models; no selection
  among them; every model seed must pass every gate.
- **Capacity-feature ablation.** Each model seed is retrained and evaluated with
  `path_capacity_mbps` zeroed (`ppo-no-capacity`); the paired reward delta and its interval are
  reported for attribution. A missing ablation fails completeness.
- **Wider test seed sample.** At least 24 paired test seeds per profile, spread over at least
  500 seeds of the test split (not a contiguous block), disjoint from every seed of any
  historical plan, ledger or summary (`reserved`).
- **Intervals.** Two-sided 95% Student-t intervals of paired deltas with `df = pairs − 1`
  (computed from the per-episode outcomes, never taken from a report).

## Gates (per model seed)

1. Reward vs every baseline: mean paired delta > 0.02 **and** interval lower bound > 0.
2. Held-out profiles only, reward vs `capacity-oracle`, `capacity-aware-ospf`, `heuristic`:
   interval lower bound > 0.
3. Nominal OSPF: goodput interval lower bound > 0 and ICMP RTT interval upper bound < 0.

`qualified` requires complete, paired, valid outcomes and every gate for every model seed.
Against the capacity oracle, argmax(capacity) has a paired delta of exactly zero, so gate 1
fails deterministically; with independent session noise each model seed can pass only by a
chance excursion above the 0.02 margin, and all five must do so. A result never sets
`safety_calibrated` or `autonomous_activation` (confidence calibration is separate; C17).

## Prerequisites before a successor campaign

- The C23 successor lab (`emulation/Dockerfile`) needs its own fresh qualification. The ADR024
  runner cannot use it: the qualified checkpoint and frozen client are bound to the frozen v4
  lab environment spec, so `scripts/adr024_campaign.py` launches only the recorded frozen
  image, privileged, with `NANFO_LAB_FROZEN=1`.
- A successor campaign runner must embed `protocol()` unchanged in its plan before any
  training, run all baselines and the ablation in the same lab, and pass `evaluate()` the raw
  per-episode outcomes.
