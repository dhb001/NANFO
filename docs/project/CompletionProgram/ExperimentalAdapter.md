# ADR025 experimental adapter

## Campaign009 postrun integrity correction — tested source frozen

Offline final gates: **20 emulation tests pass; all5 independent reviewer integrity
probes pass;5 backend adapter tests pass; scoped Ruff and whitespace checks pass.**
This owner is frozen at the following exact SHA256 pins. No further implementation
edits or live acquisition by this workstream after publication.

| Source | SHA256 |
|---|---|
| `emulation/experimental_lab_contract.py` | `811aed1593dbafa0ed931dbc7697af8464f662234eeae4055516e7f633b24056` |
| `emulation/experimental_lab_runtime.py` | `b7af4548159f0c5be64314e38ec25c20c38af7636028de2c4c75c12eec611e1a` |
| `emulation/experimental_lab_receiver.py` | `30291515919c9250557c06591ef8c70cb006db364b86a1ff87cb29cea984b9c9` |
| `emulation/experimental_lab_operator.py` | `355d8e500286a23cff5e1de7e79540ad6d0ce7139bec92c3792c4ae46bb95c93` |
| `backend/app/modules/autonomy/experimental/adapter.py` | `30aa7c85fff25c05a8b945284af9543988650b995604b155eebf11e13370a728` |
| `emulation/tests/test_experimental_lab.py` | `3d3eb55110233efc9c12879c27a2357bf8c46a351266e5e808a427a9f1b0328f` |

IR-01: `state()` now returns a detached canonical JSON snapshot of **all** nested
owned/original/baseline/transcript/namespace values. Receiver stores detached
responses and returns detached first/replay/status values. Successor routing,
recovery, caller mutation and subsequent journal persistence cannot change retained
receipt bytes. Raw frozen frames are detached on acquisition too.

IR-02: the wrapper surrounds original `MatchedRouting.close()` with validation of
ALL reserved slots before its first deletion, including implicit error/terminal
cleanup. Every delete re-reads its slot after WAL/hooks/authority immediately before
the original delete. Unknown rule/route keys, extra rows, unowned reserved slots,
wrong tables, multipath/nhid/encapsulation/metrics and selectors (fwmark/fwmask,
iif/oif, uidrange, transport selectors, suppressors/inversion) are foreign and
refused. No broad cleanup runs on preflight conflict. Exact row identity requires
the original priority/table/src/dst and route table/dst/dev/gateway/static protocol.
Permitted explicit default representations only: rule flags=[], action=to_tbl,
protocol=boot, tos=0; route flags=[onlink], type=unicast, scope=global, tos=0.
Absent nonsemantic default keys are accepted; explicit route onlink is required
(missing/empty route flags are refused); alternate values are not. Actual campaign009
iproute2 rows have only required fields plus route flags=[onlink]. Read-only
ownership queries increase; original mutation argv/order remain unchanged.

### Campaign009 failure investigation — evidence limit retained

Read-only inspected root: `/tmp/opencode/nanfo-experimental-campaign-009/`, including
both heuristic cases' native journals, wire replies, exported inference/receipts,
controller exception chains, policies, cleanup and `postrun-reconstruction.json`.

- path0-1391 heuristic selected route1. Execute step1 succeeded: goodput4.912897Mbps,
  UDP loss0.160896, RTT61.204ms, ICMP41/48. The next verify reports
  `original_measurement_failed`; its failed step's raw error/counts are absent from
  exported evidence. A subsequent rejected heartbeat was returned as unbound
  `{error:request_rejected}`, which caused the misleading adapter
  `experimental_receiver_response_binding_invalid` exception. Fixed authenticated
  heartbeat rejection to return the exact bound response envelope; no authority is
  granted by this error path.
- path1-1392 heuristic genuinely selected the impaired route1 (2Mbps, unlike its
 20Mbps route0). Execute step1 delivered2.962144Mbps including transition service,
  UDP loss0.498277, RTT149.467ms, ICMP17/49; it passed the declared0.75 limits.
  Later verify reports `hold_measurement_failed`. Its new frame is absent, so it
  is not possible to determine which hold metric crossed the limit. Initial
  transition metrics cannot substitute for that later same-route measurement.
- Root cause of missing diagnosis is concrete: wrapper persisted raw frames only
  in the owned volume and rejected receipts omitted the failed frame; campaign
  cleanup exported journal/hashes but removed the volume. The wrapper now retains
  every raw frame in `journal.json.frames` and includes `failed_frame` in rejection
  evidence when acquisition advanced. Original error/count/timestamp bytes survive
  normal campaign journal export. Historical absent frames cannot be reconstructed.

No evidence supports claiming either missing measurement passed or identifying an
additional underlying timing/kernel fault. Thresholds, timers, seeds and frozen
source remain unchanged. No campaign was launched in this correction workstream.
Campaign owner must use fresh preregistration after the final hashes below; old009
results remain failed. No historical artifacts were modified.

## Implemented integration

