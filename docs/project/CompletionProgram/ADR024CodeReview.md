# ADR024 focused independent code review

Date: 2026-09-20. **Decision: APPROVE the reviewed software scope.**

No concrete regression was reproduced that grants rebuilt-image qualification
from a dishonest report, bypasses the admitted seed-reservation boundary, fits
calibration bounds on holdout outcomes, or understates the v2 burst bound through
a changed dispatch horizon. **257 tests passed; 2 opt-in evidence tests skipped.**
This includes 38 independent checks written for this review under `/tmp/opencode`.

## Scope and preserved decisions

Reviewed ADR-024, including the rebuilt-image amendment, against the current
working-tree implementation:

- `backend/scripts/frozen_live_inference.py`: new rebuilt plan/capture helpers,
  original report reconstruction and shared benchmark gates.
- `backend/app/modules/autonomy/{registry,live_schemas,model_provider}.py`:
  parent/derived lineage, evidence admission and qualification-result binding.
- `backend/app/modules/autonomy/{safety_installation,calibration_verification,
  calibration_verification_models,safety_provider,causal_frames}.py`: versioned
  service profiles, independent campaign verification and causal observation time.
- Supporting frozen ADR014 report/loader code, qualification import protocol,
  provider-state binding, receiver service checks, and native clock/counter adapters.

**Findings 1–11 in `ADR023Review.md` remain closed.** Relevant existing authority,
plan/delay and final-checkpoint regressions passed in this run. This focused review
does not reclassify unrelated historical findings or replace their closure evidence.

Only this report was added to the repository. Review tests and mutated copies were
confined to `/tmp/opencode`; original campaign/checkpoint bytes were read-only.
No infrastructure, service connection, privileged acquisition, source-code edit,
trust installation or dispatch was performed.

## Findings

**None requiring changes within the requested scope.** The following evidence
supports that disposition.

### 1. A passing report cannot substitute for matching raw evidence

`registry.py:39–54,83–101` checks both manifests and requires complete `weights.pt`
byte equality. The only permitted manifest difference is a different, well-formed
`lab_provenance.lab_image_id`; source, optimizer/RNG payload and other manifest
fields cannot be changed through this lineage route.

`live_schemas.py:71–85` requires parent, lineage, seed-audit and all five attachment
references specifically for the rebuilt protocol. `registry.py:103–111` reads the
pinned evidence, and `frozen_live_inference.py:105–147` invokes the unchanged
original report implementation with the derived checkpoint. That implementation
reconstructs measurements/rewards and replays deterministic PPO decisions
(`ai-engine/artifacts/adr014-001/source/cli.py:524–730`). Qualification gates consume
the reconstructed result, not producer qualification flags.

The additional capture check binds each raw measurement and summary to the derived
image/spec and requires all 60 measurement windows per policy to follow attachment
(`frozen_live_inference.py:72–102`). Provider receipts also bind the qualification
protocol and parent digest (`model_provider.py:114–126`).

Independent offline results using retained evaluation-002 and the real frozen
loader/report, without mocking either:

| Case | Observed result |
|---|---|
| Original derived lineage and complete five-policy evidence | Accepted by actual `validate_benchmark` |
| Rehashed report with reward delta changed to 999 and `qualified=true` | `live_benchmark_raw_reconstruction_mismatch` |
| Passing saved report plus wrong image in one raw measurement; raw/summary/attachment references updated consistently | `live_rebuilt_raw_capture_before_plan_or_wrong_runtime` |
| Rehashed PPO decision probabilities changed to `[0.5,0.5]` | Original loader/report rejects: `checkpoint does not reproduce measured decisions` |
| Weakened constant-policy threshold, plan declared after attachment, or historical reserved test seeds | Rejected by rebuilt semantic gates |

Existing lineage tests additionally reject non-image manifest changes and missing
protocol-specific references. All original constant-policy, OSPF and directional
threshold tests passed.

### 2. Seed audit checked against historical bytes, not accepted as a claim

The runtime helper checks the audit pin, selected/reserved disjointness, document
seed union, mandatory historical test seeds and parent training seeds
(`frozen_live_inference.py:32–60`). A private audit omitting the required reservations
was rejected with `live_rebuilt_seed_audit_incomplete`.

For the actual campaign, this review separately enumerated every JSON/JSONL file
under `ai-engine/artifacts` and `emulation/output`, checked exact inventory equality
and each document digest, then extracted seed fields from the original bytes with
an independent iterative traversal. Results:

- **5,090 documents**, with no duplicate or missing inventory entries.
- **1,342 distinct reserved values**, exactly matching the retained audit union.
- Selected **3003–3014** match the plan and are disjoint from that union.
- Audit bytes match the plan's `seed_audit_sha256`.

The runtime helper does not crawl historical roots or discover concurrent temporary
campaigns; completeness of that externally admitted inventory and the operational
reservation/attempt ledger remains the established operator-review boundary. The
checks above independently verify the retained historical inventory, not a global
claim about every possible reservation. No new self-approval route was found.

