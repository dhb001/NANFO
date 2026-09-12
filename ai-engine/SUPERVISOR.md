# Two-Hour Training Supervisor

Operator-authorized ADR011 experiment only. Implementation and offline verification
do **not** launch a campaign. There is no systemd installation, background start,
Docker build/pull, test-set evaluation, production action, or automatic restart.
The parent operator launches and owns the systemd unit.

## Frozen Experiment

- Total budget: **7200 seconds**, including exclusivity/image checks, lab startup,
  calibration, baselines, training, validation, evidence audits, and cleanup.
- Work deadline: **7080 seconds**. The last **120 seconds** are reserved for
  graceful child termination/close and owned-container cleanup. Each Python
  session has both `--budget-seconds 600` and a supervisor process deadline.
  No new round starts with less than **1500 seconds** before the work deadline:
  two 600-second session bounds plus 300 seconds of startup/cleanup/audit headroom.
  This conservative admission rule can reduce completed rounds; it does not use
  optimistic measured timings to admit another round or extend the deadline.
- Maximum eight rounds, each 12 training episodes x four decisions = 48 transitions,
  then six validation episodes x four decisions = 24 transitions. Model seed 42,
  rollout 16, five-second windows. Model/runtime defaults are not tuned mid-run.
- Training-only calibration: constants 0 and 1 on seeds **1001/path0** and
  **1002/path1**. Raw evidence must confirm stationary background placement and
  matching offered schedules. The alternate route must improve mean decision
  reward by **more than 0.02 in both directions**, or training is refused with
  measured diagnostics. This checks a meaningful signal, not proven learnability.
- Baselines: constant0, constant1, heuristic, once each on fixed validation seeds
  **2200..2205**. Mapping: path1, alternating, burst, overload, low, path0.
  PPO validation repeats exactly these seeds/horizon/windows in a fresh process.
- Training seeds: **1200..1295**, 12 disjoint seeds per round; all six scenario
  families twice per block. Calibration and validation seeds never train PPO.
  **No test split is touched.** Validation reuse is explicitly model selection.
- Stop for low quality after at least three rounds/144 transitions if the best
  validation mean has not beaten the better constant baseline by more than 0.02.
  Otherwise stop after three rounds without a greater-than-0.02 improvement over
  the last significant best, subject to the same minimum. Worse validation never
  replaces the actual best checkpoint. These rules are not convergence claims.
- Resume is allowed only **within this live campaign**, from the preceding
  successfully trained and validated block. Restarting the supervisor on the same
  output is refused. There is no failed-step retry, mid-episode resume, deadline
  extension, or synthetic measurement fallback.

Historical live timing suggests roughly 430 seconds/train block and 220 seconds/
validation session, plus startup/audit costs. Calibration adds roughly 150 seconds
and the three baseline sessions roughly 660 seconds. Eight rounds are a ceiling,
not a promise; time, quality, disk, or error gates may stop much earlier.

## Ownership And Limits

The supervisor holds `/tmp/nanfo-training-supervisor.lock` across the campaign and
a private per-run lock. Lock files are never unlinked; file descriptors are not
inherited by children. A lock owned by a different user fails closed. Existing
compose/manual/experiment containers, pinned-image containers, and a manual journal
block startup. The same checks precede every new owner. Other launchers do not
honor this new lock, so operators must still avoid concurrent manual lab starts.

Every session uses `docker run --detach --rm --pull=never`, the exact supplied
local image ID, and `nanfo-training-<32-hex-campaign-id>`. Docker writes the full
container ID to a session-specific cidfile. Cleanup checks this exact ID, name,
image ID and `org.nanfo.training.campaign` label using Docker inspect before
`docker stop --time 20 <captured-id>`. It never stops by name, never stops
`nanfo-experiment`, and never invokes compose down or global experiment-stop.
After stop, asynchronous auto-removal is polled by exact captured ID for at most
30 seconds, bounded by the existing hard cleanup deadline, with heartbeat updates.
The same bounded absence wait handles inspect/stop command failures racing with
removal; neither action is retried. Only a successful Docker query confirming
absence completes cleanup. Query failures, mismatched IDs, ownership mismatches,
or continued presence at the deadline remain errors, never permission for broad rm.
Missing ownership proof or unavailable Docker fails closed and remains an
operator-visible error, not permission to stop an unrelated container.

The existing Mininet image **requires a privileged container** and runs its lab
process as container root. The supervisor itself is a normal user process, not
root. Isolation is the established disposable lab model, not a hostile-code
sandbox: network `none`, private PID namespace, no host networking, physical
interface, Docker socket, host root, code, results, commands, or credential mounts.
The only bind mount is the private `run/lab-output` at `/output`; `/results` is not
mounted. Image ID provenance is passed explicitly. Docker limits are CPU 2,
memory/swap 768 MiB, PIDs 256, and 64 MiB tmpfs each for `/run` and `/tmp`.
Container logs rotate at 2 MiB x two files. The parent applies **separate AI CPU
limits**; its cgroup quota does not limit Docker's daemon-managed container.

