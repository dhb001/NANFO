# ADR024 independent qualification review

## Final qualification matrix — completed native and continuous runs

**Independent result: accept the scoped rebuilt benchmark, fresh continuous
recommendation demonstration, and `native-driver-verified` manual static-FIB
demonstration. Do not claim `autonomy-qualified` or physical qualification.**
This section supersedes earlier pending statuses below. All review operations
were offline; no lab, Docker inspection, database connection or dispatch was
started by the reviewer. Historical findings/checkpoints remain below as a ledger.

| Qualification item | Final decision | Exact accepted scope / residual boundary |
|---|---|---|
| Rebuilt checkpoint lineage and fresh five-policy benchmark | **PASS** | Derived77dae44…, byte-identical tensor payload3e7e38…, truthful image954462…; 12 unused paired seeds, 300 measurements / 240 decisions, original gates; prior exact reconstruction retained |
| Fresh passive acquisition and original model inference | **PASS** | Two new measured episodes, seeds1010/1011; 6 raw frames, original native JSON=IPC=snapshot history; actual bridge attachment precedes acquisition; exact original loader replay |
| Continuous worker recommendations and persistence | **PASS, bounded demonstration** | 2 monitor decisions, 4 non-actuating recommendations, 2 stale blocks, 4 control changes; matching separate-session PostgreSQL export, actual Redis/provider path per pinned harness; not an indefinite uptime/load claim |
| Native driver mutation/readback/compensation | **PASS: `native-driver-verified`** | Real Mininet-owned Linux namespaces, exact graph, **static FIB and no running FRR/OSPF**; 38 command-trace cases independently reconstructed, 4 lock/binding exception cases accepted only as source-pinned software receipts; owner campaign42/42 |
| Sealed epoch measured emptiness | **PASS measured / conditional theorem** | 460 snapshots ×22 endpoints, actual all-ethertype clsact DROP readback installed while interfaces down; zero queue/departure observations; not an unconditional proof of every kernel path or future scheduling behavior |
| Real reachability after seal closure | **PASS** | 6/6 ICMP replies for each action, 12/12 total; probes outside the zero-arrival epoch |
| V2 service mapping integration | **PASS software review/tests** | Fixed-H burst-aware upper, available-service lower→0, exact per-queue/profile/receiver checks and external trust inputs; **no real calibrated installation supplied** |
| Joined learned-model→causal-safety→durable receiver→native actuation | **NOT QUALIFIED** | The two demonstrations are separate runtimes/claims; no installed all-demand causal guarantee, aligned safety frame or calibrated native end-to-end run |
| FRR/OSPF convergence and live routing-daemon interactions | **NOT covered by manual driver campaign** | FRR package presence is not a running-daemon result; static-FIB fixture cannot establish convergence or transient daemon interactions |
| Hard future dispatch/transition deadline and loaded-network stability | **UNPROVED** | Descriptive latencies, subprocess timeouts, STOP admission barriers and zero-queue observations do not establish these guarantees |
| Physical network/RF qualification | **BLOCKED** | No hardware/survey; software emulation and nominal geometry cannot substitute |

### Native raw reconstruction

Evidence `/tmp/opencode/native-driver-02z3yisx`; protocol SHA256
`777edceccf45133aa2e0670db39d8800723882b118e332ae0342c3eb241b328e`;
image `sha256:fe807af24ed485669c18476dd69cac161366583f33356136db7081eef98325c7`.
All copied source pins match protocol; the driver/namespace/graph helpers also
match the independently reviewed current bytes. Recorded container is network-none,
private PID/IPC,2CPU/1536MiB/256PID. It has **two host bind mounts**: this campaign's
read-only `/source` and writable `/evidence`. It has no Docker socket/host-network
mount. Do not describe this native run as having no host filesystem mounts; that
description applies to the earlier benchmark/live acquisition containers.

Ran the owner's read-only audit and separate reviewer implementations:

- `/tmp/opencode/adr024_final_native_review.py` reconstructs expected resource
  tuples from the graph, all raw apply/deletion argv and ordered authority events,
  STOP0..12 for both actions, expiry, child exits73/74, missing third ACK in the
  lost-receipt case, separate recovery PIDs, 3+9 interrupted-recovery deletion
  counts, idempotence, final native table/path stdout, seal setup and every snapshot.
- `/tmp/opencode/adr024_final_native_readback.py` separately reconstructs **34
  completed prefix inventory/path results** from raw route/rule/route-get JSON;
  four deliberate interrupted applies have no complete result and are instead
  verified by actual mutation prefix and recovery traces. Recomputed both normal
  readback digests exactly:
  `595f204c046bcae63de655c58eff2d0835db3f0bcee7f26aed2949fdf9032185` and
  `8ef56c42c6727830d75f166991b22b722fa2d5de6d5b320db7d3a6958335e143`.
- Foreign core/table19110 remains identical through raw inventory reads; between
  its recorded add and fixture-owned removal there are **no driver delete or
  recovery-grant events**. Subsequent exact compensation and second zero-delete
  recovery restore the original four route paths and empty all ten reserved-table
  inventories.
- Raw command counts agree: **54,646** namespace/setup/readback commands,
  **480 policy mutations**, maximum recorded command duration **0.229714005s**.
  All reconstructed native command returns are successful and below the original
  5-second subprocess limit. Normal apply spans3.279366722s/3.426162899s and the
  282.612150746s fixture interval are observations, not future timing bounds.
- All **460 snapshots** match their preceding raw tc stdout; exactly22 distinct
  node/interface pairs and HTB/netem/clsact scope, backlog/qlen/bytes/packets zero,
  `matchall protocol all pref1 gact drop`, deterministic raw-clock binding. All
  gates were installed/read back before any non-loopback interface was raised;
  recorded ingress filters are empty and GRO/GSO/TSO off. This run tests the
  **HTB/netem sealed fixture**, not the proposed nonzero TBF/bfifo/quota campaign.
- Exactly22 gate removals per fixture follow `sealed_epoch_closed`; both raw ping
  commands follow every removal. Each stdout reports3 transmitted/3 received/0%
  loss. No probe is inside the sealed epoch.
- Eighteen keeper PID/start/inode identities are retained and namespace-cleanup
  events report none present. There are only17 distinct inode values across the
  **sequentially destroyed/recreated** fixtures: one inode was reused with a
  different PID/start identity. That is legitimate kernel reuse, not concurrent
  shared ownership. The reviewer initially tested global inode uniqueness, then
  corrected the review oracle to the driver's actual PID/start/inode tuple and
  serial-lifetime contract; no original data was changed.

**Evidence limitations retained:** the `exclusive-lock` and `binding-refusal-0`
cases (four total) have owner result receipts and the exact executed harness,
but no dedicated persisted exception event. The binding case deliberately mutates
a prepared identity and is a software negative case, not observed PID reuse.
The owner audit skips detailed reconstruction for these; this review does not
inflate38 trace-reconstructed cases to42 independently observed native syscalls.
Final container removal has an exact-ID owner cleanup receipt and checked source
path, but no saved post-removal `docker inspect/ps` output. No live query was used
to fill that gap. Exception/syscall/deletion receipts should be persisted directly
in future campaigns. These limitations qualify the evidence granularity, not the
verified38 native command cases. The narrow software-lab42-case record is accepted
with this explicit distinction.

Result `/tmp/opencode/adr024-final-native-independent.json`, SHA256
`367f6512a18cbc9d2745e97b711557b4c75bccd2f7fc3e0e097e6df6747a25b8`;
additional `/tmp/opencode/adr024-final-native-readback.json`.
Owner audit replay `/tmp/opencode/adr024-final-native-owner-audit-replay.json`
remains `independent_signoff=false`; this review supplies its own scoped finding.

### Continuous-AI raw/model reconstruction

Evidence `/tmp/opencode/nanfo-live-acceptance-7ngrbdgv`; plan SHA256
`621f51b35e1baf5cc7bcd0d4be1dfdd1bd491238706f004e9d94ebf21025784c`;
registry `d6981f29de5cad9884af5af8c182ab88380bcdbbe052fd418413a3f963b4c969`.
The exact previously accepted benchmark report remains
`e6ee9c1bd99e3f6961db497db664335684fa277bd1a1c86a8034570ac116056d`.
All **48 runtime source-manifest entries** match current files; all registry
artifact refs match sizes/digests, including parent/derived bundles and five-policy
evidence. Original source map and complete tensor bytes independently match.

`/tmp/opencode/adr024_final_live_review.py` verified:

- New operational seeds1010/1011 are disjoint from the retained operational/
  historical reservation union and benchmark3003..3014. The acquisition action
  remains0 for every actual step: suggested route1 is **not applied** to generate
  favorable observations.
- Three frames per scenario (reset+two steps), all native JSON equal to raw IPC
  and preserved snapshot history. Original frozen CLI `infer` was actually run
  on **all six** retained histories with the derived checkpoint. The original
  measurement/source/provenance/weights/distribution checks passed; no bypass,
  current timestamp substitution or live installation occurred.
