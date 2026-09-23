# ADR-027: Coordinated repository-review closure

- Date: 2026-09-21
- Status: Accepted implementation direction under the user's explicit instruction
  to implement all seven recommended repair/acceptance workstreams together.
- Input: `docs/project/RepositoryReview-2026-09-21.md`.

## Scope and ownership

Repair evidence hygiene, existing cross-layer workflows, dependency/CI gates,
bounded operational resource growth and current0029 acceptance. Preserve module
ownership, historical experiment bytes/results and frozen model identities. No
shared database/container changes, Git history rewriting, model retuning, invented
participant/RF evidence or new production actuation authority follows from this ADR.
Parallel owners use disjoint files; final integration freezes source before any
deployment or newly admitted serialized experimental campaign.

## Contracts

1. Existing binary asset downloads retain `application/octet-stream` and quoted
   `sha256:<digest>` ETags. Client verifies exact size and SHA-256 and uses stored
   MIME only for validated local model interpretation.
2. Request IDs are bounded opaque correlation identifiers; generate a UUID when
   absent, preserve valid supplied opaque IDs, deterministically map to UUID-backed
   storage with original identity retained. Resolve before side effects. Success,
   errors and logs share request identity and timestamps. No token replay relaxation.
3. Asset GET `/api/v1/networks/{network_id}/campus/model-assets` gains an additive
   explicit metadata-only paginated mode: `include_data=false&page=1&page_size=20`,
   page_size1..100. Metadata mode returns the same envelope and `{items,total,page,
   page_size}` with model_data_base64 omitted; legacy default remains compatible.
   Scope precedes pagination, stable creation-time/UUID ordering. Existing explicit
   binary endpoint supplies bytes. Frontend migrates to paged metadata; nullable/
   optional compatibility bytes are consumed only when present. No schema change.
4. Domain-stream retention is an internal operator policy, not a new public API.
   Archive verified exact entries before deleting only entries already durably
   acknowledged by every relevant group, below pending/delivery boundaries.
   Unknown groups/state or archival failure blocks deletion. Bounded batches,
   explicit age/capacity configuration and diagnostics, no eviction/lossy MAXLEN on
   durable domain streams. Keep fanout's existing distinct lossy semantics.
5. Development stores bind loopback and require generated/configured credentials;
   production validates unsafe placeholders. Proxy trust is explicitly limited to
   the private gateway boundary, with overwritten forwarding headers and tests.
6. Evidence publication uses an explicit credential-free allowlist. Preserve raw
   artifacts privately and record relocation/checksums without printing credentials.
   Remove exposed receiver tokens from the active tracked tree only after verified
   preservation. Document historical exposure; do not rewrite Git history implicitly.

## Validation and qualification

Actual production-build browser tests must consume actual ephemeral authenticated
HTTP/store/worker responses for critical workflows, including upload/reload/restore.
CI includes dependency auditing with explicit reviewed reachability exceptions for
unpatched/frozen historical runtimes; do not claim that ignoring an advisory fixes it.
Current0029 requires source-matched deployment and backup/fresh restore evidence.
Experimental014 failures require retained-frame diagnosis and regressions before
fresh immutable-plan acquisition. Historical outcomes/thresholds remain unchanged.
Physical measurement and participant-study obligations remain explicit external
inputs. Status tracking distinguishes delivered code, executed acceptance and
scientific/physical qualification.

## Risks

Cross-group stream trim races must fail closed; partial archives must never authorize
deletion. Metadata compatibility must not create an unbounded implicit body fetch.
Dependency upgrades cannot silently rebind frozen checkpoints or qualify new images.
Full-stack tests use only exact-owned disposable resources and teardown even on
failure. Global tracking and final integration are owned by the coordinating agent.