Run directories must be new private directories directly inside
`ai-engine/artifacts/`, with simple names and no symlink ancestors. Paths, labels,
cidfiles, and locks are validated. Evidence files are retained, never deleted or
truncated to make room. stdout/stderr are drained to per-command logs, rotating
at 1 MiB x two files each; machine stdout over 1 MiB is an error. Disk scans before
commands and every two seconds fail closed at 960 MiB, leaving 64 MiB within the
1 GiB budget for final artifacts. Symlinks, hard links, nonregular files, unreadable
directories, and excessive file counts abort. This is a monitored bound with
headroom, not a filesystem quota; enforce an external quota if adversarial or
unbounded writers are in scope. Per-session JSONL also has its existing 64 MiB cap.
At the maximum plan there are 830 measured reset/decision windows across 21
sessions, up to 384 training transitions. Actual byte counts, not an assumed
fixed measurement size, decide disk admission.

SIGTERM/SIGINT and `stop.request` stop new work. The supervisor signals only its
currently held child process group, allows up to 50 seconds for the CLI's protocol
close, then kills the group if necessary and cleans the verified owned container.
Saved PIDs are never signaled. Network/Docker loss aborts immediately without
replaying a step; if Docker remains unavailable, cleanup cannot be verified and
the error must be reconciled after connectivity returns.

## Commands

Run from `/home/DHB/Documents/NANFO/ai-engine`. Before launch, the parent verifies
the intended local image and current non-learning lab readiness. The image below
is the recorded V2 image; use a different exact **local** ID if the approved image
has changed. The supervisor checks the pin but never builds or downloads it.

Read-only plan, safe to run without Docker:

```bash
uv run --locked --offline python -m nanfo_routing.supervisor run \
  --operator-experiment --dry-run \
  --image-id sha256:a9721d734aac37319794ba4756302c5162c075887cfd297075bf2dd03f324c6f \
  --output artifacts/training-two-hour-001
```

Exact foreground command for the parent to wrap, **not executed by implementation**:

```bash
/home/DHB/Documents/NANFO/ai-engine/.venv/bin/python -m nanfo_routing.supervisor run \
  --operator-experiment \
  --image-id sha256:a9721d734aac37319794ba4756302c5162c075887cfd297075bf2dd03f324c6f \
  --output /home/DHB/Documents/NANFO/ai-engine/artifacts/training-two-hour-001
```

Suggested parent-owned user unit invocation, **not executed here**:

```bash
systemd-run --user --unit=nanfo-training-two-hour-001 \
  --property=Type=exec \
  --property=WorkingDirectory=/home/DHB/Documents/NANFO/ai-engine \
  --property=RuntimeMaxSec=7200 \
  --property=TimeoutStopSec=120 \
  --property=KillMode=mixed \
  --property=KillSignal=SIGTERM \
  --property=SendSIGKILL=yes \
  --property=Restart=no \
  --property=CPUQuota=200% \
  --property=UMask=0077 \
  --property='ExecStopPost=/home/DHB/Documents/NANFO/ai-engine/.venv/bin/python -m nanfo_routing.supervisor cleanup --output /home/DHB/Documents/NANFO/ai-engine/artifacts/training-two-hour-001' \
  /home/DHB/Documents/NANFO/ai-engine/.venv/bin/python -m nanfo_routing.supervisor run \
  --operator-experiment \
  --image-id sha256:a9721d734aac37319794ba4756302c5162c075887cfd297075bf2dd03f324c6f \
  --output /home/DHB/Documents/NANFO/ai-engine/artifacts/training-two-hour-001
```

`KillMode=mixed` delivers TERM to the supervisor first; it owns graceful child
termination. The service manager kills remaining AI cgroup processes on stop
timeout. `ExecStopPost` is the separate, ID/label-checked Docker fallback because
Docker containers live outside that cgroup. It refuses cleanup while the supervisor
still holds the run lock. Post-stop recovery has its own bounded 110-second cleanup
allowance and **never starts training or extends the campaign**. RuntimeMaxSec
initiates service termination at 7200; systemd's stop phase may finish afterward.
The child's normal work cutoff at 7080 reserves time to finish before that cap.
No userspace code can guarantee cleanup at a deadline if Docker/kernel hangs.

Status is read-only, with two-second heartbeat, stage, active child PID/command,
captured container ID, fixed deadlines, completed rounds/transitions, latest child
progress/evidence bytes, last validation reward, baseline means, best pointer,
stop reason and cleanup error. Stale heartbeat is reported without probing a saved
PID. Stop only writes a validated request file; parent service stop is immediate:

```bash
uv run --locked --offline python -m nanfo_routing.supervisor status --output artifacts/training-two-hour-001
uv run --locked --offline python -m nanfo_routing.supervisor stop --output artifacts/training-two-hour-001
systemctl --user stop nanfo-training-two-hour-001.service
uv run --locked --offline python -m nanfo_routing.supervisor cleanup --output artifacts/training-two-hour-001
```

`plan.json` is written before any Docker command and records image/config, source
hashes and seed/scenario mapping. Source drift before a new session aborts. Keep
the environment/source tree unchanged while a campaign runs. `best.json` points
to the best fully validated checkpoint and records bundle/weight/evidence hashes;
no unrestricted pickle is introduced. Every selection uses the existing report
reconstruction to validate raw window evidence, rewards, counts, close, schedules
and provenance. Original logs/checkpoints remain in their session directories.

## Verification

```bash
uv run --locked --offline pytest -q
uv run --locked --offline ruff check .
uv run --locked --offline ruff format --check .
```

Tests use mocked Docker/subprocess/time and explicitly offline transport fixtures.
They are supervision/contract verification, never evidence of measured training,
policy quality, a live systemd launch, or successful runtime container isolation.