- Bridge attached at session EOF before actual measurements; raw-line hashes,
  byte offsets, feed device/inode, server PID/start/boot/time namespace, registry
  and admission hashes all correlate. Wall observation times reconstruct exactly
  from the retained wall/monotonic anchor and measurement end; measured delivery
  and clock drift remain within the pinned10s/.25s limits. Snapshot byte digests
  were reconstructed using the producer's actual Pydantic serialization, not a
  different sorted-key encoding. Initial reviewer serialization mismatch was
  resolved by following that pinned serializer, without changing evidence.
- Four recommendations match original deterministic actions, **exact probabilities,
  critic values and input SHA256**, checkpoint/tensor/source/report identities,
  registered network/workspace and action path. All are persisted within the
  original30s freshness cap and registry validity. Observed timestamps are never
  freshened. The separately queried final durable export exactly matches the
  individual decision records:12 rows =4 control changes+2 observed+4 recommended+
  2 blocked, with no safety/authorization/execution/verification objects.

| Scenario / recommendation | Route | Age at persistence | Original-model probabilities |
|---|---|---:|---|
| path0 /1 | route1 |14.155144s |[0.015177391469478607,0.9848226308822632]|
| path0 /2 | route1 |10.187584s |[0.0202395748347044,0.979760468006134]|
| path1 /1 | route0 |13.369515s |[0.9700261950492859,0.02997383289039135]|
| path1 /2 | route0 |9.737084s |[0.9738398790359497,0.02616012468934059]|

The two stale decisions occur after actual age>30s with no proposal; bridge logs
record feed closure and incompatible disconnect results. Source inspection shows
actual private PostgreSQL/Redis, real authentication/membership code through
in-process ASGI transport, and new worker instances reading/committing decisions.
This is not HTTP gateway/deployment testing. Raw HTTP permission responses and
post-removal container inspections are not separately retained; those particular
claims rely on the pinned executed harness/result receipts. No independent live
database query was made; durability is checked against the retained separate-
session export. These boundaries must accompany the scoped service acceptance.

Independent result `/tmp/opencode/adr024-final-live-independent.json`, SHA256
`52068becc0787c851548382f533ec1a2be75df313ca41ce72bb80935c9aa9d69`.
The owner `audit_live_acceptance.audit()` was also rerun read-only and passed.
Native release copies exactly match this run's result/cleanup bytes; native
protocol/acquisition follows it. The new native global-lock implementation is
source-pinned; prior runs must not be relabelled as holding that later lock.

### V2 mapping review and remaining causal obligations

Reviewed actual `calibration_verification`, `safety_provider`,
`safety_installation`, `execution_contract`, `ReceiverJournal.checkpoint` and
composition trust plumbing. The implementation preserves original per-queue
rate/burst/physical capacity/error/semantics, maps at **one exact installed H**,
uses outward upper rounding and lower0 for past busy-period available service,
and validates both measured campaign and conservative runtime projection. The
global uncertainty/error floors are minima while exact full per-queue values
remain enforced, avoiding artificial heterogeneous-queue rejection. Provider and
receiver recheck the pinned profile/horizon before authority/device mutation.
Recovery remains separately owned rather than requiring a fresh dispatch grant.
V1 shapes and default trust behavior are preserved. No remaining mapping blocker
was reproduced in these reviewed paths; this does not accept any unsubmitted
guarantee or turn synthetic installation tests into real calibration.

Executed relevant v2/install/clock/native/driver/final-checkpoint/client suites,
including retained actual native evidence audit: **206 passed, 1 skipped**. The
skip is the absent authentic native-v2 causal replay receipt, not the completed
manual driver run. No lab tests were launched.

Remaining end-to-end causal requirements are substantive: actual all-demand
including ARP/OSPF/background attribution and sensor error; exact model/safety
observation alignment; enforceable arrivals and source/accounting/no-bypass
premises; future service/dynamics over transitions; policy-feasible zero-budget
drift; independently accepted runtime/plan/environment mapping; authenticated
installation and the real PostgreSQL receiver path; hard mutation/deadline fencing
or an explicitly narrower approved claim. clsact seal evidence does not inherit
the earlier nft-quota/bfifo source theorem. Privileged fixture ownership and
advisory locks are not proof against all privileged foreign writers. Hardware RF
and real-device behavior remain external prerequisites. **No empirical maximum,
producer self-approval or false human attestation closes any of these rows.**

## Decision and scope — 2026-09-20

**Native installation is not approved by this review. Physical RF qualification is
externally blocked: the user has neither RF survey data nor RF equipment.** This
does not prevent honest software-lab evidence or independent offline replay.

Reviewer scope: ADR024, existing independent calibration/import/RF/geometry code,
native causal acquisition, safety model, action/runtime installation contracts and
the forthcoming native proposal/recovered-runtime handoffs. Only this report and
offline analytical tests under `/tmp/opencode/` are owned by this workstream.
No live lab, receiver dispatch, source modification or trust installation was run.

At the initial checkpoint, `NativeQualification.md` and a recovered-runtime Markdown
handoff had not appeared under `docs/project/CompletionProgram/`; only the early
recovery JSON/log bundle was available. That checkpoint granted no approval of an
unseen protocol. The continuation below reviews the subsequently delivered files.
No native guarantee or receiver-installation digest is approved by this review.

**Continuation:** both handoffs and the ADR024 rebuilt-image amendment are now
reviewed. The new derived-artifact/plan results and native proposal findings below
supersede the initial absence-of-files status, without retroactive approval.

## ADR024 amendment and native-proposal continuation

### Standalone native-driver acquisition protocol — accepted design, not execution evidence

**Review decision:** the following protocol is acceptable for a separately
preregistered manual software-lab campaign with final claim
`native-driver-verified`. It neither requires nor creates a fabricated
`TrustedCalibration`, `SafetyShield` certificate, model qualification receipt or
autonomous authorization. `autonomy_qualified=false`, `safety_calibrated=false`,
`physical_rf_qualified=false` remain mandatory. This is approval of the **acquisition
design and scoped gate**; the exact implementation/configuration/evidence must
still pass independent review. No native run was performed by this reviewer.

**Serialization precondition:** do not provision, probe or mutate any lab until
ContinuousAI's owner explicitly releases the host-wide experiment slot. Retain
the actual release receipt and acquire the same exclusive lease before creating
new owned resources. Completion of the earlier five-policy campaign alone is
not release of a subsequent continuous-AI run. A per-output `campaign.lock` is
insufficient. Never attach to or reuse ContinuousAI namespaces.

#### Claims and result contract

Use a new standalone protocol identity, e.g.
`nanfo.native-driver-acceptance/v1`, rather than overloading the calibrated
installation schema. A result contains at least:

```json
{
  "version": "nanfo.native-driver-acceptance/v1",
  "claim": "native-driver-verified",
  "environment": "isolated-emulation",
  "status": "pending",
  "authority_kind": "scoped-manual-driver-campaign",
  "autonomy_qualified": false,
  "safety_calibrated": false,
  "physical_rf_qualified": false,
  "trusted_installation": null,
  "safety_certificate": null,
  "sealed_queue_theorem": "conditional-on-reviewed-native-enforcement",
  "hard_transition_deadline_proved": false,
  "receiver_journal_acceptance": false,
  "cases": [],
  "failures": [],
  "unresolved_resources": []
}
```

This example is a schema shape, not a measured result. Freeze exact source/image/
kernel identities, namespace graph, case IDs, expected command graph, authority
rules, cleanup, thresholds and raw-evidence references in the protocol before
acquisition. The result may say `passed` only after every mandatory case and
cleanup gate passes. Keep separately named subresults for sealed native readback,
unsealed reachability, STOP admission, restart compensation and foreign-state
refusal. Missing sealed-enforcement evidence leaves that subresult blocked;
successful manual driver operations may still be reported individually, never
promoted to the full protocol claim.

#### Exact command graph and rollback semantics reviewed

Actual implementation: `emulation/autonomous_frr.py:69–79,122–129,151–222`;
namespace boundary: `autonomous_namespace.py:55–77`; cancellation join:
`autonomous_driver.py:12–21`.

- Each action has **six resource tuples**: three forward routers for h1→h3,
  table/priority19110; three reverse routers for h3→h1, table/priority19111.
  Action0 uses access1→dist1→access2; action1 uses access1→dist2→access2.
  Host interfaces and gateways come from exact `linkPlan()`, not guessed ports.
- Apply is exactly **12 add operations**, in resource order: static onlink /32
  route then exact source/destination /32 rule for each tuple. No `replace`, table
  flush, OSPF cost change or bulk reset is an admitted apply operation.
- `prepare()` requires **all ten router/reserved-table combinations empty** and
  both foreground baseline paths equal `baseline_action`. It records background
  paths. Applying over an already installed action is unsupported. Test switching
  by compensation back to the baseline then a fresh prepare, not by pretending
  direct action1→action0 overwrite is supported.
