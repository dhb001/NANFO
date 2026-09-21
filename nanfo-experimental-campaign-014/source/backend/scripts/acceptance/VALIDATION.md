# Step14 Executable Validation

## Diagnosed And Retested

2026-09-12 08:12-08:33 UTC: focused serialized reruns under a new 3600-second
overall authorization (later emulation-only attempts used reduced remaining caps).
All three previously failed stages now pass, without raising any assertion timeout,
changing traffic demand, retuning a model or repeating unrelated successful stages.

Final aggregate: **partial**, **22 passed / 0 failed / 9 blocked cases**;
**8 passed / 0 failed stages**, including the previously verified external alerts.

`/tmp/opencode/step14-7a3aa518d6da241690b38153bcd1716d/aggregate-final-retest.json`

SHA256: `8289430824f59f2ffc457d76fb6188f5a5711859acdd78aa45604c1e622786bb`.
The aggregate embeds prior failed rows in `supersessions` and hash-pins the new
attempt summaries. Original failed artifacts and intermediate failed diagnostics
remain unchanged; this is not a rewritten first-run success.

### Execution: Product Bug

Retained deadline job `03573b6f-6bdd-4bdb-8a6a-4368657d9d88` had a lab `failed`
receipt at 07:49:11.064068 UTC with `rollback.verified=true` and a real readback hash.
Its exact command mailbox contained `operation=cancel`. `ExecutionWorker._reconcile`
required a `cancelled` result whenever cancellation was requested, even though a
verified failed result already proved compensation. The lab intentionally retains
the original failed receipt on late cancellation of an inactive execution. The
worker therefore remained uncertain and republished cancellation forever.

Minimal runtime fix in `backend/app/modules/intent/worker.py`: accept a matching,
time-valid, safe `failed` OR `cancelled` terminal receipt when cancellation is
pending. Existing rollback/no-mutation proof, identity/time and lease checks remain.
Unverified compensation still stays uncertain and republishes only exact cancel.
The new positive regression failed before the fix (`uncertain` instead of `failed`);
its negative unverified counterpart passed and remains passing.

Live retest:
`/tmp/opencode/step14-787f7de1f6d937fdc71c477fd0ff2681/execution/result.json`.
The complete execution verifier passed, including final deadline compensation with
phase `failed`, verified rollback and readback SHA256
`240d8461f2622d2171a6c1811b45b8f07a8fabc0664db3c084edceff1d84f49f`.

### Override: Verifier Scheduling Race

Original recorded next authority check: 07:53:13.885819 UTC. Actual STOP request:
07:53:13.949267 UTC, already 63ms after that scheduled check. Capture then completed
07:53:16.194957 UTC. Sampling `next_check_at` once and sleeping until 300ms before it
did not account for Docker capture startup/child inspection latency. STOP had not
necessarily reached the recovery worker before the short capture ended. This was
not proof of failed physical compensation or ignored STOP.

Verifier fix: pause only its owned Autonomy recovery process after the completed
Intent lease has elapsed; wait for the unchanged persisted next-check deadline;
start real capture, observe actual capture children, commit the real STOP through
HTTP, then resume recovery. No DB time/status edits, extended capture duration or
looser assertions. The existing process cleanup resumes stopped children on errors.
An ordering regression protects pause -> capture -> STOP commit -> resume -> partial
assertion. The six-case live rerun passed unmodified physical/no-replay checks:

| Case | Trigger To Verified Restoration | Owned Flows After |
| --- | --- | --- |
| expiry_restart | 7.012452s | 0 |
| stop_during_restoration | 6.077202s | 0 |
| expiry_during_capture | 6.487455s | 0 |
| stop_during_capture | 7.974849s | 0 |
| lab_restart_holding | 7.050402s | 0 |
| actor_revocation | 9.171165s | 0 |

Both capture interruption responses were `passed=false,status=partial`, previous
capture evidence unchanged; final 6 executions cancelled, active=null, owned flows=0,
model inferences=0. Evidence:
`/tmp/opencode/step14-787f7de1f6d937fdc71c477fd0ff2681/operator_override/result.json`.

### Emulation: Verifier Consumer Contract And Throughput

The old verifier bypassed the event bus and invoked `_merge_handlers` list values
as callables. The initial adapter addressed that TypeError, but left a single serial
consumer directly repeating handlers, including expensive measured-alert ingestion
added by ADR019. Diagnostic rerun proved the equality assertion fired while delivery
was still progressing: expected3170, persisted1459, lag1891, pending70, zero handler
errors. Raw stdout/stderr was deliberately not retained, so no server-log cause is
invented; the new structured `persistence_diagnostic` establishes actual backlog.

A rejected intermediate fix drained every producer batch: exact694/694 persistence
then passed, but the long polling gaps missed the required measured queue peak.
That intermediate failure remains at `step14-136436ffa396475529d5600910274c00`.

