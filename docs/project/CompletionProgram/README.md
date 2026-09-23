# NANFO completion program — capability and evidence register

## Current — ADR027 review consolidation (2026-09-21)

Current authority: [seven-workstream matrix](../ReviewClosure-Completion.md) and
[remaining checklist](../CurrentSprint.md). Current schema is **0029** (0025 retention,
0026 fleet,0027 Autonomy state/execution,0028 experimental ownership and0029 telemetry
coverage invalidation/reconciliation). These migrations do not confer execution
authority. Historical0027/0028 images require matching tooling; any upgrade is a
separately reviewed procedure, while cold restore uses identical images/schema.

- Parent-observed integrated backend **3,939 passed/317 skipped**; frontend **615
  tests/98 files**, lint/types/build/perf pass **394.28/410.16 KiB**. Final assets-owner
  fixture browser **70/70, no retries**; actual production full-stack **5/5**.
- Accepted source-matched core0029 install/11-volume cold encrypted backup/fresh
  restore **28 passed/0 failed/5 blocked**, with **253 deployment tests**. Exact
  images/manifests and optional blocked scopes: [Deployment](../ReviewClosure-Deployment.md).
  Latest **c8rorfzd accepted**, backend `a2bf67af…`, runtime source `f7105617…`.
  Subsequent source changes are only experimental verifier scanner/test (`9e46d086…`
  verifier), not core serving behavior; no whole-tree byte-parity claim. The
  [durable credential-free bundle](../ReviewClosureEvidence/README.md) retains
  new refresh/retention receipts, with new backup/key/result preserved privately locally.
  Historical0027 distributed/fleet results below are not new0029 optional acceptance.
- Clean upgraded PostgreSQL **254 passed/12 skipped** plus real-Redis **12 passed/
  0 skipped** covers all266 selected cases. Development fakeredis Lua/lupa and clean-CI
  EVAL checks fixed; nginx headers/proxy **24 passed/0 skipped**. Remote CI unverified.
- Final portable **441 JUnit/zero skips/11 explicit deselections**; original AI
  environment **463 passed**, reaffirmed. These are not research qualification.
- Bounded metadata-only asset pages and verified selected downloads are delivered;
  opt-in domain-stream retention passed **27 real-Redis cases**. Scheduling/capacity,
  pending/DLQ growth and archive backup remain operator obligations.
- **71 credentials** privately preserved and removed from active files; historical
  exposure unresolved. npm0; exact expiring frozen/unpatched exceptions remain
  [open security obligations](../ReviewClosure-Dependencies.md).
- Actual **017 FAILED**:4/4 smokes,67/68 matrix outcomes completed/1 invalid
  (`path1-1564-qualified`, `protected_regular_owner_file_required`); all20 fault
  outcomes completed. Original frozen source/model unchanged. Active atomic-replace
  read race reproduced/repaired with protected bounded reopen; frozen018 gates
  **115 backend passed/3 historical skips,34 receiver passed,2 STOP passed**.
- Independent018 review accepted the protected-read fix and reconfirmed017 failure.
  Count-only1342 was falsely reserved; active extractor corrected with60 passing tests.
  Fresh plan **BLOCKED**:996/1000 genuine/preregistered train-operational reservations,
  4 available/36 required,deficit32. No018 plan/live acceptance,
  seed reuse or split change. [Experimental status](ExperimentalAcceptance.md).
  Physical RF, intended-user study and repeated training remain
  [evidence obligations](../ReviewClosure-Research.md); experiment completion is open.

The six-area matrix and dated gates below preserve ADR021–024 capability context.
Their “current”, “final” and remaining-sequence wording applies to those historical
checkpoints only; use ADR027 above for present release and review status. This
register does not authorize broader feature expansion or calibrated production autonomy.

## Historical ADR024 measured results — 2026-09-20

- Exactv4 sources recovered; original model/tensors preserved. A new deployment
  checkpoint truthfully binds rebuilt image954462… and independently passed the
  unchanged five-policy/12-seed gates on300 new measured windows/240 decisions.
  Derived checkpoint77dae44a… retains tensor hash3e7e38ab…; no training occurred.
- Actual fresh feed/bridge/confined inference/AutonomyWorker:6 real frames,4 durable
  recommendations, correct opposite-route selection twice per direction, persistence
  ages9.737–14.155s within30s. Staleness, disconnect, expired admission and revocation
  checks passed. No recommendation was dispatched.
- Native manual driver:42 cases,480 policy mutations, both12-command actions,
  STOP0–12, restart/lost-receipt/interrupted-compensation, foreign-state refusal,
  exact restoration and6/6 ping replies per action after unsealing. Independent
  review accepts `native-driver-verified` on the static-FIB Mininet fixture;
  FRR/OSPF daemons were not running and no safety certificate was installed.