- Compensation examines all ten reserved-table combinations and refuses unknown
  selectors/nexthops/extra semantics, including on an unused router, **before its
  first deletion**. It traverses resources backwards, deleting a present matching
  **rule before route**. Missing matching resources are skipped. It then requires
  all reserved tables/rules empty and all four route paths equal `prepared.before`.
  It does not restore changed foreign/default/OSPF state, flush foreign entries,
  or blindly undo every command in an optimistic journal.
- `routePath()` uses real `ip -j route get ... from ... [iif ...]` at each hop and
  rejects off-graph gateways/loops. This establishes kernel forwarding decisions,
  not packet delivery. Archive full route-get JSON, not only its path digest.
- Full `verify()` also issues exactly **two ping commands**, each `-c 3 -i .1 -W 1`,
  and requires **6 sent / 6 received** overall. Those probes generate traffic;
  never run them inside a strictly sealed zero-arrival interval or suppress/fake
  their output. During the sealed interval use actual `read_owned(...,complete=True)`
  and actual `paths()` plus an independent graph assertion; label it
  `sealed_configuration_readback`, not `driver.verify` success.
- `dispatch_guard` is stored by the constructor but is not invoked by direct
  `apply()`/`compensate()`. The supplied checkpoint callable is the effective
  direct-call authority. Returning `False` does **not** deny a mutation: the
  callback must raise. An async function that returns successfully after real
  validation is appropriate; an always-successful lambda/test mock is not.

#### Manual authority, with no fake safety installation

The standalone harness must bind an actual software operator/process identity and
the user's limited manual-test authorization to a protected manifest digest.
The manifest is explicitly `scoped-manual-driver-campaign`, never presented as an
accepted `FRRRuntimeBinding`/equivalence or safety guarantee. Its digest may be the
driver's `binding_sha256`/plan binding for **manual identity checking only**; no
accepted-guarantee/runtime trust store is populated. If the namespace adapter
requires an object with resource/run/namespaces fields, provide a separate manual
binding type carrying real PID/start/inode values, not a fictitious model manifest.

For each actual `network.mutate(node,argv,checkpoint)` call, a logging boundary
must first require the exact next allowed tuple/argv and pinned run/namespace/
source identities. Preserve and invoke the driver's final checkpoint immediately
before subprocess I/O; no additional read sweep may follow it before launch.
The async apply checkpoint validates protected manual scope, exclusive ownership,
case/phase/sequence, current monotonic expiry if supplied, and an independently
set STOP latch. It raises on any mismatch. Do not claim the callback alone sees
argv: `apply` passes it no arguments; the wrapper must bind command context.

Before first write, persist/fsync `prepared` and its hash, baseline readbacks,
operation sequence and a `may-have-applied` record. Persist each attempted command
before launch and its actual return/stdout/stderr/timestamps after join. A crash
between syscall and receipt remains uncertain until readback. A fresh recovery
process must validate the original prepared digest and ownership, not regenerate
a convenient baseline. Hold exclusion until the worker thread and spawned
processes have terminated; Python cancellation does not cancel kernel work.

Recovery uses **separate manual recovery authority** limited to exact matching
deletions from that prepared record. STOP/expired apply permission must not prevent
authorized cleanup. Recovery still refuses ownership loss, foreign state and
identity mismatch. This is direct-driver/manual-journal evidence; it is not proof
of `AutonomousReceiver`, PostgreSQL journal/fence behavior or full API STOP. If
those receiver paths are separately exercised, retain their real evidence and
report a separate claim rather than substituting a fake receiver journal.

#### Sealed empty native epoch: feasible setup and honest limits

Use fresh owned namespaces/interfaces, all **22 directed link endpoints**, and
real qdiscs. A practical standalone fixture may use explicitly provisioned static
main-table baseline routes while FRR/OSPF and workload producers are absent or
stopped. Identify this as a **static-FIB manual driver fixture**; it does not
claim OSPF convergence or model-runtime equivalence. Static baseline provisioning
is separate from the driver's reserved-table mutations and is captured in full.

Install unconditional, source-reviewed drop-before-qdisc gates for **all**
ethertypes on every scoped endpoint while fresh interfaces are down and before
any traffic producer is admitted. No ARP, IPv6/ND, OSPF, probe or management
exemptions. Bring interfaces up only after every gate and namespace identity is
read back. Ensure the fresh qdiscs/pipeline contain no previously admitted packet;
otherwise the epoch is not ready. Audit tc ingress/redirect/BPF/XDP/raw bypass,
offloads and writer capabilities. A gate installed after ordinary traffic began,
two empty polls, or a stopped sender alone does not prove no in-flight arrivals.
If that fresh construction is incompatible with the launcher, record a setup
blocker rather than claiming the seal from polls.

Use a non-renewed immutable seal throughout the epoch. Root/leaf qdisc byte
backlog and packet count must be **exactly zero at entry, after every tested
mutation/prefix, and at exit**, with **zero admitted bytes/packets** and no reset,
unknown bypass or unexpected qdisc change. Prequeue rejected traffic may increase
drop counters and remains recorded; it is not qdisc arrival. Preserve raw
integer clocks and each read's interval. Monotonic chronology must be ordered;
raw/canonical conversion is deterministic, not a retimestamping operation.

Conditional theorem: initial q=0, no enqueue under the maintained seal, and route/
rule-only mutations imply q(t)=0 for the epoch, with A=0, service lower0 and
nonpositive drift. This is independent of scheduler progress; a stalled driver
does not invalidate the queue statement while its premises remain enforced.
No claim of positive service, packet delivery, useful load or global calibrated
autonomy follows. Source-to-installed-code/enforcement obligations from the kernel
record still apply; leave `sealed_queue_theorem` conditional if they are not
fully resolved. Native measured readback can be accepted without inventing a
globally trusted calibration from this lemma.

For full driver `verify`, **close the sealed epoch first**, record the unseal,
then admit an explicitly separate probe-only phase after writers remain fenced.
Keep frozen static FIB/owned override and verify real six-packet delivery. Reopening
the gate ends A=0; no queue theorem or SafetyShield certificate covers those
probes. Re-sealing does not automatically restore the fresh empty-epoch proof:
use another fresh fixture/epoch or explicitly prove and record pipeline closure.

#### Required deterministic cases and exact gates

No random seeds are required for this finite state/command test. Assign immutable
case IDs and cover both actions; do not borrow the benchmark holdout labels.

1. **Normal action0 and action1**, separately from clean baseline: real prepare,
   all12 actual adds, complete sealed configuration readback, separately unsealed
   real full verify (6/6 probes), then compensation. Expected all six route/rule
   pairs present after apply, exact foreground forward/reverse paths, both
   background paths unchanged, zero foreign reserved entries; after compensation
   all10 table inventories empty and all4 paths exactly restored. Call compensation
   again: **zero further deletes** and restoration still true.
2. **STOP at each apply boundary k=0..12 for both actions**: after exactly k
   acknowledged real add commands, persist STOP before permitting the next final
   checkpoint. At k<12 it raises and **no (k+1)th add is launched**. k=12 means a
   fully applied action is revoked before acceptance. Keep seal throughout;
   compensate through independently permitted recovery. Each state requires the
   exact prefix inventory and eventual empty reserved tables/original paths.
   This is deterministic checkpoint-STOP semantics, not instantaneous cancellation
   of a command already in flight.
3. **Interrupted apply / restarted recovery**: terminate the standalone apply
   owner after a persisted nontrivial prefix (k=3: a rule+route pair and the next
   unmatched route). Ensure all child processes/threads are joined or dead and
   exclusion can be transferred without overlap. A new driver process loads the
   original prepared bytes and performs exact compensation. Also test losing the
   completion receipt after a successful real add; kernel readback, not the
   missing receipt, determines whether that tuple needs deletion.
4. **Interrupted compensation**: after a full apply, permit three real reverse
   delete commands then interrupt/join. Restart from the same prepared bytes;
   skip absent tuples and delete only remaining matches. Require exact baseline
   restoration and a subsequent idempotent zero-delete recovery.
5. **Expired/revoked apply authority**: expire or revoke permission before the
   next checkpoint via a recorded control event; **zero new adds**. No fabricated
   stale safety certificate. Separately test recovery authority remains valid.
6. **Foreign reserved state** in a separate negative fixture: create a distinctly
   labelled test-owned foreign tuple (e.g. core table19110) before compensate;
   require refusal and **zero driver deletions**, including already matching
   tuples. Capture unchanged before/after foreign state. The fixture owner may
   remove only its separately inventoried foreign tuple and then retry recovery;
   preserve the refusal. Never flush a table to make recovery pass.
7. **Exclusive ownership/identity refusal**: a second adapter using the same
   protected `.autonomous-frr.lock` must fail to acquire; no command may dispatch
   with a changed/closed owner identity or mismatched run/binding digest. Test
   actual lock contention and a revoked manual scope in fresh owned fixtures.
   PID/inode reuse simulation is reported as a software negative test unless
   genuinely observed; do not claim live reuse from a mutated JSON field.

All listed cases are required for the full `native-driver-verified` protocol.
Record every failure/attempt; a fixture provisioning failure is not a passing
negative-control outcome. A missing or failed positive case makes the campaign
incomplete/failed, while completed individual cases remain reportable.