Final verifier-only fix uses the real `process_entry` contract (all merged handlers,
completion markers and retries), bounded8-way concurrency across independent metric
series, FIFO series locks and batches capped100. The original0.6s producer polling
remains. Final drain uses the existing200*0.2s bound, not an enlarged timeout; any
dead letter still fails. Unit regressions require both zero lag and zero pending,
reject stalls at exactly200 polls, and reject consumer errors. No application
telemetry persistence, alert rules or event-bus behavior was changed.

Live retest:
`/tmp/opencode/step14-2eecc4662f898157f6622d2ee3ffdeed/emulation/result.json`.
Passed all source-value, ID, timestamp, duplicate, REST aggregation/bounds, graph
ownership, WebSocket and actor-revocation assertions: **2178 unique rows and matching
WebSocket frames**, zero duplicates, lag0/pending0, 9 nodes/11 edges. Measured maxima:
19.943285Mbps port throughput (not application goodput),98.084671% utilization,
33.59ms RTT,283178 queue bytes/100 packets,0% measured probe loss;19,186,000 delivered
bytes. The final implementation removes the redundant post-drain polling loop, so
there is one original40s drain bound, not two sequential wait allowances. Final code
was live-retested after that tightening; the earlier successful attempt is retained.

### Preservation And Alert Provenance

All new stage cleanups passed with empty leak/unknown/baseline-drift lists. The old
stopped lab full inspect hash remains
`178672b973d121c20629a2b0c94355b8ef6a21e5fb0d06fea7169e76e6a30d80`.
No old-container lifecycle operation occurred. Alert runtime/module hashes are
unchanged since the primary campaign. The current measured-alert verifier hash
`7979de021165c53ead65d7cfdf853667c0cb2258f9f0ab335ab3e6d526750a02` exactly matches
the source hash in the already-passed external adapter's `adaptations.json`.
Therefore its measured success is retained, not unnecessarily repeated. No training
or heldout evaluation was run. Focused final regression suite: **100 passed**;
scoped lint passes. Physical unimplemented cases still block overall completion.

## Authorized Live Result

2026-09-12: parent authorized live execution and the exact stopped-container
preserve-only exception. The primary seven stages all ran, followed by the standalone
measured-alert verifier after lock release. Aggregate: **partial**, 18 case passes,
4 case failures, 9 blocked cases. Stage counts: **5 passed, 3 failed**. No training,
heldout rerun, model retuning, shared migration or deployment config change.

Final hash-verified aggregate:
`/tmp/opencode/step14-7a3aa518d6da241690b38153bcd1716d/aggregate-verified.json`

SHA256: `5ab14134c95b1ab7f1fa32f5f378484e175dc080f79d19060ef23e6214e0e02b`.
Local hash integrity only; no cryptographic signature or external signer claimed.

| Stage | Actual Result |
| --- | --- |
| emulation | Failed. Initial legacy verifier called merged-handler lists as functions; acceptance-only adapter fixed dispatch. Isolated retry then reached real traffic/persistence but failed source/persisted sample-count equality. No fabricated pass. |
| execution | Failed final deadline-compensation terminal wait. Earlier actual worker SIGKILL/lost-result, QoS, reroute, cancellation and outbox replay assertions passed; retained as partial evidence. |
| operator_override | Failed STOP-during-capture assertion: capture completed rather than returning interrupted/partial. Earlier expiry/restart, STOP-during-restoration and expiry-during-capture physically restored 10 to 0 owned flows. Remaining cases not inferred passed. |
| actions | Passed existing actual partial-mutation/crash/deadline/uncertainty lab controls. |
| negative | Passed actual link-down, stale-controller and controller-disconnect preparation rejection/readback/recovered probes. |
| reports | Passed actual parsed PDF/CSV, checksum/size/tamper/tenant denial and worker gates; 5 disposable transaction tests, zero skips. |
| fixtures | 134 tests passed, zero skipped/failed/errors; alert/registry DB fixtures and unit checks, not measured traffic. |
| measured alerts (external) | Passed 26 actual counter samples, sustained breach/recovery, exact source/persistence equality, unchanged reverse duplicate replay, tenant denials, 2 history events and 2 matching audit events. |

Measured values retained even where the containing execution stage failed:

| Measurement | Actual Value |
| --- | --- |
| Baseline TCP receiver rate | 18.8044 Mbps |
| Multipath TCP receiver rate | 37.7984 Mbps |
| DSCP10 shaped / unclassified / restored UDP | 4.7591 / 17.7117 / 17.7116 Mbps |
| DSCP12 policed / unclassified / restored UDP | 4.8704 / 17.7127 / 17.7138 Mbps |
| Link-down / stale / disconnect fault-to-recovered-probe intervals | 8.8623 / 9.7438 / 11.8544 s, including deliberate 8s fault dwell |
| Recovered negative-case probes | 8 sent / 8 received per case |
| Measured alert breach | 7 observations over 11.024056s, threshold >=85% |
| Measured alert recovery | 7 observations over 12.031185s, threshold <70% |
| Workload stop to resolving observation | 12.934441s |
| Observed utilization range | 0.0023904% to 100.0305389%, 26 samples; raw value retained, not clipped |