Latest reviewer race corrections are implemented and tested offline:
bootstrap authority re-reads STOP presence and refreshes latch/abort/policy,
admission/request/action expiry checks AFTER protected admission-file I/O. WAL and
fault-boundary work remain before that final dispatch authority check. There is no
pending bootstrap authority fix.

The runtime now calls `dispatch_authority(entry)` only from its sole-writer add
boundary. Campaign checkpoint request/approval consumption moved from general
`authority()` to this hook. Watchdog, measurement and pause-loop authority checks
are read-only checks; they cannot publish or consume a pending mutation's approval.
One native addition has exactly one campaign checkpoint event, including when the
watchdog checks authority while that addition waits for its response.

Prepared plan001 is stale after these source changes. The campaign owner must
preregister a fresh plan after all fixes settle; this workstream neither updates
the old plan nor launches a live lab.

`backend/app/modules/autonomy/experimental/adapter.py` implements the actual core
`Observer` and `Transport` ports. Use the SAME instance for observer/transport.
`Ports.bind_checkpoint()` binds `adapter.bind_checkpoint()` after controller
construction; it performs no I/O. All hashes, including raw dictionaries, use
`experimental.schemas.contract_digest`. The campaign owner has composed these
interfaces in `backend/scripts/verify_experimental_lab.py`.

Explicit constructor inputs: final `policy`, verified `receiver_policy`, exact
receiver policy FILE-byte SHA256, protected `token_path`, async
`transport(bytes)->response dict`. Optional `current_authority` is superseded by
the controller-bound checkpoint. Application adapter has no Docker authority.
Inference uses the existing confined core model adapter, without tokens/authority.

## Bootstrap and actual episode identity

The original experiment generates a UUID; it cannot be chosen or rewritten.
Avoid the policy/hash cycle with explicit two-phase operator setup:

1. Pin receiver projection version **`nanfo.experimental-receiver-policy/v1`**,
   `controller_policy_sha256:null`, before acquisition. Its exact required fields
   are in `experimental_lab_contract.load_policy`: image/source/model/wrapper,
   container/owner, seed/scenario, expiry/duration/heartbeat/age/dwell and thresholds.
2. Parent admits the lab through protected `campaign-admission.json`:
   `{policy_sha256, admitted:true, container_id}`. It writes separate
   `bootstrap-admission.json`: `{policy_sha256, request_id, expires_at, authorized:true}`
   after actual owning-service authorization. The bootstrap lease is bounded by
   receiver expiry; it is operator admission, never inferred model authority.
3. Send wire `bootstrap` with that request UUID. Receiver captures all reserved
   tables and original four forwarding paths BEFORE reset, rejects occupied tables,
   journals intent and invokes the unchanged reset once. It returns original
   `episode_id`, baseline/hash, original frame and readback. Reset is explicitly
   actuating operator setup, outside controller observation.
4. Construct final core policy using `run_id=episode_id`. The newer core also
   supports separate journal UUID via `measurement_run_id=episode_id`; adapter
   honors that field without modifying the raw frame or snapshot episode UUID.
   Write protected `controller-binding.json` exact fields
   `{receiver_policy_sha256, controller_policy_sha256, run_id, baseline_sha256}`;
   binding's run_id is always the **measurement episode**. Send `bind`. Receiver
   validates original episode, baseline, live bootstrap admission and one-time
   binding, then journals it. Final policy hash pins all actor/scope/model/simulation
   requirements. The separately pinned projection remains unchanged.
5. Controller adapter verifies binding on status, supplies checked heartbeats and
   `observe` ONLY reads the fresh bootstrap frame. Stale bootstrap is rejected.
   Snapshot/raw UUID equality passes the unchanged registry identity boundary.

## Sole owner and actual restoration

The receiver instantiates original `OspfLab`, `Experiment(mode="matched")` and
`MatchedRouting`. No original experiment socket or second routing driver runs.
Frozen step applies THEN measures; exact raw request/response stays unchanged.
Wrapper hashes are separate from frozen source provenance.

WAL and optional pause finish BEFORE the final add authority check. No journal or
hook lies between that check and original command dispatch. Exact-owned deletions
retain cleanup authority after STOP/revocation. Original end-readback cannot silently
reinstall lost route state. Request UUIDs and fences prevent execute replay.

Normal recovery calls original `routing.close()` ONLY, then independently reads
every reserved rule/table and original kernel route-get path in both foreground and
background directions. It compares original tables/path identities and verifies
empty ownership. It never installs route0, calls step/reset or generates traffic.
`RecoveryReceipt` requires baseline hash, raw readback and original forwarding
verification; no experiment-performance metric is required during cleanup.
Foreign state remains untouched and ownership stays uncertain.

One action per lab; two-second reset0, execute1, optional verification2/3; never
terminal step4. Later hold checks use fresh independent readback and unchanged
measured timestamps, rejecting stale metrics. Duration begins before dispatch;
same-route checks cannot extend it. UDP loss and ICMP loss are different streams;
core thresholds them separately.