#### Timing thresholds without invented guarantees

Preserve the current namespace command timeout **5 seconds per subprocess** and
the existing driver checkpoint wait cap **20 seconds**; do not enlarge either
after an outcome. For each command require actual completion/returncode/readback,
and retain measured monotonic duration. Exceeding a subprocess bound or checkpoint
cap fails that positive case and makes any possible kernel effect uncertain.
The six ICMP probes retain the driver's existing `-W 1` and namespace command
timeout; all six replies are required, no partial-delivery pass threshold.

No arbitrary 30/60-second end-to-end transition or cleanup limit is substituted
for the shield's calibration horizon. Record total action/recovery latency as
**measured descriptive data**; the acceptance criterion is exact state and
per-command success, not a new hard real-time service promise. STOP is tested at
explicit command-admission barriers, with **zero post-denial launches**, rather
than declaring an unsupported millisecond reaction bound. A command that crossed
its final checkpoint before STOP may finish later; mark it in-flight and reconcile.
The sealed theorem remains conditional on enforcement even during such delays.

Choose and publish a campaign wall/resource budget before provisioning for
operational containment only. Budget exhaustion yields incomplete, not a relaxed
success threshold. Cleanup may continue solely under scoped recovery authority;
do not release exclusion with live writers or unresolved operations.

#### Evidence and independent acceptance

Each result must reference exact-byte protocol, release/lease/manual-authority
receipts, source/image/kernel/package identities, namespace PID/start/inodes,
seal rules/full offload inventory, raw qdisc/rule/route/route-get outputs, operation
and callback/STOP logs, prepared-record bytes, probes, recovery and cleanup ledger.
Use integer monotonic event ordering with wall-clock provenance; include every
failed syscall and raw stderr, missing receipt and uncertain phase. Independent
replay computes the expected12-command prefix and reverse compensation from
`resources/command`, matches every actual argv/node/result, verifies all exact
state/zero-arrival/delivery thresholds, then checks complete case coverage.

The reviewer may attest the resulting **local software evidence** as
`native-driver-verified` after reconstruction; no human signer or equipment
certificate is invented. This claim does not populate safety trust, turn on the
receiver, claim proof of STOP's kernel atomicity, or close physical RF. The
v2 mapping work is independent of this manual protocol. During review its update
appeared: `runtime_service_bounds` maps the explicit upper burst at fixed H and
maps past busy-period lower service to zero; versioned provider/installation
profiles preserve source semantics and enforce a fixed installed horizon. This
supersedes earlier historical statements that v2 mapping was absent. Mapping
availability does not establish authentic enforcement/evidence or a hard
scheduling guarantee, and the manual protocol does not install it.

Offline command-graph, existing driver and final-checkpoint gate:
**131 passed**. Reproduction:

```bash
# From backend/; no native commands are executed by these tests.
poetry run pytest -c pyproject.toml \
  /tmp/opencode/test_adr024_manual_driver_protocol.py \
  tests/unit/test_autonomous_frr.py tests/unit/test_autonomous_frr_final_checkpoint.py \
  --no-cov -q -p no:cacheprovider \
  --basetemp=/tmp/opencode/adr024-manual-protocol-review-tests
```

Reviewed native source pins:

| File | SHA256 |
|---|---|
| `emulation/autonomous_frr.py` | `9f2b72e5bcf6f5877e7ccb6b6a651fdcab3e74eab76d3656007407a06b92a820` |
| `emulation/autonomous_namespace.py` | `5e9ef621a1a6b8f41e286309ed3527100c4b21c500d8f88d8ba92e17cf75aa57` |
| `emulation/autonomous_driver.py` | `32cb4a1f054ef9896289cf4421ada64193e7ceff84cee30ac91da3c67b5edf0d` |
| `emulation/native_qualification_routes.py` | `1e2d5db7e8f3762bf093cd8acfd5bca8ed10bf86969fdb9186ef3cba1442197c` |

These tests validate the proposed protocol's command expectations; **live native
driver acceptance remains pending the actual serialized campaign and raw replay**.

### Current independent pass/fail matrix

| Obligation | Result |
|---|---|
| Original checkpoint unchanged; derived tensor payload identical | **PASS**, independently compared bytes |
| Unchanged original writer reproduces entire derived bundle; unchanged loader accepts | **PASS**, actual offline execution |
| Only manifest change is truthful rebuilt `lab_image_id` | **PASS**, full manifest equality checked |
| Original v4 archived source/AI source pins | **PASS**; current workspace emulation differs in six pinned files |
| Evaluation-002 seeds versus audited historical reservations | **PASS**, 5,090 exact-hashed documents, 1,342 distinct reserved values |
| Evaluation-002 original five-policy thresholds and plan/script pins | **PASS**, plan `b9e084a2c69241d3d5d3e2f60ab3f9052ee77e713befc1f43403fd21de8e4a30` |
| Evaluation-001 current runner pin | **FAIL for execution**, correctly preserved as no-traffic preparation; retirement explained in owner handoff |
| Fresh five-policy measured report/raw reconstruction | **PASS**, exact final report equality, all seven unchanged gates, 300 raw measurements / 240 decisions |
| Actual passive bridge/continuous qualified provider acceptance | **NOT ESTABLISHED** by raw-log attachment metadata |
| Finite-quota mathematical implication under explicit premises | **VALID CONDITIONAL THEOREM**, not installed calibration |
| Positive-traffic native admission with unchanged zero drift budget | **FAIL / infeasible** for the proposed S=0, positive quota/error |
| Full native source/accounting/demand/provider/deadline proof | **BLOCKED**, detailed below |

The amendment permits a derived deployment artifact and a fresh benchmark; it does
not change any safety threshold or grant native activation. Previous Q6 remains
true for the **original** artifact, while derived-artifact admission is now an
authorized distinct route to qualification. `RuntimeQualification.md` currently
describes the earlier original-artifact blocker; retain it as historical evidence
and add the new result rather than claiming that exact image identity was restored.

### Derived artifact and preregistration review

Read `scripts/adr024_campaign.py` as it appeared; independently used the pinned
original `artifacts.py` writer/loader from `ai-engine/artifacts/adr014-001/source/`.
`loadCheckpoint(parent,resume=True)` restores optimizer and RNG as well as model
state; `saveCheckpoint` then writes unchanged tensors with the new provenance.
No training or loader patch is present in the reviewed derivation. A second write
by this reviewer in a temporary directory matched the full derived bundle exactly.

- Parent: `5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`.
- Derived: `77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614`.
- Entire tensor payload, including optimizer/RNG:
  `3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967`.
- Actual new image binding:
  `sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7`.

Independently checked all archived lab pins and all original AI source pins.
Current `actions.py`, `compose.yaml`, `experiment.py`, `ospf.py`, `runner.py`, and
`workloads.py` differ from the parent; therefore the current checkout is not an
exact v4 replacement. A new bfifo/TBF native topology also cannot inherit this
netem/HTB measured runtime qualification without separately admitted evidence.

Reproduction script: `/tmp/opencode/adr024_independent_runtime_review.py`.
Preflight result: `/tmp/opencode/adr024-independent-runtime-review-preflight-002.json`.
It never imports or invokes the campaign runner; it imports only original frozen
artifact/report code for offline checks, and independently computes seed sets.
The historical inventory was complete for `ai-engine/artifacts` and
`emulation/output` at review time; all 5,090 document hashes and per-document seed
sets matched, with no selected seed in the union. This does not automatically
cover concurrent `/tmp` campaign reservations. Parent must retain the exclusive
reservation ledger, including retirement of unexecuted evaluation-001 before
evaluation-002 uses the same seeds. No post-measurement seed changes or outcome-
dependent retries are accepted.

The runner preserves .02 strict constant-policy reward margins, positive lower
95% paired-seed reward bounds against **both** constants, positive OSPF goodput
lower bound, negative OSPF RTT upper bound, and strict majority correct actions
in both scenarios (24 steps each). Five policies, 12 matched seeds, four steps,
2-second windows. The independent final checker is prepared to require exact
equality to the original raw report reconstruction and independently recompute
all seed-mean intervals using t=2.2010 (df=11), not 48 pseudo-independent steps.

**Submission requirements still open:** independent pre-acquisition plan receipt;
source-pinned attempt/retirement and global serialization record; all raw captures
and failed attempts; exactly five complete sessions with actual image/spec/source
identity; original raw reconstruction and unchanged gates. `campaign.lock` is
per-output-directory and is not a host-wide lease. Parent's external exclusive
lease must cover preparation-to-cleanup and be retained as evidence.

`collect()` writes a session log before reset, then writes `feed-attachment.json`.
That is an acquisition-log receipt, **not a running passive bridge or durable
recommendation pipeline**. Report benchmark acquisition separately from the ADR024
continuous observation/inference requirement. A producer-written attachment time
or a `qualified` flag must not become independent authenticity or author approval.

### Native finite-quota theorem: what is justified

