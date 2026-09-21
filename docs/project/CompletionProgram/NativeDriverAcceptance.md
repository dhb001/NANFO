# ADR024 native driver campaign — preregistered implementation scope

Claim under test: `native-driver-verified`, `scoped-manual-driver-campaign`.
No safety certificate, trusted installation, model inference/training or autonomous
qualification. This follows QualificationReview's accepted standalone protocol.

The user explicitly released ContinuousAI's exclusive slot for this work. Retain its
passed `/tmp/opencode/nanfo-live-acceptance-7ngrbdgv/result.json` and `cleanup.json`
as release evidence plus the present user authorization, and acquire a single
host-wide `/tmp/opencode/nanfo-privileged-lab-slot.lock` before any new graph. Earlier
campaigns used separate output locks rather than a common host lock; this fact must
be retained rather than claiming they acquired this new lease. Check running
containers for any other privileged lab before launch. Never reuse their namespaces.

Implementation: `backend/scripts/verify_native_driver.py`, new dedicated receiver
image from pinned Python3.12 bookworm with actual Mininet/Linux/iproute2 tools. The
recoveredv4 image954462 is preserved unchanged; new image/source identities are
recorded. No host network/PID, Docker socket, credentials or physical-device mounts.
Container: network none, private PID namespace,2CPU,1536MiB,256PIDs,30minute campaign
budget (containment only),5s native subprocess and20s existing checkpoint limits.
Cleanup may continue under separate exact recovery authority after acquisition stops.

Use the reviewed **static-FIB manual driver fixture**: nine Mininet-owned namespaces,
exact `linkPlan()` graph with22 directed endpoints, no FRR/OSPF/workload producers.
Create veths DOWN; install all-ethertype clsact-egress matchall DROP on every endpoint
and HTB/netem while down, then admit links only after all gates read back. Disable
IPv6/offloads and retain native inventories. Freeze seal until epoch ends. Inspect
root/leaf queue bytes/packets/departure counters at entry, after each mutation and
exit. Conditional zero-enqueue statement is not a hard kernel service guarantee.

For each action: STOP at every0..12 add boundary; expire/revoke before a next add;
partial apply restart at3; lost receipt after actual third add; interrupted recovery
after3 deletes and restart; foreign core/table19110 zero-delete refusal; lock and
binding refusal; normal12 adds + sealed readback. Close seal explicitly, remove only
owned gates, perform actual driver.verify6/6 ping, compensate and repeat compensation
with zero further deletes. Use a fresh sealed fixture for the second action.

Persist immutable source/protocol/image identity before acquisition and per-case
prepared bytes/digest before mutation. Every native command records wall_ns and
monotonic_ns, argv/node, raw output/error/returncode. Manual callback checks protected
protocol/hash, process identity, immutable namespace ownership, phase, exact next
command, monotonic campaign expiry and STOP; recovery callback admits only matching
deletes. Fresh child processes load original prepared bytes for restart cases.
No invented clocks: retain integer timestamps, use existing Q5 canonical conversion
where a derived datetime is needed. Preserve failed attempts and cleanup results.

Acceptance and actual results will be appended after the campaign. A failed setup
or missing enforcement premise is a blocker, never a passing negative test.

## Actual campaign result — 2026-09-20

**42/42 native manual-driver cases passed**, with raw reconstruction passed.
Evidence root: `/tmp/opencode/native-driver-02z3yisx`.
Protocol SHA256:
`777edceccf45133aa2e0670db39d8800723882b118e332ae0342c3eb241b328e`.
Actual new image:
`sha256:fe807af24ed485669c18476dd69cac161366583f33356136db7081eef98325c7`.
Original recoveredv4 image954462 and historical model files remained untouched.

Runtime: Python3.12.14 bookworm, Linux7.2.6-arch2-1 x86_64; Mininet2.3.0-1,
iproute2 6.1.0-3, ethtool6.1-1, FRR package8.4.4-1.1~deb12u2 (daemon deliberately
not started), util-linux2.38.1-5+deb12u3. The pinned setuptools75.8.2 dependency
supplies Mininet's distutils compatibility. Exact package/boot/time/PID/netns/kernel
identities and effective capabilities are retained in `identity.jsonl`.

| Measured gate | Actual result |
|---|---|
| Both action paths |12 real route/rule additions each; exact forward/reverse kernel route-get; background unchanged|
| STOP k=0..12, each action |26 cases; exact acknowledged prefix; no add after denied checkpoint; full k12 revoked before acceptance|
| Expired manual authority |0 adds for each action; cleanup independently permitted|
| Interrupted apply |child process exits after actual3-command prefix; fresh recovery process loads original prepared bytes|
| Lost completion receipt |actual third command accepted by kernel, missing operation ACK; fresh process recovers actual matching state|
| Interrupted compensation |3 actual reverse deletions then process exit; restart skips absent tuples and restores remainder|
| Foreign core/table19110 |driver refuses before deletion; foreign tuple unchanged; fixture removes only its own foreign rule, then recovery succeeds|
| Exclusive lock/binding |actual same-lock contention refused; changed binding refused before writes (software identity negative case)|
| Idempotent recovery |every second recovery performs0 deletes and returns exact baseline hash|
| Seal observations |460 snapshots ×22 endpoints =10,120 endpoint readbacks; root/leaf backlog/qlen/bytes/packets all0|
| Actual full verify after unseal |action0:6 sent/6 received; action1:6 sent/6 received|
| Exact cleanup |18 owned namespace keeper processes gone, both fixtures stopped, exact container removed, unresolved=[]|