### 3. Post-fit changes do not inherit existing admission

Network configuration is referenced by the externally preregistered protocol.
`qualification_protocol.py:121–145,197–225` checks that receipt before importing
complete original instrument records. `calibration_verification.py:120–252` checks
fixed bounds over both splits; it contains no fitting step. Installation repeats
verification, including the conservative v2 runtime projection
(`calibration_verification.py:355–399`).

Independent tests established that:

- Changing a bound after capture and rehashing the configuration, protocol and
  campaign cannot reuse the original preregistration receipt: import rejects with
  `protocol_not_externally_preregistered`.
- Increasing holdout arrivals from 10 to 11 bytes while preserving counter
  conservation makes v2 empirical acceptance fail with `arrival_inequality_failed`;
  the verifier leaves the original configuration unchanged.
- Rebuilt benchmark threshold/chronology changes fail independently of saved
  qualification claims; parent/derived tensor equality prevents training changes
  being disguised as image-only rebinding.

These results retain the existing externally admitted chronology and attempt-history
boundary; they do not infer historical honesty from a producer timestamp alone.

### 4. Burst and time mappings stay conservative within the installed scope

`calibration_verification.py:83–117` maps upper service to
`min(capacity, outward(rate + burst/H))`. Busy-period available lower service maps
to **zero** for prospective runtime bounds. Nominal shaping rate remains separate
from physical capacity. Per-queue original values and service-evidence references
are checked at installation (`safety_installation.py:42–82`).

The provider uses exactly installed **H** (`safety_provider.py:140–149,217–235`).
`LoadedCalibration.validate_action` rejects a different H and checks exact mapped
bounds (`calibration_verification.py:283–317`). The wire guard repeats those checks
(`execution_contract.py:28–55`), and `ReceiverJournal.checkpoint` calls it before
authority/device mutation (`execution.py:46–65`). Thus a smaller measurement window
does not permit reuse of the full-H burst-equivalent rate for shorter dispatch.

Independent exact-rational cases covered fractional rates/bursts, H of 0.125/1/3
seconds and physical-capacity saturation: serialized upper service times H never
fell below `min(capacity*H, rate*H + burst)`. Alternative dispatch horizons were
rejected by provider, calibration and wire checks. Existing tests also verify
heterogeneous per-queue uncertainty, profile tampering, zero-lower-service drift
refusal, receiver ordering and unchanged v1 serialization.

For v2 causal time, `native_qualification_clock.py:18–40` derives the observation
from the raw integer endpoint, conservatively floors datetime/binary64 time and
retains total quantization uncertainty. `causal_frames.py:75–110` checks that binding,
raw digest and capacity-scaled error allowance; the native adapter independently
checks integer-clock ordering and float projections. Eleven independent submicrosecond
boundary cases covered both representations. A pinned instrument with zero error
allowance for a nonzero quantization interval was rejected. Existing altered-raw,
unrelated-observation and native-clock tampering tests also passed.

The safety certificate remains observation-anchored and endpoint-scoped. This
mapping review establishes neither a shorter-subinterval service guarantee nor a
hard future scheduling deadline.

## Reproduction and results

From the repository root, using the existing AI environment:

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  ai-engine/.venv/bin/python -m pytest -c /dev/null -q -p no:cacheprovider \
  --basetemp=/tmp/opencode/adr024-focused-benchmark-tests \
  /tmp/opencode/test_adr024_focused_benchmark.py
```

Executed in two stages: the first eight benchmark tests passed in 46.12s; the
subsequently added historical seed reconstruction passed in 29.67s (`-k
seed_reservations_reconstructed`, eight deselected). **9 independent checks passed.**

From `backend/`:

```bash
PYTHONDONTWRITEBYTECODE=1 poetry run pytest -c pyproject.toml -q --no-cov \
  -p no:cacheprovider --basetemp=/tmp/opencode/adr024-focused-safety-tests \
  /tmp/opencode/test_adr024_focused_safety.py \
  tests/unit/test_rebuilt_qualification.py \
  tests/unit/test_native_qualification_installation.py \
  tests/unit/test_native_qualification_review.py \
  tests/unit/test_autonomous_causal.py \
  tests/unit/test_adr023_review_autonomy.py \
  tests/unit/test_autonomous_frr_final_checkpoint.py
```

**248 passed, 2 skipped in 3.94s**, including 29 independent safety/import/clock
checks. The skips were the environment-gated actual-derived-artifact test and
actual native-v2 causal replay receipt test. The derived artifact was exercised
directly by the independent benchmark suite; authentic native-v2 causal replay was
not supplied to this test run. `git diff --check` passed.

## Approval boundary

Approve the derived-registry validation and v2 safety burst/time software scope
reviewed here. Preserve the existing native campaign classification as
**`native-driver-verified` manual isolated-emulation evidence**. This review grants
no joined learned-model/causal-safety/native-autonomy qualification, calibration
installation, physical-network/RF claim or new safety-threshold allowance.