- Current backend3282pass/212skip; lint passed. Frontend unchanged527unit/52browser,
  bundle408.36KiB. Current source-matched deployment29pass/0fail/4blocked,216 deployment
  tests,20 installed smoke checks and actual confined benchmark qualification passed.
- **PhysicalRF blocked:** user confirmed no survey files or equipment. **Native
  autonomous calibration blocked:** missing independently accepted causal/transition
  guarantees and joined model/safety/receiver measured acceptance. Ordinary Linux
  timeouts and observed maxima cannot establish hard future completion guarantees.
- Durable evidence: [QualificationEvidence](QualificationEvidence.md),
  [independent review](QualificationReview.md), [current deployment](DeploymentEvidence-ADR024/README.md).
  Reusable exact artifacts: `ai-engine/artifacts/adr024-qualified-001/` (Git-ignored).

The ADR023 capability matrix below remains implementation context; ADR024 results
above supersede its earlier runtime-mismatch/fresh-acquisition blockers.

- **Delivered:** dimensioned canonical geometry/UI/RF integration; configured
  multi-API realtime in `app.main`; all-five-owner evidence retention with actual
  archive/delete/restore; fleet scheduling and durable spool; continuous qualified
  provider and passive-producer code; governed OVS and native Linux/FRR driver code.
- **Accepted corrected release:** schema0027 distributed/core/archive campaign
  **29 passed/0 failed/4 blocked**; packaged fleet **6/6**, deployment tests **216**,
  installed-image smoke **20/20**. Current exact images and source parity:
  [LATEST-HEALTH-FINAL](DeploymentEvidence-ADR023-20260920/LATEST-HEALTH-FINAL.md).
- **Activation blockers:** authentic causal bounds/installation and a joined live
  model→safety→native-receiver campaign are absent. Recovered/requalifiedv4 resolves
  the model runtime mismatch for the accepted recommendation scope; defaultv5 is
  not implicitly substituted. Physical RF survey/calibration remains absent.

Authority: [ADR023](../../adr/ADR-023-operational-twin-runtime.md), continuing
[ADR021](../../adr/ADR-021-measured-twin-completion-program.md) and
[ADR022](../../adr/ADR-022-spatial-assets-history-and-data-lifecycle.md).
The historical ADR023 schema checkpoint was **0027**:0025 retention,0026 fleet,
0027 Autonomy state/execution. Current source targets **0029**, as recorded above.
This register distinguishes source implementation, local measured acceptance and
external physical qualification.

## 1. The six requested areas

