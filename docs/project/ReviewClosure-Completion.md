# ADR027 repository-review closure — master matrix

**Status date: 21 September 2026.** This is the current seven-workstream register
for [RepositoryReview-2026-09-21](RepositoryReview-2026-09-21.md), under
[ADR027](../adr/ADR-027-repository-review-closure.md). Software delivery, executed
acceptance and research/physical qualification are separate states. The seven rows
follow the review's recommended order; R01–R12 are finding IDs, not seven new features.

> **Update 2026-09-24:** [ADR-028](../adr/ADR-028-full-stack-review-remediation.md)
> changed the current source after this matrix: schema **0030**, contract changes C1–C26
> and new CI/deployment tooling. The ADR-028 status and owner actions are at the top of
> [CurrentSprint](CurrentSprint.md). This matrix still records the accepted `c8rorfzd`
> release (schema 0029) and the open evidence obligations. No ADR-028 image or
> deployment has been accepted.

## Source and evidence scope

- Base commit: `3f9f1f1fd247cd1af6d66cf38d94155ee32a91e1`, plus the uncommitted
  ADR027 integration worktree. The base commit alone does **not** identify the
  accepted release. Exact frozen manifests, locks and images are in the
  [deployment handoff](ReviewClosure-Deployment.md); full-stack source/build
  identities are in the [full-stack handoff](ReviewClosure-Fullstack.md).
- Current schema: **0029**. Accepted core images: backend/six workers
   `sha256:a2bf67af00b76980beec822f9c7f1fcb0e6d4ef2e1e6461b169b9b3ff3397b39`,
  frontend `sha256:2e6f019d5807e7a4f97cd2d82d9a62c4349a68e5c2b2ed0493a8eb206119657d`.
  The deployment handoff records all store images and exact source parity limits.
- **Latest core refresh `c8rorfzd` ACCEPTED:28 passed/0 failed/5 blocked.** Accepted
  runtime source aggregate:
  `f7105617ee9cad1ae51e2f223761885c9223ee22d4d586a08ff36a5f87e89d05`.
  Subsequently only the experimental verifier seed scanner and its test changed
  among source code; current verifier hash is
  `9e46d086343fffa3c0cfe95fb6c636172d03be5bd175ff030fedb7b5ec0c87c0`.
  Core serving behavior is unchanged, but **the current tree is not byte-identical
  to the accepted image**. The deployment handoff records this host-tooling drift.
  [Refresh](ReviewClosureEvidence/refresh-c8rorfzd/) and
  [retention](ReviewClosureEvidence/retention-c8rorfzd/) bundles preserve credential-free
  evidence; new backup/key/original result are separately preserved privately locally.
  Browser evidence remains tied to its own run, not rerun by core refresh.
- Results below are current owner handoffs and the parent's supplied latest
  integrated observations, not suites rerun by this documentation task. Counts
  overlap and must not be added together. Skips and blocked cases remain explicit.
- Earlier failed attempts remain in their handoffs. Later accepted runs supersede
  their blocker status, not their recorded outcomes. Old schema0027/0028 releases,
  ADR023/024 checkpoints and completed VS checklists are historical evidence.

## Seven-item master matrix

