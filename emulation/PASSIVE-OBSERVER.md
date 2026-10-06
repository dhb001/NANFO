# ADR023 passive measured-feed bridge

`passive_observer.py` is a **read-only measurement consumer and protected snapshot
publisher**, run in the backend operator environment. It does not import or change
the emulation experiment, start a lab, connect to its socket, issue reset/step,
probe hosts, change routes, terminate senders, or train a model. Initial implementation
did not launch a lab. Subsequent explicitly authorized serialized acceptance passed:
`docs/project/CompletionProgram/ContinuousAI.md` records real fresh recommendations,
unchanged30s freshness, raw evidence and exact cleanup; the passive bridge itself
continues to issue no control calls.

## Why direct passive polling is not the frozen model contract

The preserved ADR014 v4 checkpoint requires actual `Request` + `Response` frames
with seeded stationary workloads, two sender/receiver payload counts and durations,
foreground ping RTT/loss, eight interface counter intervals, queue peaks, both
capacity readbacks, exact bidirectional Linux policy-route readbacks, and verified
post-sender drain sweeps over all22 interfaces. `Experiment.measure` starts/stops
UDP/ping and applies route/workload settings. Its only wire commands are reset,
step, close; there is no passive observation request. Ping itself generates traffic.
Counter/qdisc reads cannot manufacture sent-packet totals, offered load, verified
outage RTT, drain results, seeded workload identity, or actual request history.

Existing frozen `LoggedTransport.exchange` **already** writes the real request and
response into an append-only `evidence.jsonl` immediately after receipt. This is the
implemented source. The lab's `experiment-UUID-index.json` files contain only Data,
not the actual request, so this bridge deliberately does not wrap them in fabricated
requests/responses. Frozen source files and source fingerprints remain untouched.

Current checkout `experiment.environmentSpec('matched')` produces **v5**. The selected
ADR014 checkpoint binds **v4** and its exact lab source/image provenance. A v5 feed
is rejected even for superficially similar path0/path1 values. Parent must use the
preserved, hash-matched v4 artifact/image for a compatible acquisition campaign.

## Exact startup contract

Use existing `NANFO_LIVE_MODEL_REGISTRY`, `NANFO_LIVE_MODEL_REGISTRY_SHA256`,
`NANFO_MODEL_ROOT`, `NANFO_MODEL_PYTHON`, `NANFO_LIVE_OBSERVATION_ROOT`. The private
registry selects the network/workspace and target snapshot path. No new main,
deployment or application settings integration is required.

Provide a protected independently pinned `Admission` JSON (schema in the module):

* version: `nanfo.passive-feed-admission/v1`;
* network_id, workspace_id, registry_sha256;
* feed_path: absolute protected path of the **current evaluation** evidence.jsonl;
* session_sha256: SHA256 of the exact first `session` JSON line, excluding newline;
* server_pid: host-visible PID of the actual admitted measurement server;
* server_start_ticks: `/proc/<pid>/stat` field22, excluding PID-reuse ambiguity;
* boot_id: `/proc/sys/kernel/random/boot_id`;
* time_namespace: `/proc/<pid>/ns/time` link value, e.g. `time:[4026531834]`;
* expires_at: aware UTC timestamp of admission expiry;
* max_clock_drift_seconds: positive, at most0.25;
* max_delivery_seconds: positive, at most10;
* authorization: `observe-existing-measured-feed-only`.

These identity values are operator-bound, not accepted from a frame. Admission must
identify the real server, not the reader process. Header must declare evaluation,
matched mode,2s windows,4steps, generalization=false. Training sessions are rejected.
Feed and ancestors must be root/service-owned, non-group/world-writable, nonsymlink.
The operator has to provide read-only log access without granting lab control.

After the parent has separately admitted the measurement producer:

ADR-028: the implementation lives in the backend
(`app.modules.autonomy.experimental.passive_observer`); `emulation.passive_observer` is
only a host-side compatibility shim and is not part of the stdlib lab package.

```sh
PYTHONPATH=backend:. /path/to/backend/python -m app.modules.autonomy.experimental.passive_observer \
  --admission /protected/passive-admission.json \
  --sha256 <independently-provisioned-admission-byte-hash> \
  --duration-seconds 300
```

This command does not start the producer. It supports1..3600seconds, at most256
published frames per invocation,2MiB per input line, bounded polling and one writer
per snapshot via a file lock. Repeated campaigns require renewed explicit admission.

## Clock, freshness, validation and failure semantics

