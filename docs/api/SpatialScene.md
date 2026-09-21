# Canonical spatial scene API (ADR-021/022/023)

Network owns this contract and its PostgreSQL persistence. This design is written
before implementation. Authority: [ADR-021](../adr/ADR-021-measured-twin-completion-program.md).
Responses use [API_STANDARD.md](API_STANDARD.md); this is spatial metadata, not a
configuration push to physical devices.

## Routes and authorization

`GET /api/v1/networks/{network_id}/spatial-scene` requires an authenticated current
session, current `read:topology` permission and current workspace membership.
`PUT` at the same URI requires current `write:config` permission and writable
workspace membership (Organization's Admin/Operator rule). Optional token workspace
and organization claims narrow access. Network must exist and not be soft-deleted.
Membership uses public owning services, never cross-module SQL.

Both operations return HTTP 200 with `data` equal to the complete scene document:

```json
{
  "success": true,
  "data": {
    "version": 1,
    "revision": 0,
    "coordinate_system": {"units": "m", "up_axis": "y"},
    "objects": []
  },
  "meta": {
    "request_id": "e0c84701-74b0-4e51-a0aa-0d0a84e19ff9",
    "timestamp": "2026-09-19T12:00:00+00:00",
    "execution_time_ms": 1,
    "execution_mode": "demo"
  },
  "errors": null
}
```

A network without a stored scene reads as revision **0**, with empty objects,
without creating a database row. No implicit import of legacy schematic placements.

## Exact request and document fields

PUT body has exactly `expected_revision` and `scene`. `scene` has exactly `version`,
`coordinate_system`, and `objects`; clients cannot supply `revision` inside it.
Every field shown below is required, including nullable fields. Unknown fields at
any level are rejected. Object order is preserved, but parents can occur after children.

```json
{
  "expected_revision": 0,
  "scene": {
    "version": 1,
    "coordinate_system": {"units": "m", "up_axis": "y"},
    "objects": [
      {
        "object_id": "device-ap-1",
        "parent_id": null,
        "object_type": "device",
        "name": "Access point 1",
        "position": {"x": 1.5, "y": 2.4, "z": 0},
        "rotation": {"x": 0, "y": 1.5707963267948966, "z": 0},
        "device_id": "b02868da-5d90-4b67-b522-d8f751395624",
        "provenance": {"source": "operator-survey", "accuracy_m": 0.1}
      }
    ]
  }
}
```

The example device UUID must refer to active inventory in the target network.

| Field | Contract |
|---|---|
| `version` | Integer literal `1` (not boolean or string). |
| `revision`, `expected_revision` | Strict integers, 0 through 9,007,199,254,740,991 (JavaScript-safe). Successful PUT assigns expected + 1. Exhaustion returns 409. |
| `coordinate_system` | Exactly `{ "units": "m", "up_axis": "y" }`. |
| `objects` | Array, 0–10,000 objects, unique case-sensitive stable IDs within this network. |
| `object_id`, `parent_id` | Nonblank strings of 1–128 characters; parent may be null. No NUL characters. IDs are preserved, not trimmed or generated. |
| `object_type` | `campus`, `building`, `floor`, `room`, `rack`, `device`, `interface`, or `wall`. |
| `geometry` | Optional, nullable ADR-023 discriminated union below. Omission and explicit null are preserved separately. |
| `name` | Nonblank string of 1–256 characters, no NUL. |
| `position` | Exactly numeric finite `x,y,z`, each in [-1,000,000, 1,000,000] meters. No numeric strings or booleans. |
| `rotation` | Exactly numeric finite `x,y,z`, each in [-2π, 2π] **radians**. No numeric strings or booleans. |
| `device_id` | UUID string or null. Only a `device` object can associate inventory. Each inventory device occurs at most once in a scene. Missing, deleted or foreign-network device references are rejected identically. |
| `provenance` | Exactly `source` (nonblank 1–128 characters, no NUL) and `accuracy_m` (null or finite numeric 0–1,000,000 meters). Null means unknown, never zero error. |

## Hierarchy and transforms

All non-null parents must exist in this replacement document. Self-parenting and
cycles are rejected. A parent must be earlier in the ordered containment types
`campus → building → floor → room → rack → device → interface`; skipped levels are
allowed. Any type except interface and wall can be a root. An interface requires a direct
device parent and has null `device_id` (association is inherited from that parent).
This bounds depth to seven objects without recursive traversal of untrusted input.
Exception: a `wall` requires a direct `floor` or `room` parent, cannot be a parent,
and must have null `device_id`. It is a leaf, not another containment rank.

The coordinate frame is right-handed, +Y up; +X × +Y = +Z. All positions and
rotations are **local to the parent**, or to the scene for roots. There is no
implicit scale, geodetic origin, axis conversion or inferred asset registration.
For column vectors the explicit local matrix is
`T(position) × Rz(rotation.z) × Ry(rotation.y) × Rx(rotation.x)` (apply X, then Y,
then Z about fixed parent axes). World matrix is `parent_world × local`; world
position is its translation column. Bounds apply to local components; composed
world coordinates may exceed a single local bound. The backend pure transform
helper implements this convention; derived matrices are not extra wire fields.

Clients must explicitly convert asset coordinates into this frame. Provenance is
operator-supplied metadata, not backend certification of measurement. Generated
schematic placements must use `source: "schematic-fallback"` and unknown accuracy
(`accuracy_m: null`); clients must retain that visible fallback labeling.

## Concurrency, transaction and errors

PUT replaces the entire scene (including removal by omission), never merges.
Expected revision must equal the stored revision, including first write at zero.
Every successful replacement, even byte-equivalent content, increments revision.
Concurrent requests from the same revision have exactly one winner. On 409 clients
GET the current scene and explicitly reconcile; blind retry would lose edits.

Canonical errors have `success:false`, `data:null`, normal `meta`, and
`errors:{code,message}`. Existing application handlers apply:

| Status | Condition / code |
|---|---|
| 401 | Missing, invalid, expired or revoked session (`AUTH_TOKEN_MISSING_OR_INVALID`). |
| 403 | Permission, scope or current membership denied (`FORBIDDEN`). |
| 404 | Missing/deleted network (`NOT_FOUND`). |
| 422 | Wire/structural validation (`VALIDATION_ERROR`); invalid inventory association (`SPATIAL_DEVICE_SCOPE_INVALID`); derived geometry bounds/resolution (`SPATIAL_GEOMETRY_INVALID`). |
| 409 | Stale expected revision (`SPATIAL_REVISION_CONFLICT`), or revision exhausted (`SPATIAL_REVISION_EXHAUSTED`). |

Network-owned table `network_spatial_scenes` stores one current JSONB scene payload
and bigint revision per network, with timestamps and an owning-network FK. Migration
**0021 after 0020** imports its owning metadata explicitly. PostgreSQL insert-on-
conflict plus conditional revision update serializes first-write and later races.
Referenced inventory rows are share-locked while checking their scope. Before
replacing the snapshot, the service acquires the network, device and scene locks
(including first-insert contention), expires SQLAlchemy's identity map and rechecks
writable membership and narrowing claims through the public Network/Organization
services against fresh READ COMMITTED database state. A revocation committed while
the request waited on any of those locks denies the write; any tentative revision0
placeholder is rolled back. The public
Identity `append_audit_log` service appends local audit action
`network.spatial_scene.replaced` in the **same transaction**, with actor, network,
workspace, old/new revisions, object count, SHA-256 of the canonical scene JSON and
request correlation. Non-UUID request IDs are deterministically mapped to UUIDv5
for the audit's existing UUID column. Audit or persistence failure rolls back both.
This audit action is not a domain event; no event bus or websocket messages are added.
ADR-022 adds immutable revision bodies as described below. Network soft-deletion
hides its current scene and history.

## ADR-022 immutable history contract

Design recorded before history router implementation. Both new routes require
the same current session, `read:topology`, current workspace membership and optional
narrowing organization/workspace claims as current-scene GET. Historical authorship
does not grant access after membership revocation. The service expires cached ORM
state before history authorization. Reads do not require inventory devices in an old
body to remain active; attempting to restore that body does require current validity.

### History list

`GET /api/v1/networks/{network_id}/spatial-scene/history?page=1&page_size=20`

Query bounds: integer `page`1–1,000,000 and `page_size`1–100. Canonical HTTP200
envelope with `data`:

```json
{
  "items": [
    {
      "revision": 7,
      "recorded_at": "2026-09-20T12:00:00Z",
      "actor_id": "00000000-0000-0000-0000-000000000303",
      "origin": "replacement",
      "object_count": 12
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

`items` are descending by revision, metadata only (no scene bodies). `total` and
items are read from one database statement/snapshot. An out-of-range page returns
empty items and the actual total. Separate page requests are live views: new writes
can shift offsets; this is not a frozen multi-page export cursor. `recorded_at` is
the timestamp the history row was recorded, not a claimed original measurement
time. `origin` is exactly `replacement` or `baseline`; `actor_id` is UUID or null
(unknown baseline author). Revision numbers may have gaps preceding a baseline.

### Revision body

`GET /api/v1/networks/{network_id}/spatial-scene/history/{revision}`

`revision` is an integer0–9,007,199,254,740,991. HTTP200 canonical envelope `data`
is exactly the scene document used by current GET (`version`, `revision`,
`coordinate_system`, `objects`), not a wrapper with metadata. Missing history entry
returns404 `SPATIAL_REVISION_NOT_FOUND`. Authorization is checked before existence.
Invalid pagination/path input returns422 `VALIDATION_ERROR`.

### Persistence, baseline and restore

Network-owned migration **0022 after0021** creates `network_spatial_scene_revisions`
with composite primary key `(network_id, revision)`, full scene JSONB body excluding
the separate revision column, timestamp, nullable actor UUID logical reference and
origin. Database triggers reject row UPDATE/DELETE and table TRUNCATE. The network
FK has no deletion cascade; operational network deletion remains soft deletion.

The migration copies each existing stored snapshot at its **existing revision**
into one immutable `baseline` entry, with null actor and migration recording time.
The copy holds a snapshot-table write barrier until migration commit. Drain old
scene writers for deployment; running pre0022 service code afterward cannot append
history and is unsupported.
It does not invent missing previous bodies or backfill them from audit hashes.
Networks with no persisted scene have empty history; their virtual current revision0
is not a stored history entry. A persisted revision0 snapshot, if one exists at
migration time, is preserved as a baseline. Downgrade removes the history table and
its triggers only; the current snapshot is retained.

Every successful PUT appends exactly one `replacement` history entry in the same
transaction as current snapshot replacement and public Identity audit append.
Conflict, membership denial, history failure, audit failure or rollback leaves all
three unchanged. Existing post-lock authority refresh remains mandatory. New history
is append-only even when submitted content is identical to the current scene.

Restore uses the existing PUT: GET the selected history body, remove its `revision`
field, and submit it as `scene` with the **current** `expected_revision`. A successful
restore creates current+1 and a fresh history/audit entry. No restore route or
historical rewrite is introduced. Current device scope and schema validation apply.

## ADR-022 asset registration schema (asset-owner handoff)

Owning schema import:
`from app.modules.network.registration import AssetRegistration`.
The existing asset request/response field is `registration: AssetRegistration | None`.
Missing/null means unregistered, including all legacy assets. There is no implicit
identity registration or position inference. The asset workstream owns adding this
field to existing schemas/models/service and its JSONB persistence in **0023**;
0022 is history-only under the user's explicit ownership split.

```json
{
  "version": 1,
  "translation": {"x": 0, "y": 0, "z": 0},
  "rotation": {"x": 0, "y": 0, "z": 0},
  "scale": {"x": 1, "y": 1, "z": 1},
  "target_units": "m",
  "target_up_axis": "y",
  "source": "operator-registration"
}
```

All seven fields and all vector components are required when registration is
non-null. Unknown fields are rejected at every level. Version is strict integer1;
target literals are exactly `m` and `y`. Translation is finite numeric meters per
axis in±1,000,000; rotation is finite radians per axis in±2π, with the scene's
`Rz × Ry × Rx` convention. Scale is finite numeric per axis in[0.000001,1,000,000]
(positive, bounded, no reflection/zero). Numeric strings and booleans are rejected.
Source is a nonblank1–128 character string without NUL. Source is provenance, not
measurement certification. Column-vector matrix is
`T(translation) × Rz × Ry × Rx × S(scale)`, mapping asset-local coordinates into
the canonical meter/Y-up scene frame. Scale values include any explicit source-unit
conversion; legacy source units/axis conventions must not be guessed.

Asset registration does not infer canonical dimensions or materials.

## ADR-023 dimensioned geometry (design recorded before implementation)

The existing version1 object accepts optional `geometry`; omitted or null means
unknown geometry, never a default shape. The exact non-null union is discriminated
by `kind`; every listed field is required and extra fields are forbidden:

```typescript
type Geometry =
  | {kind: 'box'; width: number; depth: number; height: number}
  | {kind: 'slab'; width: number; depth: number; thickness: number}
  | {kind: 'wall'; length: number; height: number; thickness: number;
     material: {name: string; attenuation_db: number | null; source: string}};
```

- `building`, `room`, `rack` accept only box; `floor` only slab; `wall` only wall.
  Campus/device/interface reject non-null geometry. Any type may omit it or use null.
- Dimensions are strict finite numbers in **[0.000001, 1,000,000] meters**; numeric
  strings/booleans, subnormal/zero/negative/oversized values are rejected.
- Box occupies local X=[-width/2,width/2], Y=[0,height], Z=[-depth/2,depth/2].
  Slab has the same centered X/Z footprint and Y=[0,thickness].
- Wall lies in local XY: X=[0,length], Y=[0,height], with physical thickness
  centered on Z=0 (Z=[-thickness/2,thickness/2]). Transform the entire volume with
  the existing parent-composed `T × Rz × Ry × Rx`; origin/rotation never changes
  the supplied dimensions. General rotations are supported in canonical storage.
- Material name is nonblank1–256 characters; source nonblank1–128, neither allows
  NUL. Attenuation is strict finite numeric **0–100 dB**, or null for unknown.
  These are supplied metadata, not inferred frequency-dependent coefficients.
- Network's public pure geometry helper returns eight transformed volume corners.
  Each coordinate must be finite and within ±16,000,000m; transformed edges must
  remain numerically resolvable. These derived bounds accommodate all permitted
  seven-level placements and dimensions. No containment/overlap or survey accuracy
  certification is implied. No footprint/prism or inferred enclosing walls yet.

### Representation, persistence and hashing

No relational migration: geometry is stored in the existing current/history JSONB.
Default model serialization omits **only an absent geometry field**. An explicitly
supplied null remains null; other required nulls remain present. Do not inject
`geometry:null` into legacy objects on GET, history, restore, internal revalidation
or RF hashing. Existing geometry-free stored bodies and audit/RF hashes retain
their representation. Non-null geometry (including all material metadata) and
explicit null participate in hashes. Scene audit hashing retains the existing
sorted-key compact JSON body excluding revision; RF document hashing retains
revision and object-ID sorting. Frontend RF hashing must include supplied geometry
without manufacturing an omitted key. Changing dimensions/material invalidates
old scene-bound artifacts even when object origins are unchanged.

### Simulation bridge extension

`canonical-spatial-rf.v1` keeps its existing explicit `SpatialWall` entries. An
additional exact wall-reference alternative is `{wall_id, object_id, source}`:
`wall_id` is the existing RF-safe alias, `object_id` a canonical wall ID and `source`
the existing required `ValueSource` evidence. Extra geometry overrides are rejected.
Every canonical wall object must appear exactly once in this reference inventory;
missing/null wall geometry is rejected for RF. Legacy explicit entries cannot use
a canonical wall as their frame. Total walls remain bounded to256. Legacy scenes
and requests with no canonical walls retain their exact hashes/results.

The bridge derives endpoints from local (0,0,0) and (length,0,0), transforms through
all ancestors, then maps Network (X,Y,Z) to RF (X,-Z,Y). Height comes from geometry.
World-up must be preserved within1e-12; tilt/inversion is rejected, not flattened.
RF endpoint/top coordinates retain ±100,000m bounds and height≤1000m. Thickness
is retained in the pinned canonical scene but the RF model is a center-plane
single-crossing approximation, not a volumetric propagation solver. Canonical
material attenuation must be known; it is passed as `custom` with explicit loss,
never replaced with nominal material defaults. Material name/source remain in the
pinned input. Existing ancestor accuracy, evidence, scope and persisted-revision
requirements remain. Geometry availability does not manufacture accuracy evidence.

## Integration and limits

Router composition belongs to the parent integrator:

```python
from app.api.v1.spatial import router as spatial_router
app.include_router(spatial_router)
```

Apply migrations through0022 before serving the history-enabled router. No new dependencies or
configuration keys. Shared response/error handlers must be installed as in the
existing application. No Neo4j projection, asset bytes, frontend integration,
or physical/RF accuracy guarantee is provided here. Database
race/rollback/migration tests are opt-in with `SPATIAL_TEST_DSN` pointing to an
authorized disposable PostgreSQL database; tests own only a UUID-named schema.
