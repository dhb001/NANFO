# ADR014 Test-Only Continuation

Explicit parent/user authorization permits test-only selection from the existing
128/256/384-transition validation-qualified models. No new training, validation
collection, hyperparameter changes or model updates. Original stage artifacts and
checkpoint-bound `src/nanfo_routing/**` remain unchanged.

## Frozen Selection

Highest existing qualified validation mean reward, lower transitions breaks ties.
Independent reconstruction of all three qualifications selects384 transitions:
`artifacts/adr014-001/train-06/checkpoint.ptz`.

Checkpoint SHA256:
`5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`.

The new immutable `plan.json` and `selection.json` explicitly record that the parent
waived the original512-transition selection minimum for this test-only stage. They
reference/hash the original plan and evidence, not a forged replacement plan.
Original unused test ledger is verified before selection. Original artifacts are
hashed and checked before every session; selection is never rerun after test begins.

## Test Protocol

- Exactly12 reserved seeds3900..3911 per method, balanced stationary path0/path1.
- Four decisions/episode, two-second requested windows, original measured reward,
  actual sender-duration goodput and verified-drain endpoint loss definitions.
- Fixed random order seed9142026, shuffled once: PPO, constant1, constant0,
  heuristic, actual OSPF. One randomized order reduces intentional order choice,
  but is not a counterbalanced repeatability experiment; wall-time drift remains.
- Unchanged image `sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff`.
- Total runtime3600 seconds including collection/audits, final120 reserved for
  cleanup; per-session CLI600 seconds, outer child660, bounded by work deadline.
  No speculative remaining-pipeline reserve that can block a useful test stage.
- Each attempted policy consumes its identity even on failure. No retries after
  invalid or unfavorable outcomes, no new output-directory escape hatch.
- PPO vs OSPF paired95% Student-t intervals use12 seed means, not240 windows as
  independent replications. Success requires goodput lower CI>0 AND ICMP RTT upper
  CI<0, with all12 pairs. Loss, route changes, reward and timing also reported.
- Scope: stationary2/20Mbps impaired capacities against frozen nominal-cost OSPF.
  Not capacity-aware OSPF, all networks, UDP echo latency, safety or autonomy.
- Two fresh process loads and101 identical warm/cold deterministic decisions use
  existing validation history, with exact action/value/probability reproducibility
  checked against the frozen CLI. Raw holdout replay checks every PPO decision.

## Implementation

`scripts/run_adr014_holdout.py` is outside the hashed model package. It adds an
explicit test-only admission ledger and calls the existing frozen CLI parser and
session function with normal evaluate/test arguments. It does not patch any model
or qualification function, rewrite source, relabel test as validation, or reset
the original campaign deadline. The new admission layer replaces only the expired
original collection admission, under the explicit continuation authorization.

The current model package is verified byte-for-byte against original snapshot and
runtime. No alternate snapshot loader is needed. New runner hash is frozen too.
Existing supervisor process-group, semaphore, resource/disk caps and exact
ID/name/image/campaign-label cleanup and asynchronous auto-removal wait are reused.
One new fixed directory and ledger, no automatic restart or promotion.

## Commands

From `ai-engine/`, exact durable launch:

```bash
systemd-run --user --unit=nanfo-adr014-holdout-001 \
  --property=Type=exec --property=WorkingDirectory=/home/DHB/Documents/NANFO/ai-engine \
  --property=RuntimeMaxSec=3600 --property=TimeoutStopSec=120 \
  --property=KillMode=mixed --property=Restart=no --property=CPUQuota=200% \
  --property=UMask=0077 \
  --property='ExecStopPost=/home/DHB/Documents/NANFO/ai-engine/.venv/bin/python /home/DHB/Documents/NANFO/ai-engine/scripts/run_adr014_holdout.py cleanup' \
  /home/DHB/Documents/NANFO/ai-engine/.venv/bin/python \
  /home/DHB/Documents/NANFO/ai-engine/scripts/run_adr014_holdout.py run \
  --parent-approved-test-only
```

```bash
.venv/bin/python scripts/run_adr014_holdout.py status
.venv/bin/python scripts/run_adr014_holdout.py stop
systemctl --user stop nanfo-adr014-holdout-001.service
.venv/bin/python scripts/run_adr014_holdout.py cleanup
```

Service manager stop cleanup can finish after its runtime cap if Docker/kernel
hangs; normal work reserves120 seconds inside the cap. No unrelated container is
stopped. Terminal status and cleanup errors remain visible.

New evidence directory: `artifacts/adr014-holdout-001/`. Results are not claimed
until its five sessions and `test-report.json` exist and have been reconstructed.