Totals: **480 actual policy add/delete operations** reconstructed from native argv,
returncodes and independent manual checkpoints; **54,646 native commands** including
readback/provisioning. Maximum observed command duration0.229714005s, median
0.003486321s. Descriptive campaign interval282.612150746s. Normal12-write apply
intervals (first final checkpoint through last syscall result, including intervening
sealed snapshots)3.279366722s/action0 and3.426162899s/action1. These are measured
durations, not hard transition deadlines, and are not installed shield horizons.

Driver full verify evidence:
*action0 readback* `595f204c046bcae63de655c58eff2d0835db3f0bcee7f26aed2949fdf9032185`;
*action1 readback* `8ef56c42c6727830d75f166991b22b722fa2d5de6d5b320db7d3a6958335e143`.
Raw ping stdout, route-get JSON and gate removal timestamps establish that probes
occurred after `sealed_epoch_closed`, never within the A=0 scope.

### Evidence layout and replay

* `protocol.json`, `sources.json`, read-only copied `source/`, `container.json`:
  pre-acquisition protocol, exact bytes, actual image/container limits and mounts.
* `continuous-release-result.json`, `continuous-release-cleanup.json`: prior owner
  pass/cleanup evidence. User release is explicitly recorded as user authorization,
  not a fabricated common-lock receipt from the previous agent.
* `action{0,1}/fixture.jsonl`, `namespaces.json`, `manual.json`: actual down-link seal
  setup, raw tc/link/offload inventories, static baseline, integer clocks and scoped
  software operator/process identity. clsact matchall DROP has no protocol exemption.
* Per-case `prepared.json`/SHA256, apply/recover JSONL and child result receipts:
  fsynced prepared identity, attempted command graph, callback/STOP, raw native
  stdout/stderr/result timing and crash/lost receipt evidence.
* `result.json`, `cleanup.json`, `reconstruction.json`: reported cases, exact owned
  cleanup and independent-code owner reconstruction. The latter explicitly records
  `independent_signoff=false`; no reviewer signature is impersonated.

```bash
# Launch is privileged and must only run while owning the explicitly released slot.
poetry run python scripts/verify_native_driver.py --launch --output /tmp/opencode

# Read-only replay, no lab or service:
poetry run python scripts/audit_native_driver.py /tmp/opencode/native-driver-02z3yisx
NANFO_NATIVE_DRIVER_EVIDENCE=/tmp/opencode/native-driver-02z3yisx poetry run pytest \
  tests/unit/test_verify_native_driver.py tests/unit/test_autonomous_frr.py \
  tests/unit/test_autonomous_frr_startup.py tests/unit/test_autonomous_frr_final_checkpoint.py \
  --no-cov -q
```

**149 passed**, including the retained actual evidence audit; scoped Ruff and
whitespace checks pass. New verifier and Dockerfile are outside frozen sources;
driver logic was not bypassed or modified to make a native command pass.

### Retained attempts and limits

Attempt `/tmp/opencode/native-driver-ze6l5g0r`: failed before Mininet graph creation
because Python3.12 lacked distutils. Fixed only the new image by installing pinned
setuptools; failed result/container log retained. Attempt
`/tmp/opencode/native-driver-bqpfoktp`:42 cases passed, but parent tool wait timed
out120s and evidence audit exposed missing package/cleanup/idempotence explicit
gates. The container completed and was joined/removed by exact ID; no second live
lab overlapped it. The final run used a2100s outer wait and source-matched hardened
verifier, retaining both prior attempts rather than rewriting their results.

This is **native-driver-verified manual software-lab evidence** on an isolated
static-FIB Linux graph. It is not FRR/OSPF convergence testing, genuine model-runtime
equivalence, PostgreSQL receiver/API acceptance, autonomous authorization or useful
loaded-network adaptation. `autonomy_qualified=false`, `safety_calibrated=false`,
`physical_rf_qualified=false`, `trusted_installation=null`, `safety_certificate=null`,
`hard_transition_deadline_proved=false`, `receiver_journal_acceptance=false`.
The seal theorem remains conditional on independent installed-kernel/enforcement
review; observed zero counters alone do not prove unbounded future safety. Physical
RF remains externally blocked. Independent reviewer should reconstruct the retained
raw campaign before attesting the narrow claim. No training or concurrent liveAI ran.
