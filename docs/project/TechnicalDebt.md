# Technical Debt

## Active Debt — 21 September 2026

Current delivery/acceptance authority: [ReviewClosure-Completion](ReviewClosure-Completion.md).
Unresolved exposure and qualification blockers are tracked in [KnownIssues](KnownIssues.md).

| Debt | Rationale / risk and next bounded work | Owner / target |
|---|---|---|
| Frozen/unpatched dependencies | Exact exceptions are not remediations. Replace unpatched JWT dependency path in a tested change; build separately versioned AI/emulation successors, audit exact CPU/image/OS inventories and requalify without rebinding historical identities. | Security/runtime owners; exception expiry **2026-10-21**; [policy handoff](ReviewClosure-Dependencies.md) |
| Retention scheduling/capacity | Cross-owner pins/archive/delete/restore and operator-only domain-stream retention work. Unknown/pre-enrollment/ever-pinned records remain; pending/DLQ/archive growth still needs operations. Global scheduling, partitions, permanent evidence lifecycle, disk admission and reviewed CAS/history/outbox GC need separate design. | Data/operations owners; before sustained deployment |
| Asset compatibility transport | Frontend now uses bounded metadata pages and fetches only selected binary bytes. Legacy default full-body/base64 listing remains for compatibility and is still unbounded; inventory/migrate remaining consumers before any approved removal. Preserve referenced identities and bytes. | Network/frontend owners; separate contract change |
| Operational observability | Request metadata/log context, route recovery and retention health diagnostics are delivered. Sustained dashboards, service objectives, alert routing, capacity response and representative soak evidence remain. | Operations; separately scoped acceptance |
| Performance/scale | Current parent bundle **394.28/410.16 KiB gzip** passes unchanged gates. Representative real-GPU geometry/model and distributed connection loads, clock-skew budgets and Redis Cluster key migration need separate sizing/acceptance. Bundle size alone is not runtime performance. | Frontend/platform owners; target-environment qualification |
| Portable versus private CI evidence | Clean upgraded PG254pass/12skip plus real-Redis12pass covers all266 selected cases after development-only fakeredis Lua/lupa declaration and clean-CI EVAL checks. nginx header/proxy24pass/0skip closes its fixture issue. Broader portable/full-stack gates exist; exact historical artifacts still need a private checksum-verified lane/original interpreters. Remote execution and required checks remain unverified. | CI/repository owners; integration follow-up |
| Evidence/release identity | Latest c8rorfzd accepted28pass/0fail/5blocked at backend `a2bf67af…`/source `f7105617…`; new public refresh/retention receipts and private local backup/key/result retention ready. Subsequent source drift is only verifier scanner/test (`9e46d086…` verifier), not core behavior; no entire-tree parity claim. Off-host escrow remains open. | Deployment/evidence owners; explicit release boundaries |
| Experimental operational-domain exhaustion |017 remains failed despite67/68 matrix outcomes and all20 fault outcomes completed. Independent018 accepted protected-read repair and reconfirmed failure; active count1342 scanner defect corrected with60 passing tests.996/1000 true/preregistered reservations,4 available/36 required,deficit32. Preserve genuine reservations and train/validation/test split; explicit reviewed protocol direction is needed before a new plan. | Experimental/research owners; blocked, no completion claim |
| Module size and documentation governance | Split large telemetry/Twin/deployment/experimental modules only along existing ownership boundaries with behavior-preserving regressions. Reconcile older architecture rules with accepted later ADR scope explicitly. Licensing, contribution/security-reporting policy and evidence access decisions remain open. | Respective owners/student; deferred, separately authorized |

Dimensions, fleet/spool and bounded qualifiedv4 recommendations are delivered.
Final portable441 JUnit cases passed with zero skips and11 explicit deselections;
original AI463 passed reaffirmed. These local results do not close remote CI obligations.
Physical RF, intended-user study, repeated training and causal/autonomous qualification
are **evidence obligations**, not debt that can be cleared by refactoring. Broader
AIOS/vendor/physics/plugin features remain outside this documentation consolidation.

## Usage
Track debt with rationale, risk, payoff, and target milestone.