External alert artifact:
`/tmp/opencode/step14-alerts-external-06ce1a8e5aaaaaf5b1452a62f1edf85c/measured-alerts-k52fhxhq/result.json`.
The first standalone attempt lacked repository `PYTHONPATH`; the second failed email
validation during binding. Acceptance-only AST adapter changed invalid `.invalid`
login fixture addresses to `.com`. No shared verifier edit, detector threshold,
measurement, offered load or workload duration change. Actual 22Mbps UDP ran 30s.

All primary stage cleanups and external cleanup passed. Primary/final baseline has
30 containers; no owned/unknown additions remain. The earlier admission-only baseline
had 31 and was not reused after drift. The preserved full ID
`1db3c959ff4f712da1d9f5674c120c900f7d5392d2236f6f3d41f68f3620ac55`
remained `exited`, name `nanfo-emulation-lab-1`, image
`sha256:215a5100a427ff3c43c69a5cf6910b49b8eaebcdbc72098b6363bfc8fa6f2f58`.
Full inspect SHA256 remained
`178672b973d121c20629a2b0c94355b8ef6a21e5fb0d06fea7169e76e6a30d80`.
Mounts are canonically sorted by destination because Docker returns their set in
varying order; no fields are discarded from the full inspect hash. Each stage has
`baseline-before.json` and `baseline-after.json`; old container was never started,
deleted, reconfigured or mounted by the campaign.

Infrastructure retries are separately retained. Actual primary stages ran roughly
07:45-07:59 UTC; separate alert success completed 08:05:34 UTC, within the authorized
two-hour ceiling. Primary command used a reduced remaining 5400s cap, 1000s per stage,
60s quiet gate; isolated emulation retry used 1800s cap; external alert cap 480s.
No successful stages were rerun for better measurements. Final own tests: **45 passed**;
scoped Ruff passes. Remaining physical load matrix/larger topology, DRL+safety,
repeated heldout and power control are blocked, not full completion.

## Earlier Build-Only Record

Date: 2026-09-12. Implementation and verification limited to acceptance-owned files.
Concurrent agent edits/migrations were observed and left untouched. **Live launch
is pending parent/operator authorization after agents finish.** No Docker command,
shared service change, migration, inference, training or heldout test replay was
executed during this workstream.

## Commands Run

From `backend/` using its Poetry interpreter:

| Command | Actual Result |
| --- | --- |
| `poetry run pytest scripts/acceptance/test_campaign.py -q --no-cov` | 41 passed; no skipped tests; final run 1.43s |
| `poetry run ruff check scripts/acceptance` | All checks passed |
| `poetry run python -m compileall -q scripts/acceptance` | Exit 0 |
| `git diff --check` | Exit 0; no whitespace errors reported |
| `poetry run python -m scripts.acceptance.campaign --plan --historical-json ../ai-engine/artifacts/adr014-holdout-001/test-report.json --historical-sha256 f323186fee013a3c55acac9e061500c2245c36976db01495a86f48a83c57392b` | Overall **partial**, 8 passed (7 modeled + 1 historical integrity reference), 0 failed, 23 blocked; no live execution |

Last plan manifest:
`/tmp/opencode/step14-127942dad5f25fc444db29b3e38c832a/manifest.json`

Last plan summary:
`/tmp/opencode/step14-127942dad5f25fc444db29b3e38c832a/summary.json`

The same directory contains seven generated fixture/model/trace artifacts and the
fsynced hash-chained status ledger. Historical DRL reference points to existing
`ai-engine/artifacts/adr014-holdout-001/test-report.json`, SHA256
`f323186fee013a3c55acac9e061500c2245c36976db01495a86f48a83c57392b`.
No historical bytes were changed or used to retune a policy.

## Tests Covered

Flag guard/no-resource behavior; exact command maps; isolated migration adapters;
single `0019` migration-head gate; source drift; Docker baseline/training/backend
rejection; full-ID + name + both labels + absent-from-baseline cleanup proof;
preservation of unknown containers; bounded process output and descendant timeout;
safe continuation after failure; blocking after uncertain cleanup/interruption;
private exclusive files/symlink rejection; durable ledger chain/status recovery;
no-output-overwrite; sanitized logs and negative assertion preservation;
zero-test/skip rejection; historical hash-only reference with no execution;
deterministic generated model fixtures with independent per-flow mass conservation.

## Pending Live Gate

The precise pending launch command, image pins, stage/environment map, inventory
and recovery procedure are in [README.md](README.md). Physical-capable cases are
link-down, stale-controller rejection, controller disconnection, process/lab
restart, unsafe dispatch/conflict/uncertainty rejection, overrides, rollback,
DSCP classes and telemetry pipeline. Reports can verify actual HTTP/download/worker
behavior from fixture sources. These capabilities are implemented, **not yet
measured by this campaign**. Existing scripts/images may expose new compatibility
issues on the actual run; no live success is inferred from adapter unit tests.

Physical low/ramp/burst/overload/multiple-bottleneck/larger-topology rows remain
blocked with separate modeled counterparts. Sustained measured lab alerts remain
blocked with separate fixture tests. DRL+safety, repeated heldout acceptance and
physical power control remain blocked. No combined all-passed network claim.
