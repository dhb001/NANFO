# ADR-022: Spatial Assets, History and Data Lifecycle

- Status: Accepted direction under the user's comprehensive P0–P3 implementation request
- Date: 2026-09-20

## Scope and ownership

Continue ADR021 in isolated local infrastructure. Source completion and external
physical qualification remain separate. No automatic production activation.

Network owns spatial revision bodies, persisted asset registration and protected
binary storage. Migration0022 after0021 adds immutable spatial history and explicit
model registration; migration0023 after0022 moves new asset bodies to a protected
content-addressed local object store while retaining legacy inline compatibility.
Retain current GET/PUT scene version1 semantics; introduce optional shape metadata
only with a documented backwards-compatible schema and source provenance.

Approve current-membership scoped GET `/api/v1/networks/{network_id}/spatial-scene/history`
and GET `/api/v1/networks/{network_id}/spatial-scene/history/{revision}`.
Restoring a historical scene uses the existing PUT with current expected revision,
creating a new version, never decrementing/rewriting history. Registration is
persisted with the existing campus model asset request/response through a nullable
versioned field recording translation, radians rotation, positive scale, meter/Y-up
target and source provenance. Do not silently register legacy assets.

Approve an authorized binary GET on the existing campus model asset identity at
`/api/v1/networks/{network_id}/campus-model-assets/{asset_id}/download` (canonical
envelope on errors). Existing uploads may retain bounded base64 transport for
compatibility, but new persisted bytes go into protected object storage with hash,
size and safe atomic publication. Downloads verify content and scope. Local storage
is a concrete protected object-store backend, not a claim that S3 is installed.
Legacy content migration is an explicit bounded operator command; preserve rollback
and backup requirements. Document exact existing route names before extension.

Telemetry owns migration0024 after0023 for durable evidence pin records and keyset
indexes. Extend the existing history API with optional opaque scoped cursor mode,
preserving existing page behavior. Pin issuance/release are owner-service contracts,
not public APIs; default retention remains fail-closed for data whose cross-owner
reference coverage is unknown. Explicitly version reference coverage and keep
report, intent, alert, simulation and autonomy evidence. Do not pretend an empty pin
table proves historical data unreferenced. Partition conversion is a separate
operator migration decision based on actual existing retention/unique-key semantics.

## Agent execution

The AI runtime may add typed, permission-scoped registry/scheduling, persistent
evidence memory and deterministic consensus for non-actuating operator/shadow
analysis. It cannot install qualified inference, calibrated safety or execution
providers from declarations alone. No live training or physical command is added.

## Validation and integration

Separate agents own history/registration0022, asset storage0023, telemetry0024,
frontend integration and AI runtime. Shared main/config/deploy composition remains
parent-owned unless delegated. Exact wire contracts are documented before router
changes. Test rollback, revision races, tamper/traversal, tenant denial, legacy
compatibility, scoped cursor replay and reference-conservative retention. Fresh
deployment/restore claims must be refreshed for the final schema and storage volume.