## STOP, watchdog and deterministic campaign faults

Wire `nanfo.experimental-lab/v1` requests have exact fields:
`version, request_id, fence, policy_sha256, expires_at, operation, action,
duration_seconds, token`. Operations: bootstrap/bind/observe/execute/verify/restore/
recover/status/stop/heartbeat. Only execute admits numeric action0/1 and positive
duration. No arbitrary shell command or path enters IPC.

Controller calls real checkpoint during outstanding I/O and between steps. Checked
heartbeats renew a protected bounded authority lease. Receiver rechecks lease,
STOP, expiry and current policy at each addition and measurement loop checkpoint.
Authority failures deny new adds. Watchdog latches abort outside the work lock,
so blocked measurement/pause can see STOP; only the serialized owner restores.
STOP response acknowledges durable latch promptly; completion requires recovery
reconciliation. Bounded subprocess calls can delay unwinding; no hard deadline claim.

Protected `failpoint.json` exact fields:

```text
policy_sha256
operation: bootstrap | execute | verify
ordinal: 1..128 (mutation attempt within that operation)
when: before | after
effect: pause | raise | stop
timeout_seconds: >0, <=30
```

`before` is after intent WAL, before final authority; `after` is after successful
native command and completion WAL. `boundary.json` publishes point digest, exact
argv and reached/released monotonic times. Campaign performs REAL committed STOP,
actor revocation or lab intervention, then writes protected `release.json`:
`{boundary_sha256:<point digest>, release:true}`. Receiver checks STOP/expiry while
paused and final authority after release. One-shot point identity prevents repeated
intervention. Compensation bypasses failpoints. `raise` and `stop` are explicitly
injected failures, never evidence of real role revocation or traffic impairment.

## Persistence and process death

Receiver-directory `journal.json` retains original before-image, owned rows,
namespace keeper PID/start-ticks/netns identity, immutable request/response receipts,
attempted/completed argv/counters, binding and fault-boundary evidence. Raw completed
frames are separately stored as `frame-<sha256>.json`, fsynced before receipt.
Controller restart syncs fence and restores through the surviving receiver without
execute replay. Receiver-process death is a different condition: never attach a
new graph to its journal. Relaunch over any old journal is denied.

Operator `experimental_lab_operator.py --teardown-evidence-directory DIR` provides
last-resort exact-container graph disposal after owner death. It verifies full ID,
label/image/network, inventories host PID/start-ticks/netns, persists teardown
intent, rechecks process family, removes ONLY that container, then scans for any
process retaining recorded namespaces. Insufficient host proc visibility or surviving
namespaces is uncertainty, not success. Durable volume remains for inspection.
Result is `owned_graph_destroyed`, **not** original-forwarding-restored and never a
forged successful core RecoveryReceipt. Releasing core uncertainty needs explicit
operator/core reconciliation of that destruction evidence. No graph teardown ran
during this workstream.

## Operator launch and pins

Exact image: `sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7`.
Exact source-map: `08c312c64154c9aedcd3b22eeb3573783590e0eb7183bc999cb8ef39b958dbbd`.
Model: `77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614`.
Original qualified sources/images are untouched. Mount/copy wrapper separately,
outside `/opt/nanfo`; set truthful inspected `NANFO_LAB_IMAGE_ID`. Private durable
directory is `/run/nanfo-experimental`; container network is `none`; label
`nanfo.adr025.owner` equals receiver policy. No source overlay is allowed by relay.

Inside parent-admitted container:

```sh
python -B /run/nanfo-wrapper/experimental_lab_receiver.py \
  --directory /run/nanfo-experimental \
  --policy /run/nanfo-experimental/receiver-policy.json --policy-sha256 "$POLICY_SHA256" \
  --token /run/nanfo-experimental/receiver-token --source-directory /opt/nanfo/emulation
```

`--static-probe` validates source/spec/wrapper without a lab. Operator relay validates
actual Docker identity/labels/network/mounts and uses a fixed in-container socket
client. It adds token from protected file; tokens do not enter inference or logs.

## Verification

Offline suite includes original command-sequence equivalence with the **whole
preserved source package** loaded in a subprocess, all STOP mutation prefixes,
WAL-time revocation, foreign-state denial, cleanup-only restoration, watchdog,
read-only observe after explicit bootstrap, prompt STOP at exact paused native
boundary, actual core Ports checkpoint binding and complete preserved frame
observe→prepare→recover with authentic episode identity and raw-dictionary hashes.
Fixtures are not live network evidence. Parent-admitted joined traffic campaign and
independent review remain necessary for measured acceptance.

Latest focused checks:13 receiver/runtime tests and5 backend adapter tests pass.
New independent threaded reproductions pause the real bootstrap admission-file read
after intent WAL, inject either receiver-latched or external-file STOP, and verify
zero original adds. The actual campaign subclass is exercised with the original
matched command path: watchdog checks during a pending grant yield zero extra
requests/events;12 successful additions produce exactly12 distinct approvals.