| Item / review findings | Delivered and executed evidence | Honest status and remaining closure |
|---|---|---|
| **1. Evidence/credential containment — R01** | **71 receiver credentials** privately preserved with exact-byte verification and removed from the active working tree. Allowlisted export, nested/extensionless scanning and exact-hash fixture policy delivered; local whole-tree gate passed. [Evidence](ReviewClosure-Evidence.md). | **Containment delivered; exposure remediation OPEN.** Deletions are pending Git changes; index/history still expose originals. Confirm non-reuse/invalidation of surviving authority, investigate copies/access, and obtain explicit authorization for coordinated history remediation. Remote required-check configuration remains pending. |
| **2. User-visible integration and safe setup — R02, R03, R05, R06; scoped R10/R12** | Actual binary headers/ETag, size/hash verification, request identity before mutations, safe validation metadata/log context, route recovery boundary, generated private development credentials, loopback stores and exact gateway trust implemented. Identity follow-up **164 passed in each original/upgraded environment**; setup scope **226 passed**. Repaired nginx include fixture and proxy gate **24 passed/0 skipped**. Actual asset reload/restore also passed item 3. [Assets](ReviewClosure-Assets.md), [Identity](ReviewClosure-Identity.md), [Setup](ReviewClosure-Setup.md). | **Scoped repairs delivered and locally verified.** Request IDs retain refresh replay protection. Route recovery is functional software evidence; sustained operational dashboards/SLOs and general onboarding/administration improvements are not established by these checks. |
| **3. Production full-stack regression, portable CI and dependencies — R07, R09** | **5/5 actual production-build browser cases**, real authenticated HTTP/stores/workers, zero failures/skips/retries; source digest stable and owned resources cleaned. Portable CI gates delivered. Clean upgraded PostgreSQL **254 passed/12 skipped**, then the exact real-Redis subset **12 passed/0 skipped**: all **266 selected** cases covered. Declared development-only `fakeredis[aioredis,lua]`/lupa2.8 and sync/async EVAL clean-CI checks repair the missing dependency. npm full/production audits **0 advisories**. [Fullstack](ReviewClosure-Fullstack.md), [Dependencies](ReviewClosure-Dependencies.md). | **Local acceptance passed; security/CI closure PARTIAL.** PG-only receipt remains partial; the separate Redis12 result is handoff-reported, not a standalone receipt in the durable bundle. Remote workflow runs and branch protection are not evidenced. Exact exceptions in `security/dependency-exceptions.v1.json` expire **2026-10-21**: ecdsa0.19.2, upstream Torch2.8.0 advisories, exact CPU-wheel coverage gap and frozen emulation pins. Exceptions are not fixes. Successor images/runtimes require fresh audits and qualification; image/OS SBOM and private historical-artifact CI remain open. |
| **4. Bounded operating resource growth — R04, R08** | Metadata-only asset pages omit bodies; selected binary fetch remains authenticated and verified. Operator-only domain-stream archive-before-delete checks all approved group/pending boundaries; **27 real-Redis tests passed with zero skips**. [Assets](ReviewClosure-Assets.md), [Streams](ReviewClosure-Streams.md), [CI follow-up](ReviewClosure-Dependencies.md). | **Bounded mechanisms delivered; operational adoption PARTIAL.** Stream deletion is off by default. Operators must audit group history, provision private persistent archives/backups, schedule bounded jobs and monitor capacity. Pending/unread/DLQ history and archives can still grow; no automatic producer throttling, total disk quota or representative production soak is claimed. Legacy full-body asset mode remains compatible. |
| **5. Schema0029 deployment and recovery** | Latest frozen core refresh **c8rorfzd accepted28 passed/0 failed/5 blocked**, including fresh0029 install, cold encrypted **11-volume** backup and distinct fresh restore; **253 deployment tests** plus37 subtests passed. All six workers, restored reports/assets/history/archive bytes and old-session denial exercised. New backup/key/result privately preserved; public refresh/retention receipts ready. [Deployment](ReviewClosure-Deployment.md), [durable bundle](ReviewClosureEvidence/README.md). | **Core ACCEPTED at exact refreshed identities; wider qualification OPEN.** Later verifier scanner/test drift changes host tooling, not core serving behavior; no whole-tree byte-parity claim. Distributed failover, lab binding/congestion, frozen-model diagnosis and measured-telemetry survival remain blocked; `all_green=false`, `step15_complete=false`. Explicit0027/0028 upgrade rehearsal, off-host escrow and whole-host/representative-load acceptance remain open. |
| **6. Experimental017 outcome,018 repair and research obligations** | Actual017 used unchanged frozen016 source/original model: **4/4 smokes;67/68 matrix outcomes completed,1 invalid measurement** (`path1-1564-qualified`, `protected_regular_owner_file_required`); **all20 fault outcomes completed**. Independent018 review accepted the bounded protected-read repair and reconfirmed017 failure. Frozen gates115backend/3historical skips,34receiver,2STOP passed. Reviewer identified false reservation from `reserved_seed_count:1342`; active typed/provenance extractor corrected with **60 tests passed**. [Experimental](ReviewClosure-Experimental.md), [independent review](ReviewClosureEvidence/experimental017-018/018-independent-review.json), [Research](ReviewClosure-Research.md). | **017 FAILED; repair review ACCEPTED; fresh full campaign BLOCKED.** Corrected **996/1000 genuine/preregistered train-operational values reserved,4 available/36 required,deficit32**. No018 plan/admission/launch or experiment completion. Exact historical live interleaving remains unproven. Preserve genuine reservations and train/validation/test split; further protocol direction requires explicit review/authorization. Physical RF, intended-user study, independent repeated training, proactive timing, safeguards ablation and complete recovery remain evidence obligations. |
| **7. Documentation consolidation and scoped maintainability — R11, remaining R12** | Current entry points/schema/test evidence consolidated here; sprint/journal/decision tops, issue/debt registers, AI status and Fleet role wording aligned. Onboarding preserves generated env and points to six-worker/private-storage supervision. Old authority checklists explicitly archived. | **R11 documentation scope DELIVERED.** Large-module refactoring, licensing/access/contribution decisions and wider architecture-rule reconciliation remain deferred owner work. No broader AIOS/vendor/physics/plugin expansion is authorized by this consolidation. |