Attach at EOF; skip a partially written initial line. No earlier history is ingested.
Capture a wall/monotonic anchor **after attachment**. Every admitted measurement's
post-control start must occur after that anchor. Server and bridge must share boot
and actual Linux clock offsets. Distinct Docker time namespaces are admitted only
after both kernel monotonic/boottime offsets exactly match; foreign offsets reject.
Optional `NANFO_PASSIVE_PROC_SUDO=1` permits exactly one privileged read for a
root-owned admitted server: the fixed-argument helper `backend/scripts/nanfo_proc_timens.py`
installed root-owned as `/usr/local/libexec/nanfo-proc-timens` (`install -o root -g root
-m 0755`). It takes no arguments, reads one integer PID from stdin and prints only that
process's `ns/time` identity and `timens_offsets`. The exact sudoers entry (no wildcards;
`""` forbids every argument) is:
`nanfo-operator ALL=(root) NOPASSWD: /usr/local/libexec/nanfo-proc-timens ""`.
`sudo cat`/`sudo readlink` are never used. Server start ticks, boot, namespace,
wall/monotonic drift, admission digest/expiry and source inode/truncation are rechecked.

`window_started_at` and `observed_at` are anchor conversions of the original
post-control start/end, not file mtime, receipt time, or current wall time. Drain,
receiver completion and final counters must already have completed in that same
clock domain; delivery delay is bounded. End times strictly increase. Old traces
appended after attachment still fail their monotonic bounds. Reboot/PID reuse,
source rotation/truncation and clock steps stop the bridge, never reset its anchor
to make old data appear fresh. Frozen record values are never rewritten.

Each candidate is written privately, then passed through the existing isolated AI
interpreter, original frozen validator, checkpoint loader and deterministic inference
under Landlock/seccomp. No arbitrary feature conversion or relaxed validation is
used. Only after success and renewed installation/admission/freshness checks does
the bridge atomically publish the exact `PassiveSnapshot` expected by LiveObserver.
Its original request and response are preserved structurally, including numeric
values; the derived wrapper supplies scope, clock-derived times and canonical hashes.
This validation inference does not qualify the model, select an action for dispatch,
or bypass the backend's separate qualification receipt.

A receipt is durably written before each snapshot. It binds admission, registry,
snapshot/history/raw-line hashes, feed inode/device/offset, clock anchor and receipt
times, boot/server identity, original validation and `actuation:false`. Receipts are
retained as operator evidence; existing registry/provider interfaces remain unchanged.

Terminal/truncated/cleanup frames and close responses are rejected: the experiment
cleans its routes at the last step, so its last-history frame is historical only.
Bridge startup and normal exit/error/SIGTERM/SIGINT atomically replace the public
snapshot with a deliberately incompatible unavailable marker. Lost process/SIGKILL
cannot run cleanup; the consumer's existing exclusive freshness/hash checks bound
remaining stale exposure to its installed maximum age (at most30seconds). No receiver
should treat a recommendation as dispatch authority.

## Parent acquisition acceptance procedure (now verified under explicit authorization)

1. Serialize against autonomous/other experiments and admit preserved v4 FRR lab
   identity. Independently verify image, source, checkpoint and model registry.
2. Authorize an **evaluation/instrumentation-only** producer under its existing
   collection admission. Any reset, workload generation or fixed-policy step is an
   explicit active campaign action owned by that producer, not this passive bridge.
   Do not use this CLI to evade training/test-seed reservations or selection rules.
3. Attach to its newly declared protected evaluation log before a new complete
   measurement begins. Operator may need synchronization to avoid missing reset;
   a later nonterminal step can be consumed without inventing skipped history because
   the frozen history length is1. No extra test/measurement seeds are authorized here.
4. Verify a newly generated compatible snapshot, immutable receipt, actual confined
   inference and durable non-actuating recommendation. Test pause/staleness, clock
   change, incomplete/drain failure, source replacement, close and observer restart.

## Runtime mismatch choices and smallest compatible driver plan

**Keep qualified model/runtime:** integrate a separate governed Linux/FRR host-route
driver using the original `MatchedRouting` semantics. The execution workstream has
now added `autonomous_frr.py` (`LinuxFRRDriver`, runtime
`isolated-linux-frr-host-route/v1`); implementation is not qualification evidence.
Scope tables19110/19111 and
exact h1/h3 /32 source+destination in both directions at all routers on the selected
route. Preserve FRR OSPF/background paths; bind action0/1 to the checkpoint action_map.
Use new wrapper modules, not modifications to hashed `matched.py` or experiment files.
Reuse durable Autonomy authorization, resource fencing, revision/STOP/deadline checks,
pre-mutation journal, exact readback and compensating recovery. Require exclusive
ownership: the experiment server cannot concurrently control those routing tables.
An independent observation/instrumentation lifecycle must replace its reset/step
ownership before governed dispatch; the passive bridge alone cannot do that.

Even this closest action mapping still needs measured causal byte-queue/arrival/
service bounds, trusted safety calibration and independent verification that the new
driver reproduces the qualified action semantics. Historical benchmark qualification
alone does not certify the new execution adapter.

**Keep OVS driver:** supply an independently qualified checkpoint/feature contract and
measured action mapping for `isolated-ovs-autonomous/v1`, or a separately preregistered
runtime-equivalence evaluation with authentic evidence. FRR qualification cannot be
renamed to OVS qualification. No such campaign or training is performed/authorized by
this bridge implementation. Non-actuating FRR recommendations remain the immediate
compatible integration path.