| Requested area | Delivered implementation and evidence | Precise remaining work |
|---|---|---|
| **1. Dimensioned canonical geometry** | **Delivered backend and frontend.** Explicit box/slab/wall dimensions, thickness/material/source and nullable attenuation; rigid world transforms, canonical wall→RF conversion, JSON editing, actual meshes, floor isolation/cut plane, history restore and geometry-sensitive RF hashes. Legacy omitted geometry retains its representation/hash.357 scoped backend and25 real PostgreSQL cases; frontend gates below. [Geometry](Geometry.md), [Frontend](GeometryFrontend.md). | Operator geometry is not an independent survey. RF remains a configured center-plane approximation; unknown attenuation/accuracy blocks its use. Physical fidelity requires surveyed coordinates/materials/radios and measurements. Large wall-count/GPU acceptance is separate from device-instancing tests. The requested dimensioned-geometry source gap is closed. |
| **2. Multi-API realtime** | **Implemented and wired in actual `app.main`/settings/readiness.** Leader-only domain work and per-API subscribers, takeover, fencing, bounded dedup, gap resets and current authority. Real sockets and corrected-image two-API deployment failover passed. Permanent poison quarantine and canonical replay fixes are accepted. [DistributedRealtime](DistributedRealtime.md). | Default singleton remains supported; configure every serving replica consistently. Broadcast is bounded/lossy and requires REST reconciliation. Representative load/clock-skew budgets and Redis Cluster key migration remain separate scale work. |
| **3. Cross-owner evidence retention** | **All five owners integrated:** Report, Intent, Alert, Simulation, Autonomy pin before references and expose bounded historical enumeration/reconciliation.0025 supplies receipts/permanent global event tombstones; verified private archive bytes precede actual eligible-row deletion. Scoped restore preserves identities; pin/delete races and replay dedup are guarded. Real PostgreSQL and prior eleven-volume deployment demonstrated nonempty deletion, byte/receipt/pin/tombstone restore. Archive-path review fix is delivered. [RetentionComplete](RetentionComplete.md). | Drain old writers, reconcile/enroll every owner and schedule explicit bounded workspace/window jobs. Unknown/pre-enrollment/backfilled and **ever-pinned** rows remain retained, including released pins. No automatic global scheduler, partition conversion, permanent-evidence GC or PostgreSQL/report disk admission. This is working conservative retention, not merely a pin foundation or permission to delete all history. |
| **4. Fleet collection** | **Implemented and packaged acceptance passed.** Protected manifests, device scheduling/backoff/fenced leases, bounded concurrency, durable spool and stable-ID crash replay. Packaged6/6 verifies two valid SNMP targets, bad-third isolation,12 persisted measurements, dedup, heartbeat staleness, SIGKILL/restart and revocation. Net-SNMP initialization fixed without relaxing stderr rejection. [Fleet](Fleet.md). | Physical firmware/capacity/scale remain external gates. Explicit bindings are not discovery; canonical interface ownership, engine-ID/context and additional protocols remain extensions. Fleet functional evidence is bound to103 unchanged inputs in the final image. |
| **5. Continuous qualified observation/inference** | **Delivered and actual fresh service acceptance passed.** Recoveredv4/rebound unchanged tensors passed a fresh five-policy qualification; six real frames produced four independently reconstructed recommendation-only decisions. Freshness/disconnect/RBAC were tested through real stores and current providers. [ContinuousAI](ContinuousAI.md). | Production deployment still needs an admitted ongoing feed, protected scope/expiry configuration and the exact qualified image; lab instances were cleaned up. New runtime versions require their own qualification. No actuation authority follows from prediction quality. |
| **6. Governed execution/recovery** | **Concrete safety/receiver and installed journal-client composition delivered.**0027 frames/journal/fences, independently bound plans/delay, commit-before-I/O, fresh receiver authority, readback/compensation. API/worker use protected configured safety/journal clients; only separate receiver runs drivers. Confidential signed health receipts gate readiness. OVS/FRR drivers and acquisition/check/register/serve/exact-recover tooling exist. Real PostgreSQL uses fake device boundaries. [AutonomousExecution](AutonomousExecution.md). | **No authentic calibrated installation:** complete causal attribution, enforced arrival/service/error/delay guarantees, independently accepted runtime mappings, aligned model/safety frames and baseline are needed. Frozenv4/currentv5 mismatch remains. No privileged native autonomous dispatch or physical qualification is claimed. |

## 2. Historical ADR023/024 verification checkpoint and review status

These are owning-handoff/parent results, not tests rerun by this documentation task.
Scoped counts overlap and must not be summed into aggregate totals.

| Gate | Recorded result | Boundary |
|---|---:|---|
| Backend full checkpoint | **3,282 passed; 212 skipped** | ADR024 source; full app/tests/scripts Ruff passed. Skips are not passed cases. |
| Frontend / browser | **527 /52 passed** | Typecheck/lint and browser checkpoint; fixture-backed UI tests do not certify physical geometry or deployed persistence. |
| Production bundle | **408.36 /410.16 KiB** | All original bundle gates pass; no budget increase. |
| AI | **463 passed** | Prior unchanged AI suite; do not invent a new full-AI run from backend provider tests. |
| Prior0027 core deployment | **28 passed; 0 failed; 5 blocked** | Recorded frozen-source campaign, not latest corrected-source refresh. |
| Final0027 distributed deployment | **29 passed; 0 failed; 4 blocked** | Final health/key/config fixes, source-matched archive restore and leadership takeover. |
| Deployment regression / installed smoke | **216 /20 passed** | Final image checks include private-key admission and no privileged driver imports. |
| Packaged fleet | **6 passed; 0 failed; 0 blocked** | Transport also1/1; final image reuse verified103 unchanged functional inputs. |

[DeploymentADR023](DeploymentADR023.md) and its
[evidence index](DeploymentEvidence-ADR023-20260920/README.md) retain exact images,
source manifests and failures. Both campaigns exercised nonempty archive deletion,
eleven-volume cold backup/fresh restore, exact archived bytes and receipts/pins/
tombstones, assets/registration/history, reports/workflows and old-token denial.
Deployment telemetry records were explicit fixtures, not measured fleet traffic.
Core blocked distributed failover plus **lab_binding, lab_congestion,
model_diagnostic, restored_telemetry**; distributed passed failover and retained the
other four. `step15_complete=false` remains; the core-only exit1 is not a core failure.