Let an epoch start with no uncharged in-flight bytes; every enqueue-causing byte
must traverse the reviewed nonrenewable quota, with exact byte conversion and no
post-hook duplication/segmentation expansion or bypass. The quota's monotone
atomic accumulator admits only packets whose cumulative charge stays <= C; no
wrap/reset/replacement/replenishment occurs. Then accepted volume over the entire
epoch is <= C, irrespective of hook-to-enqueue delay. For a queue observation at
time r no later than the certificate's t0, nonnegative departures/drops imply:

```text
q(t) <= q(r) + C <= q_observed + eta + C
for r <= t <= epoch_end.
```

Using H>=h_min and a=C/h_min yields the conservative existing-model upper
`U=q_observed+a*H+eta >= q_observed+C+eta`. This covers arrival growth between an
earlier read and t0 as well as later arrivals, **once using the full quota**;
do not add an empirical hook delay. It is a finite-volume, nonnegative-service
theorem, not an indefinite offered-rate/service/throughput promise. Its error
premise still needs derivation; sequential stats conservation can have a residual
even if integer counters themselves are exact.

Remaining obstacles:

- **Policy:** every positive a or eta makes upper drift positive with S=0. The
  zero-budget policy cannot pass. A one-queue test's B=2^33 is not an existing
  22-queue approval. Merely being expressible in `SafetyPolicy` does not authorize
  a new positive B; ADR024 explicitly prohibits relaxed safety thresholds.
- **Minimum window:** a=C/h_min bounds full-window arrivals only for h>=h_min.
  `NetworkQualificationConfig`/`LoadedCalibration.validate_action` currently admit
  shorter positive horizons without a minimum. A fixed-H provider is helpful but
  all admission/receiver paths and empirical campaign rows must enforce the same
  reviewed horizon. Shortening it can invalidate the rate representation.
- **Hard deadlines:** no quota or bfifo occupancy invariant guarantees that a
  Linux userspace/netlink operation finishes before certificate expiry. Current
  observation-anchored strict age+remaining-delay gates still apply. Post-check
  descheduling, partial update and late kernel effects need an enforceable fence
  or remain blocked; observed maxima and timeouts are not proofs.
- **Attribution:** six disjoint per-egress classifier classes are useful, including
  ARP/OSPF/reverse flows. `execution_map` constructs 22 directed egresses and 48
  logical demands, but no compatible complete provider adapter is supplied. Old
  `CausalDemand` cannot encode ARP; old capture validates netem/HTB and stable paths.
  Do not label new bfifo captures as that instrument. Late old-route bytes and
  partial fallback routes need explicit all-prefix path readback/trace review.
- **Aggregate versus demand bounds:** a shared C is a coupled aggregate budget,
  not independent allocated quotas for every routed/control demand. The shield
  sums each demand's upper rate along its selected path. Assigning C/h_min to
  each of six potentially present demands and only C/h_min to the queue fails
  `understated_attributed_arrivals`. Supply defensible individual envelopes whose
  sum is covered (possibly more conservative), enforce separate allocated quotas,
  or explicitly review a contract capable of representing coupled demand sets.
  Do not understate a demand merely because the aggregate quota limits the sum.
- **Units/departures:** prove skb length to qdisc accounted bytes, segmentation,
  root/leaf drop and dequeue/requeue semantics under the actual pinned build.
  A separate upper-departure rate including burst/finite initial backlog is still
  needed for the generic validator. Nominal TBF rate is not that bound.
- **Mutation:** the pure mutation manifest lists prefixes, not their resolved
  transient forwarding paths. Prefix enumeration alone does not exclude loops,
  duplication, OSPF fallback outside the union or altered background routing.

### New native-code review findings

**Q7 — feasibility arithmetic can disagree with the unchanged shield at a boundary.**
`analyze()` computes U/drift from exact C/h_min, but emits outward-rounded float
rates/errors that the shield then treats as exact IEEE inputs. Example: C=65536,
H=h_min=3, eta=2048, q=0, Q=67584. The compiler reports U=67584 and passes; its
serialized rate times 3 plus eta is strictly greater than 67584, so the shield
rejects. This is a false-feasibility/validator-limit bug, not an unsafe shield
acceptance. Required fix: compute feasibility, U and drift from the final emitted
conservative numeric fields, or emit an exact supported representation. Do not
increase Q to hide the mismatch.

**Q8 — raw replay is only a partial native validation gate.** Reproductions show
`replay_window` still passes if the parsed/raw `links`, `routes`, `rules` and
`neighbors` are arbitrary matching JSON, command `argv` is wrong, or TBF burst/
peakrate options change while rate stays the same. The implementation explicitly
leaves burst semantics to external review; its `raw_replay_passed` must not be
reported as full enforcement/topology proof. Required installation evidence is an
independent complete parser/check of these retained fields, actual offload/bypass
inventory and exact source-reviewed options. Similarly global/class/drop counter
partitions are not reconstructed by this replay; separately reconcile trace/skew
before claiming complete attribution. Preserve these limitations even if ordinary
fixture tests pass.

### Kernel 7.2.6 scientific provenance and source obligations

Read-only host identification reports `7.2.6-arch2-1`, PREEMPT_DYNAMIC, build
`Mon, 14 Sep 2026 22:41:30 +0000`. Installed packages report linux and linux-headers
`7.2.6.arch2-1`, nftables `1:1.1.7-3`, iproute2 `7.2.0-1`. These host userspace
versions are **not** automatically those inside the Debian-based evaluation image.

The cached signed binary package
`/var/cache/pacman/pkg/linux-7.2.6.arch2-1-x86_64.pkg.tar.zst` has SHA256
`0cb7a38236285170db963826d2515c0de81b83b66ba4236da5a85ee6bc932362`.
`pacman-key --verify` returned a good signature for Arch packager heftig, key
`83BC8889351B5DEBBB68416EB8AC08600F108CDF`. Read-only archive extraction confirmed
that installed vmlinuz, nft_quota, nft_limit and sch_tbf module bytes exactly match
that package. `.BUILDINFO` pins PKGBUILD SHA256
`d305de4d7419feba3409d67234e961e7ea4a26f2f2622585b4179dfa4d5ad98f`.

Resolved Arch tag `v7.2.6-arch2` through the repository API to commit
`4498b7f9a5ba741370b6ca880fa047cee00c8d11` (API reports a verified signed tag).
Retrieved actual file bytes through the GitHub contents API at that commit,
verified their Git blob IDs and retained SHA256s:

| File | SHA256 |
|---|---|
| `net/netfilter/nft_quota.c` | `cc545927fcf507024b2daff8a984b3ca07f52d7f15e7630bfe99e8d9b6580d64` |
| `net/netfilter/nft_limit.c` | `57757198654d1640befb6a99f73ab40c008d163c635e6646a1904951bde30fea` |
| `net/sched/sch_fifo.c` | `41e4cdc591d3e742e21941e2690957ab7e796f58a1907eeb52e079426ffb9f6f` |
| `net/sched/sch_tbf.c` | `418bbc522960c69f264fe76ca20a23158a9f93c84738e6f75d08de71c94e3813` |
| `include/net/sch_generic.h` | `fda8980ad982148acd88cebe3bddda0bdbed45477ca4a8c7fd58c4a0d3aae00f` |

Original bytes, package metadata, local binary hashes and retrieval URLs are in
`/tmp/opencode/adr024-kernel-source-review/record.json` and adjacent files.
The original upstream v7.2.6 archive's advertised SHA256 is
`039aef84f2b0994aeda3f4fcfc3d02ec9d7a9bbb9020ea264c43f446c860f606`
for `linux-7.2.6.tar.xz`, from kernel.org's signed-checksum text; this review did
not download/verify that whole archive or independently authenticate that signature.
Arch's exact PKGBUILD fetch encountered an Anubis challenge, and raw GitHub fetch
encountered HTTP429; the commit-pinned API file retrieval succeeded.

**What the reviewed source actually supports:**

1. `nft_quota.c:25–31,62–64` atomically charges `skb->len` before comparing with C.
   With the compiler's inverse quota/drop rule, the packet crossing C is rejected
   whole, not admitted with one-packet overshoot. Concurrency does not evade that
   monotone prefix bound. All offered packets consume credit, even subsequently
   rejected classes. `:147–165` explicitly supports reset and caps reported used
   bytes; a capped readback cannot establish no reset or absence of overflow.
2. `nft_limit.c` uses a locked token accumulator and integer packet cost
   `floor(1e9/p)` for a one-second unit. The proposed outward rate and burst
   formulas match that algorithm for p>0 with positive cost. Clone resets tokens
   to full; the no-clone/no-refresh epoch premise is material.
3. `sch_fifo.c:19–26` admits only when accounted backlog+packet length<=limit,
   using a widened u64 addition. `sch_generic.h:1109–1113,1162–1169` increments
   on enqueue and decrements/increments byte-service stats on dequeue. Under
   the pinned software queue/locking/ownership premises this supports the leaf
   occupancy invariant. It does not bound total kernel buffers or loss.
