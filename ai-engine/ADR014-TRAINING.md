# ADR014 Expanded Measured Training

Scope: `ai-engine/**` only. Disposable operator-authorized Linux/FRR experiments;
no production action, automatic autonomy, backend integration or promotion.
Historical ADR013 plans, checkpoints and outcomes are not rewritten.

## Frozen Plan

Authoritative executable plan: `nanfo_routing.expanded.frozenPlan()` (version4).
One fresh compact 16-input, separate32-unit actor/critic model, model seed44.
No hardcoded actor routing rule, supervised training, fixture warmstart, or
validation/test gradient updates. Baseline heuristic remains a separate comparator.

- Budget7200 seconds including startup, baselines, collection, audits and cleanup.
- Work cutoff7080 seconds;120 seconds cleanup reserve. Session CLI cap600 seconds,
  supervisor child cap660 seconds, additionally bounded by the work deadline.
- Calibration: constants on1580/path0 and1581/path1. Both measured alternative-route
  reward margins must exceed0.02 before training. This is action-effect evidence,
  not a learnability or convergence guarantee.
- First64 fresh on-policy transitions and four gradient updates precede any
  validation/baseline selection data. Their diagnostics are saved separately;
  the predeclared hyperparameters are not changed after viewing outcomes.
- Training: unique1600..1855, balanced path0/path1, four decisions, two-second
  requested windows. First512 transitions use1600..1727; full1024 use1600..1855.
  The256-seed range extends the suggested1600..1799 to support1024 transitions.
- Validation:2700..2707, eight seeds. Reserved test:3900..3911, twelve seeds.
  All ranges fixed before training; preparation checks prior training seed metadata.
- Resume/save every64 transitions; validation/qualification every128 transitions.
  Resume restores exact optimizer/RNG/config/source/spec and consumes next16 seeds.
  No campaign restart or failed-seed retry. Every parent block is audited.
- Rollout16, four epochs, learning rate0.003, gamma0.9, lambda0.95, entropy0.01.
  A four-decision stationary task justifies discounting distant value noise rather
  than default0.99;0.003 is the preselected diagnostic candidate for larger update
  movement. Neither is selected using validation/test outcomes. PPO losses, entropy,
  KL, clipping, gradient norm and explained variance remain in each training trace.
- No quality stop before512 fresh transitions (32 on-policy updates). Hard resource,
  invalid measurement, stop requests and action-effect failure still fail closed.
  At512, qualify or extend while best reward OR minimum directional probability
  improves by>0.02 comparing recent256 with preceding256 transitions, up to1024.
  Fixed argmax is not an early stopping condition.
- Before each128-transition pair, require1200 seconds plus1800 reserved for tests.
  This admission headroom is not a guarantee all stages fit; actual deadlines win.
- Baselines validation order: constant0, constant1, heuristic, unchanged OSPF.
  One pass each; repeatability is not established. Per-policy timing is retained;
  fixed order and wall-time drift remain limitations.
- QualificationV4: actual deterministic majority correct route in BOTH congestion
  directions AND mean reward advantage strictly>0.02 over BOTH constants. Synthetic
  pressure swap is diagnostic only. Full eight-seed paired curves are retained.
- Select highest eligible validation mean after512, earliest checkpoint breaks ties.
  Test order: OSPF, constant1, selected PPO, constant0, heuristic. Each exactly once.
  All test outcomes consumed, including unfavorable/invalid attempts; no retuning.
- OSPF improvement requires all12 seed pairs with goodput95% CI lower>0 and ICMP
  RTT95% CI upper<0. Intervals use seed means, not packets/windows as independent
  replications. Scope is stationary2/20Mbps degradation versus nominal-cost OSPF,
  not capacity-aware OSPF or general networks. RTT is ICMP, not UDP echo.

## Release And Ownership

Completed lab handoff: `emulation/DRAIN-V4-VALIDATION.md`. AI preparation independently
validated all six released raw windows and copied their exact spec/source/image
identity into `artifacts/adr014-release.json`; no new measurements were collected.
Late delivered packet counts are unavailable and stay null; final delivered totals
and actual sender duration remain independently checked. Verified drainage needs
two timed complete empty sweeps over all22 topology interfaces within three seconds.

Immutable image:
`sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff`

Spec:
`bb15142a19ed3ee87a6aec2c6f9109d789d9736a5e6afda826ad898ef5fe7200`

The extended supervisor reuses the existing bounded child process groups, global
and run locks, disk/log caps and repaired exact-ID asynchronous auto-removal wait.
Every new session starts a fresh `--rm --pull=never` pinned image with campaign
label, captured cidfile, network none, CPU2/memory768MiB/PIDs256. Container cleanup
checks exact ID/name/image/label, never another agent's lab. No emulation control
script or compose lifecycle calls. Source drift blocks new collection. Original
AI source and dependency lock snapshots are retained inside each run.

## Commands

From `ai-engine/`, release preparation (one-time, refuses overwrite):

```bash
.venv/bin/python scripts/prepare_adr014_release.py
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Read-only release/plan preflight:

```bash
.venv/bin/python -m nanfo_routing.extended_supervisor run --operator-experiment \
  --image-id sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff \
  --release artifacts/adr014-release.json --output artifacts/adr014-001 --dry-run
```

Durable bounded launch, with no restart and ownership-checked stop fallback:

```bash
systemd-run --user --unit=nanfo-adr014-001 \
  --property=Type=exec --property=WorkingDirectory=/home/DHB/Documents/NANFO/ai-engine \
  --property=RuntimeMaxSec=7200 --property=TimeoutStopSec=120 \
  --property=KillMode=mixed --property=Restart=no --property=CPUQuota=200% \
  --property=UMask=0077 \
  --property='ExecStopPost=/home/DHB/Documents/NANFO/ai-engine/.venv/bin/python -m nanfo_routing.extended_supervisor cleanup --output /home/DHB/Documents/NANFO/ai-engine/artifacts/adr014-001' \
  /home/DHB/Documents/NANFO/ai-engine/.venv/bin/python -m nanfo_routing.extended_supervisor run \
  --operator-experiment \
  --image-id sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff \
  --release /home/DHB/Documents/NANFO/ai-engine/artifacts/adr014-release.json \
  --output /home/DHB/Documents/NANFO/ai-engine/artifacts/adr014-001
```

Status and stop (no PID reuse hazards):

```bash
.venv/bin/python -m nanfo_routing.extended_supervisor status --output artifacts/adr014-001
.venv/bin/python -m nanfo_routing.extended_supervisor stop --output artifacts/adr014-001
systemctl --user stop nanfo-adr014-001.service
.venv/bin/python -m nanfo_routing.extended_supervisor cleanup --output artifacts/adr014-001
```

The service stop phase can exceed RuntimeMaxSec if Docker/kernel cleanup hangs;
normal work reserves cleanup inside7200. A cleanup error remains visible and never
authorizes broad container deletion. The foreground equivalent is the final Python
command above; it retains its own two-hour cap and signal handling.

Evidence: `plan.json`, `training-plan.json`, `training-plan.collection.json`,
`status.json`, `curves.json`, block traces/checkpoints/audits, qualifications,
`selection.json` and `test-report.json` if reached. No output file means no claim
that the corresponding stage ran. Unit fixtures verify code only, not policy quality.