## Latest integrated verification checkpoint

| Gate | Actual reported result | Evidence boundary |
|---|---|---|
| Full backend | **3,949 passed; 317 skipped** | Final parent-observed run after scanner correction; opt-in skips are not passes. |
| Final portable suite | **441 JUnit cases, zero skips;11 explicit deselections** | Parent-observed final portable run; excluded cases are not passes or remote CI evidence. |
| Original AI environment | **463 passed, reaffirmed** | Parent-observed original AI suite; no new training or qualification. |
| Clean upgraded PostgreSQL / real Redis subset | **254 passed/12 skipped**, then **12 passed/0 skipped** | All266 selected cases executed across two runs after development Lua dependency repair; PG-only receipt remains partial. |
| nginx headers / proxy boundary | **24 passed, zero skips** | Repaired private upstream include; actual nginx/Uvicorn and two-client/spoof checks. |
| Frontend unit/component | **615 passed /98 files** | Latest parent-observed integrated run. |
| Frontend lint/types/build/performance | **Passed; 394.28 KiB gzip /410.16 KiB cap** | Latest parent observation; unchanged bundle budget, not a real-GPU/load qualification. |
| Default browser suite | **70/70 passed, zero retries** | Final assets-owner upgraded-lock run; fixture-backed development browser lane. |
| Production full-stack browser | **5/5 passed, zero skips/retries** | Actual stores/workers/HTTP and minified assets; final `r09-live-08.json` receipt in full-stack handoff. |
| Core0029 deployment/restore | **28 passed /0 failed /5 blocked** | Latest accepted `nanfo-deploy-verify-c8rorfzd`; exact refreshed images/source above, later scanner/test drift explicit. |
| Deployment regressions | **253 passed**, plus37 subtests | Reported separately from live matrix cases. |
| Real Redis retention | **27 passed, zero skips** | Required-lane local execution in dependency follow-up; broader63-case retention/recovery gate overlaps. |
| Dependency audit | **npm0; Python lanes passed reviewed policy** | Backend1 package/advisory pair, upstream Torch8 pairs, emulation26 pairs; exact CPU coverage incomplete. These are not distinct-CVE totals or fixed vulnerabilities. |
| Experimental017 | **4/4 smokes;67 completed/1 invalid of68 matrix;20/20 fault outcomes completed** | Overall failed; independent018 review reconfirmed failure. Completion includes rejection/restoration, not candidate improvement. |
| Frozen018 offline gates | **115 backend passed/3 historical skips;34 receiver;2 STOP passed** | Fresh plan blocked by permitted operational-domain exhaustion; no live acceptance. |
| Independent018 review / active scanner correction | **Repair accepted;60 scanner/campaign tests passed** | Review SHA256 `61ae01ccca57b5607566791ebd8dc811c25b84af57b0dbdcc7530c493087cd80`; corrected996 reservations leave deficit32, no launch authority. |

## Remaining-work authority

The current remaining checklist is at the top of [CurrentSprint](CurrentSprint.md),
with this matrix defining scope and the ten linked `ReviewClosure-*` owner handoffs
defining evidence. Older “Post-VS8”, “Post-VS16” and fully checked VS master lists
are archived slice records, not present production or scientific acceptance.

Credential-free accepted manifests/results are now retained in
[ReviewClosureEvidence](ReviewClosureEvidence/README.md); encrypted backup and key
have separate private local durable copies. This is not off-host escrow or a
self-contained disaster-recovery kit. Latest refresh and subsequent host-tooling
drift have distinct identities; update item6 only from actual evidence and independent
review. The single working academic ODT/PDF is unchanged by this consolidation.
