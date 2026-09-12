# ADR-016: Balanced Long Refinement

- Status: Accepted under explicit user request to further improve the model without time restriction
- Date: 2026-09-10

## Purpose

ADR015 completed512 fresh transitions but its candidate did not meet replacement
thresholds. Independent raw replay verified modest gains and deterministic plateau.
Preserve incumbent ADR014 and candidate512, including all historical artifacts.
Continue in a separately frozen campaign, not by extending the completed ledger.

## Plan

Tensor-only warm-start from exact hash-verified ADR015 candidate512 with NEW Adam
and RNG, explicitly not optimizer resume. Retain PPO learning rate0.0005/gamma0.9/
lambda0.95/entropy0.01/clip0.2/four epochs/gradient norm0.5. Change rollout/minibatch
to32/32 so every update contains all eight profiles. Collect2048 additional fresh
on-policy transitions; evaluate predetermined1024/2048 checkpoints. No changed
reward, future actor inputs, supervised labels or test-based hyperparameter tuning.

New explicit seed namespaces: train10000..19999, validation20000..29999,
test30000..39999. These are confined to the new operator runner and versioned plan,
not silently admitted as old-checkpoint training seeds. All chosen seeds/profiles
must be checked against previous raw/success/failure ledgers before collection.
Use64 validation seeds (eight/profile). Freeze final128 seeds (sixteen/profile)
and balanced method-session order before first collection. Keep old3600..3623 closed.

Compare incumbent, candidate512, new qualified candidate, constants0/1, heuristic,
actual OSPF. Preserve meaningful gain and non-regression margins from ADR015; add
progress versus candidate512, not only the weaker incumbent. Validation selects;
final test cannot trigger training, retuning, repeated attempts or gate changes.

## Execution and Safety

Finite24-hour service cap including startup, baselines, training, validation and
final evaluation. Reserve time for complete test/cleanup stages; stop with explicit
insufficient-budget reason if admission fails. One owned isolated lab at a time,
CPU/memory/PID/disk limits, unique label/ID cleanup, bounded child timeouts and
graceful stop. No automatic restart, failed-step retry or unbounded continuation.
Persist progress, elapsed campaign duration and actual block counts correctly
across post-stop cleanup. Never modify checkpoint-bound source while running.

Qualification failure retains incumbent/default. A higher validation probability
alone does not count as model improvement. An active campaign is not a completed
result; publish exact status/stop commands and verify actual PPO progress after
launch. No production or autonomy provider is installed or enabled.