**Independent review:** [ADR023Review](ADR023Review.md) verifies all11 findings
closed, including the FRR final-check race, signing-key confidentiality, stale-health
race and full-config reload. Final review gate335 passed, including62 independent
safe assertions. Source/image pins were refreshed afterward. Aggregate execution
timing and authentic physical bounds remain qualification obligations.

## 3. Independent validation: implemented tools, bounded measured evidence

[IndependentValidation](IndependentValidation.md) delivers preregistered grouped
protocol/import tooling, independent RF error reconstruction, raw queue/drift and
transition verification, and an explicit trusted-installation loader. It checks
external preregistration/attestation/guarantee pins and independently reviewed
executable plans, physical demand/egress mappings and total delay. A provider's own
rehash cannot qualify its plan or widen the reviewed delay.

**Actual unprivileged UDP/application-FIFO acquisition ran eight windows.** A
separate controlled sealed-FIFO continuation also passed8/8 native replays: after
ingress closes, no enqueue operation exists, so its queue cannot increase and its
conditional drift upper bound is zero even during scheduler stalls. This is a
bounded application-runtime result, **not FRR/kernel-queue qualification, a positive
service/deadline guarantee, an accepted receiver installation or physical RF**.
No FIFO fixture/attestation can be substituted for an OVS/FRR executable plan.

Missing evidence is explicit:
- **RF:** authenticated/calibrated receiver identity, raw timestamped dBm survey,
  actual radio/antenna settings and surveyed frame/material/error evidence; externally
  preregistered site/session groups and error limits, independent held-out evaluation.
- **Native network safety:** same-window byte queues/arrivals/departures/drops,
  complete foreground/background/control/link-layer attribution, actual capacities,
  enforced arrival envelopes, justified service/outage and within-window/sensor-error
  bounds, all old→new action transitions and total completion timing. Native counters
  measure behavior; they do not enforce or prove those future guarantees.
- **Trusted admission:** matching runtime/source/image/namespace and model evidence,
  independently accepted mappings/equivalence/guarantees, fresh aligned observations,
  baseline history and protected installation. Current native acquisition tooling
  alone is not a completed controlled FRR transition campaign.

## 4. Historical ADR024 remaining sequence (Current Authority Linked Above)

1. **Release/deployment:** use the final source-matched image pins and configured
   optional profiles. Core/distributed restore and packaged fleet are accepted;
   remote CI and target-environment admission remain separate. Retain failed attempts.
2. **Execution admission:** all11 software review findings are closed. Keep default
   safety/executor unavailable until authentic installation; never install synthetic
   test guarantees. API health and calibration source pins must match the receiver.
3. **Runtime deployment:** use the newly qualified derived artifact and recoveredv4
   image with a fresh admitted instrument feed. This scope has actual recommendation
   acceptance; preserve expiry/provenance and do not substitute defaultv5 or historical
   timestamps. Sustained operational deployment needs operator-provisioned scope.
4. **Causal campaign/receiver:** admit exclusive native namespaces with old
   controllers stopped; establish reviewed traffic enforcement and complete sensors,
   preregister transitions/limits, capture raw evidence and obtain independent pins.
   Provision aligned model/safety frames and baseline, then exercise concrete FRR
   dispatch/readback/STOP/revocation/crash/compensation. Additional control/attribution
   integration is required where the current native instrument cannot account for
   unknown/drop/link-layer traffic; historical averages cannot replace it.
5. **Physical/operational acceptance:** conduct real RF survey and target-device fleet
   validation; schedule conservative retention with protected DB+archive backups;
   test representative distributed connections and real-GPU geometry loads. Time
   partitions, disk admission, broader protocols/vendors and general upgrade/scale
   qualification remain distinct implementation or deployment work.

## 5. Preserved capabilities and wider-vision limits

ADR021/022 delivery remains: transactional inventory outbox; auth/session/gateway
hardening; locked CI/release tooling; protected local asset CAS, persisted registration,
immutable spatial history; signed raw-history keyset cursors; modeled fluid simulation,
RF artifact import; non-actuating agent registry/scheduling/coordination and SQLite
four-tier memory. Base64 remains a compatibility transport/legacy storage format,
not the sole persistence backend. Operator memory is not an LLM/RAG/Neo4j runtime.

Remaining wider implementation includes richer RF/interference/capacity physics,
automated evidence-linked scenario assembly where not supplied by operators,
predictive/drift/promotion workflows, richer agent planning/retrieval and vendor
execution coverage. Strict resource CSP/token-transport migration, portable historical
CI evidence, general storage GC/admission and representative enterprise performance
are not implied by these six increments. **SSO remains optional, outside the original
request.** Local source delivery, measured emulation, authentic physical qualification
and production activation must continue to be reported separately.
