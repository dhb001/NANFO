# Two-Hour Background Training Campaign

## Replacement Run 002

Run 001 FAILED after its first successful eight-decision calibration session,
before any training. Root cause: Docker stop completed before asynchronous auto-
removal, and the supervisor treated a single still-present ID query as permanent
cleanup failure. Post-stop cleanup verified removal. Original artifacts are intact.

Cleanup now polls the exact captured ID for at most 30 seconds, bounded by the
remaining cleanup deadline. Ownership mismatch/query errors still fail closed;
no broad removal, step retry or failed-campaign resume was added. Regression gates:
186 AI/supervisor tests passed, Ruff and formatting passed.

Replacement service `nanfo-training-two-hour-002.service` launched 2026-09-09
21:32:38 EAT, fresh two-hour cap about 23:32:39 EAT (cleanup reserve unchanged).
Output: `ai-engine/artifacts/training-two-hour-002/`.
Observed beyond startup: both calibration directions passed, all three validation
baselines completed, first actual PPO update finished after 16 measured transitions,
service active and heartbeat fresh with no cleanup error. This is progress evidence,
not a promise the remainder will succeed or a useful policy is already trained.

Current commands (from `ai-engine/` for the Python command):

```bash
.venv/bin/python -m nanfo_routing.supervisor status --output artifacts/training-two-hour-002
systemctl --user status nanfo-training-two-hour-002.service
systemctl --user stop nanfo-training-two-hour-002.service
```

The original launch details below are historical and do not describe a running
service. Read run 002's status.json for current outcomes.

## Authorized Launch

User explicitly requested implementation and launch. Started 2026-09-09 at
21:12:17 EAT as user systemd service `nanfo-training-two-hour-001.service`.
Maximum campaign runtime: two hours, expected cap about 23:12 EAT. Work stops
120 seconds early to reserve cleanup; emergency service stop cleanup may exceed
the cap if infrastructure hangs. No automatic service restart or campaign resume.

Output: `ai-engine/artifacts/training-two-hour-001/` (private local artifacts,
ignored by Git). Authoritative live state is `status.json`, not this launch note.
Frozen workload/model/early-stop plan is `plan.json`; `best.json` appears only
after a checkpoint has passed validation. No test-set selection is performed.

## Policy

Train-only constant-route calibration must establish reward benefit in both
stationary bottleneck directions before training. Fixed validation baselines are
constant0, constant1 and the load-aware heuristic. Training blocks use new seeds,
48 measured transitions and rollout 16. Each completed block is evaluated on six
fixed validation scenarios. At least three rounds/144 transitions precede early
quality/plateau stopping. A plateau requires three rounds without >0.02 meaningful
reward improvement; low quality means no >0.02 advantage over the better constant.
Higher reward is better. Stop reasons do not imply convergence or deployment safety.

One invalid session, failed cleanup or infrastructure error stops the campaign
without retrying ambiguous network steps. The last fully validated best checkpoint
is retained. Total budget includes calibration, startup, baselines and evaluation;
1500 seconds must remain to admit another complete train/validation round.

## Resources and Ownership

Systemd limits AI CPU to two cores and memory to 2 GiB with no swap. Each private
lab container is separately capped at two CPUs, 768 MiB with no swap and 256 PIDs.
The established privileged lab is disconnected (`network=none`) and has no host
network/Docker socket/database credential mounts. Only the owned output directory
is mounted. Cleanup validates captured container ID, image, name and campaign label;
it never stops an unrelated manual/experiment container. Artifacts have a monitored
1 GiB limit, not a filesystem quota. Machine must remain running/awake.

## Status and Stop

From `ai-engine/`:

```bash
.venv/bin/python -m nanfo_routing.supervisor status --output artifacts/training-two-hour-001
.venv/bin/python -m nanfo_routing.supervisor stop --output artifacts/training-two-hour-001
```

Service-level commands from any directory:

```bash
systemctl --user status nanfo-training-two-hour-001.service
journalctl --user -u nanfo-training-two-hour-001.service --no-pager
systemctl --user stop nanfo-training-two-hour-001.service
```

Do not edit the AI/environment source or start another lab while the campaign is
running. Source drift aborts subsequent sessions. Closing this conversation does
not stop the service; user-manager shutdown, reboot or machine sleep can interrupt it.

## Verification

Supervisor/AI package: 173 tests passed; Ruff lint/format and whitespace checks
passed before launch. Reviewed and fixed auto-removing-container cleanup races and
insufficient round budget reservation. Actual service and owned Docker container
were observed running with a fresh heartbeat in `calibration-constant0`. No trained
checkpoint or campaign completion is claimed by this launch note. Final outcomes
must be read from the retained status, summaries, evidence and best pointer.
