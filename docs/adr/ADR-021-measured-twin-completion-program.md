# ADR-021: Measured Twin Completion Program

- Status: Accepted implementation direction under the user's explicit P0–P3 request; external acceptance remains evidence-gated
- Date: 2026-09-19

## Authorization and environment

The user requested concurrent implementation of the repository review recommendations
and selected an isolated local lab. This authorizes source implementation and disposable
local verification, not mutation of existing deployments, physical devices, historical
training evidence or production activation. Preserve earlier measured results.

## Architecture and delivery contracts

Retain the modular monolith and owning-service boundaries. Deliver independently
testable capabilities in parallel, then integrate and run serialized lab acceptance.
New research functionality remains modeled/shadow until independently calibrated.
Never equate unit tests, deterministic models or policy probability with physical safety.

1. Network owns transactional inventory outbox, migration **0020** after0019.
   Preserve existing event names/envelopes with stable replay IDs and timestamps.
   A bounded independent publisher worker is approved, following existing worker patterns.
2. Network owns canonical spatial objects and placement, migration **0021** after0020.
   Approve scoped GET and PUT `/api/v1/networks/{network_id}/spatial-scene` with the
   canonical envelope, current membership/read:topology or write:config respectively.
   PUT is an atomic versioned scene replacement requiring an expected revision;
   reject cross-network references, invalid hierarchy, cycles and nonfinite transforms.
   Scene version1 contains meter-based coordinate metadata, stable object IDs,
   parent/type/name, position/rotation, optional device association and explicit provenance.
   Asset registration uses explicit transforms; generated schematic positions remain
   labeled fallback. Document exact wire schemas before implementing the router.
3. Realtime maintains current authorization and single-API fencing. Bound slow-client
   delivery; preserve channel contracts. Frontend latest metric state must be fair
   across resources and separate from event history. Multi-process fanout requires
   separate acceptance, not merely removing the lease.
4. Telemetry gains a genuinely read-only adapter with validated configured identities,
   protected credentials, units, counter/reset semantics and explicit measured provenance.
   Existing demo adapters remain distinct. Initially use an operator CLI/configuration
   boundary; no new public telemetry endpoint is authorized by this ADR.
5. Simulation owns pure versioned RF propagation, snapshot scenario construction and
   calibration evaluation utilities. Document units, coordinate alignment, uncertainty,
   workload comparability and limits. Expose initially via operator tooling and owning
   services; no invented websocket or simulation wire fields. No physical fidelity claim
   without held-out measurements. Keep existing evaluator outputs compatible.
6. AI shadow evaluation remains non-actuating with frozen model/source contracts,
   baseline comparisons, typed evidence and explicit unavailable providers. Do not
   install fake calibration/executors. Agent recommendations must include sources,
   assumptions and alternatives. No new inference REST route is authorized here.
7. Release work adds CI and reproducible verification; security work may improve existing
   login/rate-limit and gateway controls without changing the token transport contract.
   Cookie refresh and websocket tickets require their own migration design.

## Ownership and integration

Each parallel workstream owns its listed files and a separate handoff document under
`docs/project/CompletionProgram/`. Parent integration owns main/router composition,
dependency locks, shared deployment composition and current status/journal summaries.
Agents must not edit historical artifacts, create commits, launch training, or operate
shared Docker resources. Any missing library/infrastructure is reported explicitly.

## Acceptance

Run scoped tests first, then backend/frontend/AI and deployment checks. Disposable
database migration, interrupted publication, spatial revision conflicts, measured
adapter failures, slow websocket clients, model resource cleanup and calibration
holdout are explicit checks. Preserve failures and blocked cases. Keep an actionable
capability matrix; program completion requires integrated evidence, not parallel
agent completion messages.
