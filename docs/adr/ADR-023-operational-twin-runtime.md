# ADR-023: Operational Twin Runtime

- Status: Accepted implementation direction under the user's explicit remaining-six-workstreams request
- Date: 2026-09-20

## Scope

Implement dimensioned canonical geometry, multi-API realtime, cross-owner evidence
retention, fleet collection, continuous qualified observation/inference and governed
execution/recovery. The user retains the isolated-local-lab environment selected for
ADR021/022. Local emulation measurements are not independent physical RF surveys or
production-network safety qualification. Record missing external inputs; never
manufacture measurements, qualification or provider readiness.

## Module and contract decisions

### Geometry

Network owns an additive optional `geometry` property on existing version1 spatial
objects, with exact shape-specific schemas documented in SpatialScene.md before
implementation. Local meter/Y-up coordinates and existing transform order remain.
Support explicit bounded boxes/prisms for building/room/rack, slabs for floors and
wall surfaces with physical thickness/material metadata. No inferred dimensions.
Old geometry-free revision bodies retain their exact stored representation/hash;
normalization must not silently invalidate historical or RF artifacts. Existing
GET/PUT/history routes suffice. No relational migration required for JSONB shapes.
Simulation consumes owning geometry/transform contracts; frontend draws only explicit
geometry and preserves permissions, revision conflicts and provenance.

### Distributed realtime

Retain durable Redis Streams domain processing and idempotent owning effects. Add
bounded internal fanout to all API processes; do not use the shared consumer group
as broadcast. Each API owns only its socket registry and current delivery authority.
Separate collector/domain-consumer leadership from serving sockets. Per-process
readiness verifies subscription and freshness; reconnect/loss signals existing
WS_BACKPRESSURE and forces scoped REST reconciliation. Document the internal versioned
transport, payload bounds, replay/dedup, restart and failure semantics. Relax the
single-serving-API restriction only in explicitly configured distributed mode whose
leader/fanout/authorization behavior is tested. No new public socket contract.

### Retention and fleet

Telemetry owns archive receipts/global event tombstones and durable fleet work/spool.
Reserve migration0025 after0024 for retention and0026 after0025 for fleet. Pins are
issued through Telemetry public contracts inside owner transactions before durable
references. Integrate Report, Intent, Alert, Simulation and Autonomy without SQL joins
across ownership. Owner services expose bounded reference reconciliation. Unknown
historical coverage stays retained. Archive-before-delete with verified bytes,
concurrent pin exclusion and event-dedup preservation is mandatory. Operator CLI
dry-run/apply/restore and configured bounded worker are approved; no public retention
or collector credential endpoint. Fleet bindings remain operator-provisioned protected
files, each device has fresh authority, bounded scheduling, leases and durable spool.
No duplicated collectors on multiple API processes.

### Continuous AI and governed execution

Autonomy owns concrete configurable providers implementing existing interfaces;
reserve migration0027 after0026 for additional durable provider/execution state if
needed. Use existing status/mode/decision APIs, not new inference routes. Model
installation binds actual qualified artifact hashes, feature/observation contract,
scope, runtime and freshness. Historical checkpoint compatibility cannot be asserted
by translating missing features into zeros. Separate continuous shadow recommendation
from actuation availability. Reuse the existing independent AI runtime and confinement.

Execution uses a separately versioned isolated lab receiver authorization contract,
not manual_approval impersonation. Validate server-owned action/certificate/calibration,
actor/revision/STOP, deadlines and exclusive resource ownership immediately before
dispatch. Persist accepted work before I/O; uncertain outcomes keep exclusion;
verification and compensating recovery survive requester revocation/restart. Keep
production drivers unavailable unless real installed capabilities qualify. New internal
lab wire schemas must be documented before producer/receiver changes; preserve old
manual-lab contract and frozen historical experiment compatibility.

### Independent validation

Simulation/Autonomy tooling imports authenticated or operator-attested raw measurements
with immutable preregistered train/holdout protocol and scope. Evaluate RF error and
network safety inequalities independently of fit code; distinguish statistical
coverage from guaranteed bounds. Only explicit trusted installation with all required
evidence may enable calibrated providers. Implement reproducible acquisition/evaluation
campaigns for the local lab. Real RF survey/hardware certification remains blocked
when no physical sensor/device evidence is supplied.

## Integration and acceptance

Agents own disjoint modules and per-workstream handoffs. Parent owns main/config/
shared deployment composition unless delegated. Shared migration sequence is fixed.
Preserve prior work/evidence; no commits, no shared-container mutation or training
without explicit scoped campaign admission. Use separate disposable infrastructure;
serialize privileged emulation campaigns. Verify current tests, PostgreSQL races,
multi-process sockets, fleet crash replay, pinned archive/restore and receiver-side
revocation/expiry/STOP/recovery. Finish with source-matched deployment acceptance
for the final schema; tests alone do not certify independent physical fidelity.