4. For this **bfifo child**, TBF uses `qdisc_peek_head`, a non-removing peek;
   only successful token admission calls `qdisc_dequeue_peeked` then the bfifo
   dequeue. Thus an unserved peek does not itself count as bfifo departure in
   this reviewed path. Root/device requeues and driver transmission remain outside
   the leaf proof and require exact accounting scope.
5. `sch_tbf.c:258–262` can drop at the **parent** before the bfifo child sees a
   packet, and can segment GSO. Therefore unchanged leaf-drop count alone cannot
   prove every accepted nft byte entered bfifo. Root drops must be inspected or
   ruled out by source-reviewed max-size/offload/length premises. An oversized
   parent drop can otherwise hide within eta. TBF token costs use integer
   `psched_l2t_ns` arithmetic (`sch_generic.h:1444–1455`), so a service-upper proof
   must include its actual quantization/overhead/mpu, not ideal real-number R.

**Remaining identity gap:** signed package identity plus uname plus a same-version
source tag is not a complete proof that these source bytes/config/patches generated
the running machine code. Obtain the authenticated exact PKGBUILD matching
`.BUILDINFO`, its source/patch/config hashes, and build/installed/loaded-image
mapping; account for live patches/modules and actual namespace settings. Header
config hash is `627d3a92c1f1475dbc362d7508982068815a60d9365ac4394dcf20a5e9923ac0`
with HZ=1000, quota/limit/TBF modules, FIFO built-in and PREEMPT_DYNAMIC; none grants
a hard userspace actuation deadline. This is a **scientific conditional derivation
and provenance record**, not speculative source equivalence or an accepted
`BoundGuarantee` digest.

Verification: `/tmp/opencode/test_adr024_native_review.py` plus the proposed native
unit suite: **31 passed** (four review reproductions and 27 owner tests). No native
commands or sockets executed. These results include the Q7 mismatch and Q8 missing
checks; they are not a native qualification pass.

**Q7 follow-up: CLOSED in the current compiler.** During review the owner changed
`analyze()` to calculate U/drift from `Fraction(outward(a/error))`. The original
false-pass reproduction consequently failed, as expected for a corrected bug;
the reviewer test now requires boundary rejection. Added a fifth reproduction:
a 100-byte root TBF drop is ignored when its conservation residual fits eta and
the bfifo leaf reports no drops. This extends Q8's still-open enforcement scope.
Final compiler/review gate: **32 passed** (five review tests plus 27 owner tests).
An earlier standalone temporary-test invocation had an import-path collection
error; its test-only sys.path was corrected before the completed checks.

### Newly delivered v2 semantics and clocks: scoped review

Read the owner continuation and actual new code as it appeared:
`calibration_verification.py`, `calibration_verification_models.py`,
`causal_frames.py`, `native_qualification_causal.py`, and
`native_qualification_clock.py`. V1 retains actual-departure semantics and rejects
new service fields. V2 adds separately accepted source evidence, explicit burst
and minimum horizon, and a full-window busy-trace gate; it does **not** silently
turn idle departures into available service. Independent capacity remains a
separate inequality. Past busy traces are correctly insufficient for future busy
guarantees. V2 installation and action validation explicitly refuse until runtime
mapping is implemented. This keeps Q1/Q2 a documented v1 limitation while offering
bounded offline semantics, not closing future native admission.

The new integer-clock path constructs its observation from the same capture,
preserves raw nanoseconds, deterministically floors to nonfuture representable
UTC, binds the raw capture digest and budgets quantization uncertainty. It no
longer fixes Q5 by overwriting raw timestamps. Its tests exercise acquisition with
native-command doubles through frame construction. This is a legitimate software
repair for **new v2 captures**, not a way to freshen v1 or align an unrelated v4
model observation. Authentic v2/native packet evidence is still absent.

Independent executed gate: native-v2, old causal, independent-validation and five
review tests: **72 passed, 1 skipped, 1 deselected**. Skip is the explicitly opt-in
authentic retained v2 capture; deselection is live UDP socket acquisition. No
measured v2 acceptance is inferred. Complete ARP/bfifo provider mapping and hard
execution deadlines remain blocked.

Rebuilt registry/qualification integration was also read as it appeared. Its
parent lineage validation requires complete tensor byte equality and only image
metadata differences; both original and rebuilt protocol branches use the same
strict gate function. Existing live-provider plus rebuilt-protocol tests:
**59 passed**. Seed-audit runtime validation checks the provided document's
consistency, not the external historical files; this review's separate full-file
hash/seed reconstruction is therefore essential and must precede protected trust.

### Incremental fresh evidence replay

`/tmp/opencode/adr024_review_completed_sessions.py` replays only completed sessions
and retains exact summary/raw hashes. Already reviewed sessions are checked for
byte stability rather than recomputed while other policies are running.
First completed PPO session: **PASS**, original parser/reward/decision/route/drain
reconstruction, all 60 reset+step measurements and 48 decisions, exact 12 seeds,
truthful derived provenance and raw-log attachment chronology. Result retained at
`/tmp/opencode/adr024-session-review/ppo.json`. At that incremental checkpoint
remaining policies/comparisons were pending; no single-session pass granted model
qualification. Final results follow.

### Final fresh five-policy acceptance — PASS for the scoped rebuilt benchmark

All five sessions completed within the recorded campaign elapsed time
1475.774 seconds (1800-second preregistered cap). Independently matched **all 300
reset/step IPC observations** to the original JSON copied from the five stopped
owned labs; all **60 native schedules** are retained. Each policy has exactly 12
seeds and 48 valid decisions, no invalid windows, expected scenario pairing,
truthful new image/source/spec identities and matching raw hashes. The original
frozen parser reconstructs measurements/rewards/drains/routes and reproduces PPO
actions/probabilities; complete five-policy report JSON equals the saved report
exactly. Retained image inspections and all five exact-ID cleanup/absence records
also pass; this reviewer performed no live inspection or lab mutation.

Final report SHA256:
`e6ee9c1bd99e3f6961db497db664335684fa277bd1a1c86a8034570ac116056d`.
Independent result `/tmp/opencode/adr024-independent-runtime-review-final-002.json`,
SHA256 `002d31c17281857c118c414d6c93c47e1ca5b083e661abf8cca3778316e5d800`.
Per-session replay and copied-lab hashes: `/tmp/opencode/adr024-session-review/`.
The actual new `validate_rebuilt_lineage` and `validate_benchmark` gates also
passed on these real retained bytes using original frozen code staged under
`/tmp`; reproduction `/tmp/opencode/adr024_review_registry_gate.py`. No protected
registry was installed and no live provider invoked by that check.
Reviewed gate source pins: registry
`35672778b1d914e587048adeec38fa1e27e5027ba6f33c80467b625ff2366a9f`,
frozen live runner
`22a8a84d6d3c560f3fe3e6d3a37c52edebf9af86d2f1e46e0ad923eace66f179`.

Independently recomputed paired seed-mean intervals (12 pairs, df11, t=2.2010):

| Preregistered gate | Measured delta | 95% interval | Decision |
|---|---:|---|---|
| PPO reward versus constant0, mean>.02 and lower>0 | 1.1529718383 | [0.3830821106, 1.9228615660] | PASS |
| PPO reward versus constant1, mean>.02 and lower>0 | 1.1842294235 | [0.3914077025, 1.9770511446] | PASS |
| PPO goodput versus OSPF, lower>0 | 1.9767358117 Mbps | [0.6645044226, 3.2889672008] | PASS |
| PPO ICMP RTT versus OSPF, upper<0 | -129.3162708333 ms | [-217.2049607721, -41.4275808946] | PASS |
| Correct action strict majority on path0 and path1 | Independently counted on 24 steps each | Both >12 correct | PASS |
| Complete comparable held-out schedules | Five complete matched sessions | Same 12 seeds/scenarios/horizons | PASS |

This is independent **software-lab benchmark acceptance** for derived checkpoint
77dae44… and rebuilt image954462…, not a human instrument attestation or proof of
general superiority. Unchanged original thresholds were used; the original
checkpoint and its historical qualification remain distinct. Freshness/source
checks were not bypassed. The finite-sample t intervals retain their stated
normality/exploratory limitations.

`RuntimeQualification.md` now records that preparation001 was never executed
and was superseded before traffic after import/budget corrections. The active
002 plan's exact digest was independently read and recorded during this review
before completed outcomes; the complete historical reservation audit was separately
reconstructed. No new retrospectively dated preregistration receipt was created.
An external protected receipt/global lease is still a parent installation-evidence
obligation rather than a self-authenticating producer JSON field.

**Not passed by this result:** actual continuous passive-bridge/qualified-provider
and durable recommendation acceptance; installed native calibration; finite native
actuation deadline; bfifo/control-attribution adapter; physical RF. Keep those
rows blocked/pending and retain `safety_calibrated=false`,
`autonomous_activation=false`. This reviewer accepts the exact report's scoped
metric result, not any unsupported safety/activation claim.

## Concrete findings for the parent

### Q1 — service-availability is incorrectly tested as mandatory departures

