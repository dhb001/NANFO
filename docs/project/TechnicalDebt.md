# Technical Debt

## ADR-028 changes to this register — 24 September 2026

[ADR-028](../adr/ADR-028-full-stack-review-remediation.md) paid down or changed several
rows below; each row now says what remains. New debt from ADR-028:

| Debt | Rationale / risk and next bounded work | Owner / target |
|---|---|---|
| Strict TypeScript index access | `noUncheckedIndexedAccess` is off (about 388 findings). See [KnownIssues](KnownIssues.md). | Frontend owners |
| Legacy WebSocket `?token=` path | Kept for one compatibility release (C1). Remove it, and its log redaction special case, once no client uses it. | Platform / frontend owners; next release |
| Unused `Settings.REPORTS_ARTIFACT_BUCKET` | Kept on purpose (ADR-028 §7.1), because `backend/.env` forbids unknown keys. Remove it only together with a documented `.env` migration step. | Backend owners |
| Telemetry table partitioning | Not done: partitioning would force the partition column into the unique `event_id` constraint and the `record_id` key that evidence pins reference, breaking global de-duplication and the pin foreign key. Needs its own design. | Telemetry / data owners |
| Batch owner lookups | Alert list rechecks and C26 report admission still list networks or workspaces per distinct workspace or organisation, because the owners expose no batch "network → workspace" or "all workspaces of an org" read. | Network / Organization owners |
| Host-only tools in the backend image | Five tools import excluded modules (see KnownIssues); move them out of the image context. | Deployment owners |

## Active Debt — 21 September 2026 (annotated for ADR-028)

Current delivery/acceptance authority: [ReviewClosure-Completion](ReviewClosure-Completion.md).
Unresolved exposure and qualification blockers are tracked in [KnownIssues](KnownIssues.md).

| Debt | Rationale / risk and next bounded work | Owner / target |
|---|---|---|
| Frozen/unpatched dependencies | Exact exceptions are not remediations. ADR-028 replaced the unpatched JWT path (PyJWT; python-jose/ecdsa removed) and built a hash-pinned successor lab image (os-ken instead of Ryu). Still open: requalify the successors, audit exact CPU/image/OS inventories, and retire the frozen exceptions without rebinding historical identities. | Security/runtime owners; exceptions expire **2026-10-29 … 2026-11-26** (ai coverage gap 2026-12-03); [policy handoff](ReviewClosure-Dependencies.md) |
| Retention scheduling/capacity | Cross-owner pins/archive/delete/restore work. ADR-028 made domain-stream retention a supervised deployment loop, added bounded outbox/observation retention and unreferenced-asset GC. Unknown/pre-enrollment/ever-pinned records remain; pending/archive growth still needs operations. Partitions, permanent evidence lifecycle and disk admission need separate design. | Data/operations owners; before sustained deployment |
| Asset compatibility transport | ADR-028 C4 made metadata pages the default and bounded `include_data=true` (`page_size<=10`, 32 MiB per page). Uploads return metadata only, and downloads support 304. The inline listing remains only as an explicit, bounded opt-in; remove it after the remaining consumers migrate. Preserve referenced identities and bytes. | Network/frontend owners; separate contract change |
| Operational observability | Request metadata/log context, route recovery and retention health diagnostics are delivered. ADR-028 added telemetry SLO evaluation, readiness marker counts and a process watchdog. Sustained dashboards, service objectives, alert routing, capacity response and representative soak evidence remain. | Operations; separately scoped acceptance |
| Performance/scale | ADR-028 raised the total bundle cap from 420,000 B to **450,000 B** (**422.34 KiB** measured), pending owner confirmation; per-chunk caps are unchanged. Twin rendering now uses on-demand frames and instancing. Representative real-GPU geometry/model and distributed connection loads, clock-skew budgets and Redis Cluster key migration still need separate sizing and acceptance. Bundle size alone is not runtime performance. | Frontend/platform owners; target-environment qualification |
| Portable versus private CI evidence | Clean upgraded PG254pass/12skip plus real-Redis12pass covers all266 selected cases after development-only fakeredis Lua/lupa declaration and clean-CI EVAL checks. nginx header/proxy24pass/0skip closes its fixture issue. ADR-028 added the `private_artifacts` marker/registry (backend 37 entries, ai-engine 2 modules), tracked copies of the qualified checkpoint and frozen lab archive, a skip budget and a zero-skip portable lane (722 cases). Remote execution and required checks remain unverified. | CI/repository owners; integration follow-up |
| Evidence/release identity | Latest c8rorfzd accepted28pass/0fail/5blocked at backend `a2bf67af…`/source `f7105617…`; new public refresh/retention receipts and private local backup/key/result retention ready. ADR-028 changes core source and schema (0030); no new image, deployment or release identity is claimed for it. Off-host escrow remains open. | Deployment/evidence owners; explicit release boundaries |
| Experimental operational-domain exhaustion |017 remains failed despite67/68 matrix outcomes and all20 fault outcomes completed. Independent018 accepted protected-read repair and reconfirmed failure; active count1342 scanner defect corrected with60 passing tests.996/1000 true/preregistered reservations,4 available/36 required,deficit32. Preserve genuine reservations and train/validation/test split; explicit reviewed protocol direction is needed before a new plan. | Experimental/research owners; blocked, no completion claim |
| Module size and documentation governance | ADR-028 split telemetry `service.py`, the Twin page and backend `main.py` along ownership boundaries with behaviour-preserving regressions, and added `CONTRIBUTING.md`, `SECURITY.md` and `CODEOWNERS`. Licensing and evidence-access decisions remain open (owner). Reconcile older architecture rules with later ADR scope explicitly. | Respective owners/student; licence is an ADR-028 §8 owner action |

Dimensions, fleet/spool and bounded qualifiedv4 recommendations are delivered.
Final portable441 JUnit cases passed with zero skips and11 explicit deselections;
original AI463 passed reaffirmed. These local results do not close remote CI obligations.
Physical RF, intended-user study, repeated training and causal/autonomous qualification
are **evidence obligations**, not debt that can be cleared by refactoring. Broader
AIOS/vendor/physics/plugin features remain outside this documentation consolidation.

## Usage
Track debt with rationale, risk, payoff, and target milestone.