`backend/app/modules/autonomy/calibration_verification.py:98–106` requires
`departures >= service_lower * dt` for every interval. An empty queue served by a
100 B/s server legitimately departs zero bytes; a 10-byte queue can drain in 0.1 s
and then idle for 0.9 s. Both satisfy their queue bound but fail solely with
`service_inequality_failed`. This is a **false-rejection/model-expressivity issue**
if `service_lower` means available service while backlogged. The current test is
valid only for a separately established continuously backlogged window or an
explicit guarantee of actual departures.

Required owner action: document the present restrictive semantics or version a
busy-period/service-curve-aware verifier with independent timestamped backlog
evidence. Do not substitute `min(q0 + total_arrivals, rate * dt)`: late arrivals can
still make that lower-departure claim false. Do not add artificial offered traffic,
invent departures or remove the endpoint/dynamics gate to force acceptance. The
narrow zero-service-lower-bound regime below avoids this particular limitation.

### Q2 — a tc shaping rate is not a burst-free instantaneous capacity

The same verifier compares departures with both `capacity * dt` and
`service_upper * dt` (`:101–102`). Native `autonomous_causal.py:60–77,152–155`
requires configured capacity to equal HTB's reported `rate`. HTB/TBF explicitly
allow bursts; HTB can additionally borrow up to `ceil`. For example, 200 queued
bytes with at least 200 available tokens can legitimately depart during 0.125 s
at a nominal 1000 B/s shaping rate. The current representation rejects this as
both capacity and service-upper violations (125-byte limits).

This is a legitimate native model/instrument mismatch, not evidence that Linux
violated its configured shaper. Review `rate`, `ceil`, `burst`, `cburst`, hierarchy,
packet accounting and offloads. A cumulative bound generally needs a burst term
and a minimum supported time interval, or a separately justified instantaneous
capacity. Do not change recorded HTB rate to a larger number merely to pass. An
average or observed maximum departure rate is not an enforceable future bound.

### Q3 — aggregate byte checks do not supply the missing dynamics theorem

The implemented upper bound is `U=max(0,q0+(a-s)*dt)+E`. Even accurate endpoint
totals do not justify subtracting service available before late arrivals. Both
the existing safety document and validator correctly leave proof acceptance to
an external protected guarantee. The loader only reads/hashes its eight evidence
references (`calibration_verification.py:237–240`); it does not prove their content.
An internal author putting its own digest into `accepted_guarantee_sha256` is not
independent review. A `reviewer_id` string supplies no authentication.

Old/new transition attribution uses the union of route egresses, but the numeric
bound uses the **new action's profile for the entire interval** (`:76,94–96`). Every
accepted profile must therefore conservatively cover all admitted predecessor
actions, pre-dispatch waiting, mixed-route updates and recovery. A new-route-only
arrival bound is insufficient even when old-route arrivals are correctly labelled.

### Q4 — positive error and zero drift can make real safe states unrepresentable

With `q0=0`, `a=s=0`, `E=1`, the model computes `U=1`, drift `0.5 bytes²`, and
rejects a zero drift budget despite an actually empty queue. This is a documented
conservative limitation, **not permission to zero sensor error or relax the
policy**. A hard queue cap also does not imply nonpositive quadratic drift:
`q0=0 -> q1=1 <= cap` increases the Lyapunov function. A cap-only theorem cannot
silently install as the existing zero-budget bounded-fluid certificate.

### Q5 — native timestamp precision blocks otherwise aligned causal frames

`emulation/autonomous_causal.py:78` retains `time.time()` as a binary float;
`autonomy/causal_frames.py:73` requires exact equality to
`observation.observed_at.timestamp()`, whose datetime has microsecond precision.
At `1789895035.1234562`, converting through UTC datetime changes the float. A
native-consistent capture therefore fails `causal_frame_not_attested_or_aligned`
even when every identity/pin matches. The existing test in
`tests/unit/test_autonomous_causal.py:92–95` rewrites the endpoint and read-finish
times to a representable boundary, masking this acquisition/registration problem.
The review reproduction preserves the raw endpoint and verifies rejection.

Required owner action: preserve raw integer clock values and define a canonical
observation boundary/conversion with explicit rounding/skew uncertainty and a
digest binding to the raw capture. Apply it consistently at acquisition, passive
observation and causal registration. Do not rewrite historical raw timestamps or
replace equality with an arbitrary tolerance. Precision repair alone also cannot
align a model observation acquired at a genuinely different time.

## Narrow native theorems that could be valid

### A. Closed native queue epoch (compatible arithmetic, conditional admission)

For each exact named native queue, establish before observation that **no enqueue
is possible for the whole epoch** and no operation can increase the accounted
backlog. Dequeues/drops are nonnegative. Then conservation gives

```text
q_i(t) = q_i(t0) - departures_i(t0,t) - drops_i(t0,t)
0 <= q_i(t) <= q_i(t0) <= Q
V(q(t)) - V(q(t0)) <= 0
```

Thus `a=0`, `s_lower=0`, `E=0` is legitimate only with exact aligned state and the
proved closed-queue condition. `E=0` is a proof obligation, not a convenience.
No positive service or finite Linux scheduling latency is needed for this queue
theorem. Source shutdown alone is insufficient: upstream qdiscs, driver queues,
in-flight veth packets, netem delayed packets, TCP retransmissions, ARP/ND, OSPF,
ICMP and local processes can still enqueue. Closing a boundary before a pipeline
has drained also does not close each downstream queue. Prove barrier semantics
at each enqueue point, or prove the entire pipeline empty and permanently sealed.

Starting with all queues empty and enforcing the seal throughout permits a
quiescent route-readback/recovery test. It establishes **native route changes
under sealed zero-arrival conditions**, not adaptive operation under traffic or
useful positive service. Unsealing ends the theorem. Hard blocking may change
historical model input/runtime semantics and therefore needs separate equivalence
review; route identity alone does not establish that equivalence.

The existing native instrument requires `netem` under HTB and exact nft rule sets.
Replacing it with an application FIFO, inserting extra rules into its exact
instrument table, or relabelling another qdisc as netem is not acceptable. Any
compatible sealing mechanism needs explicit source/hook/counter-order review and
separate enforcement readback. Nonzero drains still need a justified service
**upper** profile; a fully empty epoch avoids burst departures but does not prove
that the generic upper profile is valid outside that epoch.

### B. Native byte-limited queue occupancy (weaker, not current drift admission)

For a pinned, independently reviewed `bfifo` implementation with limit `B`, an
enqueue accepts a packet only if the accounted backlog remains within `B`;
dequeue cannot increase it. From an initially valid queue, induction proves
`q(t)<=B` irrespective of offered load or service stalls. Define exact skb/byte
accounting, offload/segmentation behaviour, ownership and permissible mutations.
This covers that qdisc's accounted backlog only, not socket memory, sibling
qdiscs, device rings, end-to-end delay, losslessness or throughput. Drops are
expected under overload. The current native collector requires netem, so bfifo
is not an already admitted drop-in runtime.

For `pfifo`/netem packet limits, bytes require a separately enforced maximum
accounted packet/skb size, including GSO and headers. A packet limit alone is not
a byte cap. Neither hard-cap theorem proves `V(next)<=V(before)`; use a separately
approved contract if that weaker claim is desired. ADR024 does not authorize
relaxing existing thresholds to achieve acceptance.

## Exact acceptance requirements for a future native submission

1. **Pre-acquisition freeze.** Submit the full protocol, named independent groups,
   all actions and directed transitions (including holds/recovery), numerical
   thresholds, time windows, attempted-run/failure retention rules and source/image
   manifests. Independent timestamped receipt must precede every sample. A revised
   protocol after failure needs a new campaign/receipt and fresh groups.
2. **Enforced arrivals.** State precisely which queue boundary is regulated, bytes
   counted, token-bucket rate and burst (if used), maximum packet/skb size,
   offloads, all foreground/background/control demands and bypass prevention.
   Bound upstream backlog/in-flight arrivals and old/new path combinations. A
   generic envelope is `A(s,t)<=sigma+rho*(t-s)`; using only `rho` discards burst.
   The current schemas have no explicit burst term/minimum horizon, so explain
   exactly how their constant rates/errors conservatively represent the theorem
   over **every admitted horizon**, or report a schema/model limitation.
3. **Service and queue semantics.** Review actual kernel/iproute2/FRR versions,
   hierarchy, rate/ceil/burst/cburst/quantum, parent contention, outages and queue
   accounting. A positive service curve must hold during backlogged periods under
   all allowed conditions. General-purpose Linux scheduling and a `tc rate` value
   alone do not prove positive wall-clock service. Preserve raw byte and packet
   counters; dropped-packet counts cannot become drop bytes without exact size
   evidence. A bound that remains safe with service zero must say so explicitly.
4. **State and sensors.** Retain raw nft/tc/class readbacks with per-read spans,
   aligned before/after data, complete demand counters and conserved bytes. Define
   the errors from sequential reads, packet accounting, clock quantization and
   multi-queue sampling using enforced limits, not observed residual maxima.
   If a closed empty epoch makes all reads invariant, prove that invariant.
   Counter reset, unexpected demand, modified qdisc, missing/drop-byte evidence or
   violated read skew rejects the sample and must remain in the attempt ledger.
5. **Clocks and deadlines.** Retain monotonic integer timestamps and the explicit
   mapping to UTC, uncertainty and suspend/clock-jump policy. Horizon starts at the
   actual observation boundary. With age `now-t0` and remaining action bound `L`,
   require `age+L < max_delay` and `age+L < dt`, plus strict freshness/calibration
   expiry, including lock wait, dispatch, every route update and final readback.
   Observed completion maxima, subprocess timeouts or post-hoc overrun detection
   are not hard completion guarantees. A sealed queue remains safe during a stall,
   but that fact does not satisfy an independently required transition deadline.
6. **Exact action/runtime mapping.** Bind action index, model action ID, FRR plan,
   namespace PID/start/inode, device/interface/qdisc handle, directed demand/route
   chain and both route directions to reviewed native commands/readback. Cover
   transient loops, loss, mixed paths, compensation and baseline restore. Pin
   executable frozen sources, receiver sources, model bytes/contract/spec and real
   image identities. A rebuilt image has a new identity. Current-v5 sources cannot
   be presented as recovered v4; equivalence must be an independently justified
   scope, including instrumentation and enforcement changes.
7. **Separate software attestation.** ADR024 permits an explicitly named software
   collector/operator identity and independent software review for
   `isolated-emulation`. Bind identity evidence, source/image/environment, original
   capture digests and exact review result. `operator-attested` must clearly name
   the software agent/operator, never suggest a human signature. Use
   `authenticated-instrument` only if an actual authenticated receipt exists.
   Independently accepted digests enter protected trust configuration separately
   from producer output. A matching hash proves byte identity, not measurement
   authenticity, physical equipment certification or theorem validity.
8. **Complete replay and runtime acceptance.** Independently reconstruct all
   preregistered train/holdout rows and action/transition coverage using original
   native sources; pass all inequalities without excluding failed observations.
   Separately pass installation/runtime/model compatibility and receiver expiry,
   authorization/revocation, stale evidence, readback, partial failure,
   compensation and cleanup checks. Qualification/recommendation tests can pass
   while autonomous activation remains blocked. Preserve that distinction.

## RF and geometry assessment

`simulation/spatial_rf.py` maps Network `(X,Y,Z)` Y-up to RF `(X,-Z,Y)` Z-up;
requires explicit persisted scene/geometry hashes, complete canonical-wall
references, known attenuation and ancestor placement accuracy; and rejects tilted
walls. Its model reduces walls to finite centre planes: thickness/volumes are not
qualified RF propagation physics. Declared accuracy metadata is not independently
surveyed accuracy and is not propagated into a guaranteed RF error interval.

`qualification_rf.py` fits only training rows, independently reconstructs held-out
errors and retains `physical_qualified=false`, `physical_safety_authorized=false`.
Hashed registration bytes and an environment label do not supply a survey. The
code and geometry tests can be verified without RF equipment. Measured physical
RF acceptance cannot be completed in this environment and must remain explicitly
blocked; simulated dBm and nominal wall coefficients cannot close it.

## Recovered-runtime evidence review

Read the newly available `/tmp/opencode/nanfo-adr024-runtime-xfwykjez/` files
`audit.json`, `recovery.json`, `registry.template.json`, `validator-boundaries.stdout`
and the recorded rebuilt probe. This is review of another workstream's retained
output, not a new image inspection/build or independently witnessed execution.

The recovery report distinguishes the absent historical image
`sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff`
from rebuilt image
`sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7`.
It reports recovered v4 spec/source identity, but explicitly sets
`historical_image_identity_reproduced=false`, `live_qualified=false`,
`measurements_started=false` and `rebuilt_live_inference_compatible=false`.
Those limitations are consistent with the recorded validator results.

`ai-engine/src/nanfo_routing/cli.py:1049–1052` requires both exact environment spec
and exact provenance equality to the checkpoint. Historical replay succeeds;
the copy containing the rebuilt image identity fails with
`inference image/source provenance differs from checkpoint`. Incorrect source
and spec controls also fail. Historical inference has `qualification_checked=false`
and `execution=not_applied`; it is not evidence of fresh operational qualification.

**Q6 — rebuilt-runtime admission is an expressivity limitation, not proof that the
rebuilt runtime is behaviorally wrong.** Exact source/spec recovery does not satisfy
the existing image-identity check. Honest new-image provenance must keep failing
until an explicitly authorized, independently reviewed compatibility/admission
mechanism or separately qualified model exists. Do not lie in
`NANFO_LAB_IMAGE_ID`, overwrite measurement provenance, change the historical
checkpoint manifest, or treat an FRR equivalence document as an automatic override
of this separate inference gate. A valid extension would preserve both identities,
pin all relevant dependencies/source/kernel assumptions and independent evidence,
reject unreviewed/source/spec mutations, and scope qualification to the new runtime.
This workstream neither implements nor approves that extension.

The registry file is a **template** with placeholder scopes/timestamps, not an
installed qualified registry. Report source recovery, build identity, historical
replay, new-runtime inference, fresh measurement qualification and native safety
installation as separate acceptance rows. The native deadline/queue proof cannot
resolve this model admission issue.

## Offline verification checkpoint

Analytical counterexamples only, with explicitly synthetic in-memory campaigns;
no raw-measurement attestation or trusted installation generated:

```bash
# From backend/
poetry run pytest /tmp/opencode/test_adr024_qualification_review.py \
  --no-cov -q -p no:cacheprovider
```

Initial result: **7 passed**, including two Q1 false rejections, Q2 token-bucket burst,
compatible sealed queue arithmetic, positive-error/zero-drift limitation, late
arrivals and whole-horizon arrival-envelope obligation. These passing tests
reproduce limitations; they are not a passing measured qualification campaign.

After adding the Q5 precision reproduction, the combined offline gate passed:

```bash
poetry run pytest /tmp/opencode/test_adr024_qualification_review.py \
  tests/unit/test_independent_validation.py tests/unit/test_spatial_geometry.py \
  tests/unit/test_spatial_rf.py tests/unit/test_spatial_registration.py \
  -k 'not acquisition_records_actual_socket_events_and_replays' \
  --no-cov -q -p no:cacheprovider \
  --basetemp=/tmp/opencode/adr024-qualification-review-pytest
```

**246 passed, 1 deselected** (actual socket acquisition excluded). Eight review
tests are included; their native instrument is a deterministic test double, not
a live network. `git diff --check` passed.

### Previously acquired measured FIFO evidence: replay completed

Read-only replay of the preserved ADR023 measured application-FIFO campaign
succeeded for **8/8 windows**, using the recorded preregistration receipt rather
than creating a new one. Manifest SHA256:
`3c18eb100df4c239735df2ee783f3339fe0d6b94618cd149de4009d386446d7d`;
protocol SHA256:
`4d04dc4b9017661d15d6c161a4a14bd437a99b9f362697e449ff46ee6266b784`.
Output: `/tmp/opencode/adr024-qualification-review-existing-fifo-replay.json`.
Both groups reconstruct final queues `0, 896, 384, 1408` bytes from 2048-byte
initial queues. The conditional sealed-queue upper bound remains 2048 bytes and
zero upper drift; transition observations are approximately 25.10–25.91 ms.

This review accepts **consistency of the retained bytes and scoped replay**, not
independent witnessing of their historical acquisition. The available software
receipt itself is not a human attestation. The result correctly preserves
`independent_attestation_accepted=false`, `receiver_installable=false`,
`physical_qualified=false`, `trusted_installation=null`. No new measurement was
acquired and no FRR/kernel claim follows from this application-FIFO replay.

## Authoritative Linux documentation consulted

Fetched 2026-09-20 from the iproute2 manual pages hosted by man7.org:

- [tc(8)](https://man7.org/linux/man-pages/man8/tc.8.html): `bit`/bare rate is
  bits/s; `bps` is bytes/s; bare time is microseconds; bare size is bytes. Verify
  installed JSON encoding and actual readback rather than assuming CLI suffixes
  are preserved. Documentation contains historical implementation notes, not a
  real-time service certification for the installed kernel.
- [tc-tbf(8)](https://man7.org/linux/man-pages/man8/tc-tbf.8.html): initial tokens,
  burst in bytes, rate versus millisecond-scale bursts, downstream adapter queues;
  replacing the inner qdisc makes TBF's original limit/latency ineffective.
- [tc-htb(8)](https://man7.org/linux/man-pages/man8/tc-htb.8.html): borrowing at
  `ceil`, `burst`/`cburst`, hierarchy/default classification and timer constraints.
- [tc-bfifo(8)](https://man7.org/linux/man-pages/man8/tc-bfifo.8.html): bfifo byte
  limit versus pfifo packet limit, tail drop and link-layer-header accounting.

These references constrain a proposed proof; they do not certify the installed
lab's kernel, offloads, measurement hooks or execution deadlines.
