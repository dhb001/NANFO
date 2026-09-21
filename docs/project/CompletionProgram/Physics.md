# P2 simulation fidelity toolkit — ADR-021

## Delivery and boundary

Simulation-owned, offline utilities:

| File | Callable / purpose |
| --- | --- |
| `backend/app/modules/simulation/rf.py` | `evaluate_rf(RFRequest) -> RFResult`; `rf_config_hash(RFScene)` |
| `backend/app/modules/simulation/calibration.py` | `evaluate_calibration(CalibrationRequest) -> CalibrationResult` |
| `backend/app/modules/simulation/snapshot.py` | `build_snapshot(SnapshotRequest) -> (ScenarioConfig, SnapshotProvenance)` |
| `backend/app/modules/simulation/spatial_rf.py` | `build_spatial_rf(SpatialRFRequest) -> (RFRequest, SpatialRFProvenance)` via Network public pure transforms |
| `backend/scripts/evaluate_twin_physics.py` | `rf`, `spatial-rf`, `calibration`, `snapshot` operator modes; request JSON Schema export |
| `backend/tests/unit/test_twin_physics.py` | Analytical, validation, reproducibility and CLI filesystem tests |
| `backend/tests/unit/test_spatial_rf.py` | Canonical parent/AP transform, evidence rejection and numerical boundary regressions |

The toolkit imports the existing evaluator's canonical hashing and fluid scenario
contract. Snapshot evaluation calls its existing checkpoint/advance/output functions.
The existing evaluator, schemas, lifecycle, endpoints, events, dependency set and
application composition are unchanged by this workstream. New schemas are local
operator contracts, not simulation API or websocket fields. No storage migration.

All computation boundaries revalidate nested inputs and are deterministic, synchronous,
bounded pure computations. Results retain `physical_safety_authorized=false`.
No real RF campaign was supplied or run; analytical tests do not establish physical
fidelity. Calibration fixtures with `source_kind=measured` exercise validation
semantics only and are not actual measurements.

## RF model and units

Version: **`log-distance-segment-walls.v1`**.

```text
d = Euclidean 3D distance in meters
d_eff = max(d, d0)
PL0 = 20 log10(4 pi d0 frequency_mhz * 10^6 / 299792458)
PLdistance = 10 n log10(d_eff / d0)
PLwalls = sum(single-crossing loss_db for intersected finite wall surfaces)
signal_dbm = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - PL0 - PLdistance - PLwalls
```

`coordinate_frame_id` identifies one aligned local Cartesian frame with **Z up**;
all transmitter/receiver/wall coordinates are meters in that frame. The caller
must apply owning-service model transforms, units and registration before calling.
The direct RF model does not accept geographic degrees, implicitly scale render coordinates,
or infer placements. `geometry_source_id`, scene/transmitter IDs and workspace/network
scope are explicit. IDs are opaque canonical owner IDs, never display names or
array positions; syntax uses the existing bounded simulation `Identifier` type.

Each wall is a vertical rectangle extruded from a horizontal `start`–`end` base
segment by `height_m`. Intersection uses the actual TX→RX segment parameter, finite
wall parameter and interpolated Z; a distant wall's infinite plane cannot attenuate
the ray. Interior radio-segment crossings only (`0 < t < 1`), inclusive wall edges
and height, parallel/collinear rays excluded. Near-parallel cross products use a
relative `1e-12` threshold. A radio exactly on a surface is not counted as crossing
it. Separate wall IDs at a shared corner each contribute; callers must avoid
duplicate/tessellated representations of one physical surface. No floor slabs,
sloped surfaces, reflection, diffraction, multipath, polarization or thickness
integration are modeled. Wall base length must be at least one micrometer.

Defaults are explicitly illustrative: `n=2`, `d0=1 m`; material loss per crossing
is glass **3 dB**, drywall **4 dB**, concrete **12 dB**, metal **20 dB**. They are
not measured coefficients and do not vary with frequency, thickness or incidence
angle. Set `loss_db` to override any material; `custom` requires that field.
Every returned crossing labels its loss as `configured` or `nominal_default`.
TX power and both antenna gains are required; gains are scalar effective gains
for the requested direction, not a radiation-pattern solver. The clamped distance
and clamp flag are reported, so co-location cannot cause infinite received power.

`uncertainty_db` defaults to **null (unknown)**. If supplied it is a caller-assumed
symmetrical dB error magnitude, not an estimated standard deviation or confidence
interval. It is retained verbatim. Neither nominal defaults nor fitted mean bias
establish spatial accuracy. Signal is independent of congestion; interference,
SINR and congestion are explicitly null, never estimated from RSSI or utilization.
There is no conversion from signal to throughput or link capacity.

Bounds: 256 walls, coordinates ±100,000 m, wall height `(0,1000] m`, frequency
100–100,000 MHz, TX power −100–60 dBm, gains −30–60 dBi, exponent 1–6,
reference distance 1–100 m, each loss 0–100 dB. These are computation bounds, not
an assertion that the approximation is physically valid over the entire range.
Scene hashes include model version and defaults after validation; wall order is
canonicalized by ID. Request hashes also pin receiver identity and position.

## Declared-split calibration evaluation

Version: **`rf-declared-split-bias.v1`**. One RF scene/configuration and one declared
measurement source per request. Every sample carries scope, `config_sha256` from
`rf_config_hash(scene)`, source ID/kind, source record ID, capture ID, receiver ID/
position, timezone-aware observation time, and measured signal in dBm. Scope,
configuration hash, source ID and source kind must exactly match the request.
At most 1,024 samples; signal range −250–100 dBm. No nearest-time, nearest-location,
name-based, cross-frequency or cross-configuration matching is performed.

Every unique sample must appear exactly once in explicit `train_ids` or
`holdout_ids`. Duplicate IDs, source records, receiver/time observations and
overlapping splits reject. Correlated `capture_id` groups cannot cross the split.
The operator must declare captures honestly and freeze the scene and split before
examining holdout results. The toolkit cannot detect relabeled captures, prior
holdout-guided tuning, falsified provenance or dependence across declared groups.

Only one parameter is fitted, a constrained additive received-power offset:

```text
offset_db = clamp(mean(observed_train - predicted_train), -40, +40)
fitted_prediction = original_prediction + offset_db
residual = prediction - observation
```

Scene, exponent, wall losses and gains are frozen. Offset bounds are versioned,
with a returned bound-hit flag. Train residuals alone enter the estimator;
holdout observations are evaluated only after fitting. Both splits report baseline
and fitted count, MAE, RMSE, signed mean error and maximum absolute error in dB.
There is no metric-based selection, automatic split, resampling, optimizer or
fitted-offset deployment. Request hashes and sorted split IDs preserve the exact
evaluation basis; changing holdout observations does not change the fitted offset.

Missing train or holdout data returns `status=unavailable`, null fit/metrics.
Synthetic data returns `synthetic_only`; a declared measured source with both
splits returns `measured_holdout_evaluated`. **`calibrated` remains false in every
case**: no independently attested source, acceptance threshold, representative
sampling or confidence-interval contract exists yet. An offset can reduce mean
bias while leaving large physical errors; held-out metrics must be reviewed as-is.

## Snapshot construction and comparability

Version: **`explicit-scenario-snapshot.v1`**. Input is an owning-service export
assembled by an operator with explicit workspace/network scope, snapshot ID,
network configuration artifact hash and canonical `node_ids`. Each link wraps an
existing `ScenarioLink` as `config`, plus per-field `sources` for capacity, buffer,
delay and initial queue. Each flow wraps `ScenarioFlow` as `config`, plus
`demand_source` and `route_source`. Each source requires:

```json
{"kind":"configured","source_id":"operator-1","record_id":"config-1","artifact_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

`kind` may be `measured` or `configured`; it never changes the evaluator's output
source (`operator_configured_model`). A hash pins the caller's source artifact;
this offline builder cannot authenticate that artifact or verify current network
membership. Each export must be scope/configuration-consistent before assembly.
Measured capacity must represent the modeled directed service rate; a sampled
traffic rate is demand, not link capacity. Counter intervals, reset handling,
sampling windows and physical units belong to the measurement source artifact.

Capacity, demand, buffer, delay and initial queue are required, including explicit
zero where appropriate. No missing quantity is invented; routes are required.
The snapshot boundary additionally rejects capacity byte budgets
`capacity_mbps * tick_ms * 125 < sys.float_info.min` (subnormal/zero) to avoid
unstable utilization/service division in the unchanged fluid evaluator. RF walls
reject heights that disappear when added to their base elevation in IEEE-754.
IDs pass through unchanged; all link/flow endpoints must belong to `node_ids`.
The existing `ScenarioConfig` validation enforces directed acyclic connected paths,
unique link/flow IDs, demand vector length, finite values and queue/buffer bounds.
It also enforces 128 nodes/links, 64 flows, 1,000 ticks and **16,384 total
tick/link/flow/path work units**. `action_binding=None`: offline snapshots do not
bind or authorize production actions.

The return value is a tuple: the existing `ScenarioConfig` and **separate** typed
provenance. CLI output keeps `scenario_config`, `provenance`, and the unmodified
`evaluation` result separate. Provenance includes canonical snapshot/scenario/
workload hashes and per-field sources. It is not embedded into existing wire fields.

Comparison requires the same workload hash (seed, tick, duration, flow identities,
endpoints and demand), plus review of sources, units, capture windows and model
versions. Link capacities/routes may be deliberate scenario interventions; source
changes must be documented. The workload hash does not attest equivalence of real
traffic or hardware. `MATH.md` remains authoritative for fluid queues, finite-horizon
censoring, tick-rounded latency, no TCP/contention, and objective versus safety gates.

## Operator usage

Run from `backend/` using the existing Poetry environment:

```bash
poetry run python -m scripts.evaluate_twin_physics rf --schema
poetry run python -m scripts.evaluate_twin_physics calibration --schema
poetry run python -m scripts.evaluate_twin_physics snapshot --schema
poetry run python -m scripts.evaluate_twin_physics rf --input /tmp/rf.json --output-dir /tmp/results --output-name rf-result.json
poetry run python -m scripts.evaluate_twin_physics calibration --input /tmp/calibration.json --output-dir /tmp/results --output-name calibration-result.json
poetry run python -m scripts.evaluate_twin_physics snapshot --input /tmp/snapshot.json --output-dir /tmp/results --output-name snapshot-result.json
```

Create the output directory beforehand. Every directory component must exist and
be a real directory: symlinks and `..` are rejected. Output names are a bounded
ASCII basename ending in `.json`; exclusive mode-0600 creation rejects existing
files and symlinks without overwriting. Directory descriptors pin the destination.
A caught write failure removes the newly created partial file; a process kill or
machine failure can still leave a partial file, so consumers must parse complete
JSON and verify hashes before use. Input must be a regular non-symlink file ≤2 MiB;
output ≤16 MiB. Duplicate JSON keys, nonfinite values, extra fields, coercible
strings/booleans in numeric fields and excessive collection sizes reject. Errors
return exit code 2 with a bounded message, never input dumps or stack traces.
Successful evaluation/file creation returns 0; inspect calibration status and
fluid objective checks independently of CLI success.

Minimal RF request (illustrative geometry, not a measured dataset):

```json
{
  "scene": {
    "scope": {"workspace_id": "workspace-1", "network_id": "network-1"},
    "scene_id": "scene-1",
    "coordinate_frame_id": "building-local-meters",
    "geometry_source_id": "survey-1",
    "transmitter_id": "ap-1",
    "transmitter": {"x": 0.0, "y": 0.0, "z": 1.0},
    "frequency_mhz": 2400.0,
    "tx_power_dbm": 20.0,
    "tx_gain_dbi": 2.0,
    "rx_gain_dbi": 1.0,
    "walls": []
  },
  "receiver_id": "rx-1",
  "receiver": {"x": 10.0, "y": 0.0, "z": 1.0}
}
```

For calibration, use the same `scene`, required `measurement_source_id` and
`measurement_source_kind`, `measurements` and explicit train/holdout ID arrays.
Empty arrays produce a valid unavailable report. The generated JSON Schemas are
the exact full input contracts; executable complete calibration/snapshot fixtures
are in `test_twin_physics.py` and are explicitly synthetic test data.

## Verification and integration handoff

Scoped command (from `backend/`):

```bash
poetry run pytest tests/unit/test_twin_physics.py tests/unit/test_simulation_evaluator.py tests/unit/test_simulation_output_schemas.py -q --no-cov
poetry run ruff check app/modules/simulation/rf.py app/modules/simulation/calibration.py app/modules/simulation/snapshot.py scripts/evaluate_twin_physics.py tests/unit/test_twin_physics.py
poetry run ruff format --check app/modules/simulation/rf.py app/modules/simulation/calibration.py app/modules/simulation/snapshot.py scripts/evaluate_twin_physics.py tests/unit/test_twin_physics.py
```

Final analytical/regression gate: **82 passed**; scoped lint and formatting passed.
The initial 78-test gate passed; edge-case review added rigid-transform/ray-reversal,
invalid wall/mutated-input, timezone-equivalent duplicate observation and FIFO-input
checks. Formatting checks initially identified formatting-only differences, corrected
before completion. Coverage includes known free-space loss, frequency doubling,
exponent/gains, 3D distance and clamping, finite/oblique/collinear/height/edge wall
intersections, material overrides, strict numeric bounds, held-out changes leaving
the fit unchanged, source/scope/config mismatch rejection, missing-data statuses,
split/capture leakage rejection, explicit snapshot requirements, fluid conservation
regressions and byte-identical CLI results across fresh hash-seeded processes.

Future integration belongs to the owning services and parent program:

1. Use the explicit adapter below for canonical spatial exports; independently
   verify wall representation, radio antenna direction and source artifact hashes.
2. Assemble scope-consistent measured/configured snapshots from owner exports,
   preserving actual capacity, demand windows, queues and routes. Reuse existing
   simulation admission rather than adding fields to its evaluator output.
3. Capture real RF measurements with independent grouped train/holdout campaigns,
   frozen configuration and source identities. Define acceptance thresholds and
   uncertainty estimation before claiming calibration; retain unsuccessful fits.
4. Keep RF predictions and separate provenance as owning-service/operator artifacts
   until a separately approved integration contract defines consumption. Any
   interference/channel contention, radio capacity mapping, richer geometry or
   physical authorization requires additional model work and measured acceptance.

No dependency/infrastructure blocker for the offline toolkit. Physical calibration
and integrated measured acceptance remain unavailable pending real evidence.

## Canonical spatial scene → RF adapter

Version **`canonical-spatial-rf.v1`** consumes the existing Network
`SpatialSceneDocument` (the `data` from authenticated
`GET /api/v1/networks/{network_id}/spatial-scene`). The approved public pure helper
`app.modules.network.spatial_transforms.world_matrices` composes
`parent_world × T × Rz × Ry × Rx`. Only Network's public schemas/transform helper
are imported: no persistence models, repositories, service database access or SQL.

**Axis conversion is explicit and right-handed:** canonical world `(X,Y,Z)` with
Y up becomes RF `(X,-Z,Y)` with Z up. Transforms are applied before conversion.
The radio's required `local_offset_m` is transformed by the AP's complete world
matrix, including AP rotation, so an offset antenna is not placed at the parent
origin. Receiver coordinates and wall bases are local to their explicitly named
`frame_object_id`. Scalar antenna gains remain operator parameters for this ray;
AP rotation moves the antenna offset but does not synthesize a gain pattern.

Required input fields (full exact schema via `spatial-rf --schema`):

- `scope`, explicit RF `scene_id` and `coordinate_frame_id`, existing canonical
  `scene` including revision, and `scene_source` evidence.
- `radio`: canonical `object_id`, matching inventory `device_id`, explicit RF
  `transmitter_id`, `local_offset_m`, `parameters` (frequency, TX power, both gains
  and optional RF defaults), and `source` evidence.
- `receiver`: RF `receiver_id`, canonical `frame_object_id`, explicit
  `local_position_m`, and `source` evidence.
- `walls`: 0–256 explicit wall records, each with `wall_id`, canonical frame ID,
  local Y-up `start`/`end`, positive `height_m`, material/optional loss, and source.
  Network v1 stores placements, **not wall shapes**; object type/name is never used
  to infer dimensions or material.
- `wall_inventory_source`: required even for an explicitly empty wall list. Empty
  means the operator asserts no modeled walls in this evaluation, not that missing
  evidence was interpreted as free space. All source records use `ValueSource`.

`scene_source.artifact_sha256` must equal
`spatial_document_hash(SpatialSceneDocument.model_validate(scene))`: validated JSON
including revision, object array sorted by canonical object ID, then the existing
canonical JSON digest. This is an adapter-defined digest, **not** Network's audit
digest or a raw response-file hash. Other source artifact hashes are retained
declarations; the CLI does not open or authenticate their source artifacts.

Revision zero, absent AP/device association, unknown frames, hash mismatch,
missing source records, missing radio/geometry fields and `schematic-fallback`
placements reject. Every referenced object **and ancestor** needs non-null declared
`accuracy_m`; no value is supplied for unknown accuracy. The adapter cannot certify
declared accuracy or detect a falsely labeled survey. The canonical scene has no
embedded network/workspace identity, so the operator must retain its authenticated
export context and supply the matching scope; an offline file cannot prove tenancy.

Canonical object IDs allow more characters/length than RF IDs. The explicit RF
alias is supplied by the operator; original canonical AP/device/frame IDs remain
in provenance without truncation, hashing into placements, or generated IDs.
The adapter never interprets an ID digest as coordinates.

For walls, local base Y values must match. The composed local-up vector must match
world +Y to `1e-12`; inverted/tilted surfaces reject because RF v1 supports only
vertical rectangles. Height differences in transformed base endpoints above
`1e-8 m` reject; smaller floating-rotation residue is normalized to the first base
height. Composed coordinates outside RF's ±100,000 m bounds reject rather than
clamping or silently rebasing. Canonical Network scenes permit larger coordinates,
so not every valid Network scene is representable by this RF version.

The adapter returns an ordinary replayable `RFRequest` plus separate provenance:
adapter version/input hash, canonical document hash/revision, RF config hash,
axis conversion, original AP/device/frame identities, all sources, and declared
local placement accuracies for the referenced ancestry. These accuracy values are
**not** propagated RF uncertainty or statistical confidence bounds. CLI usage:

```bash
poetry run python -m scripts.evaluate_twin_physics spatial-rf --schema
poetry run python -m scripts.evaluate_twin_physics spatial-rf --input /tmp/spatial-rf.json --output-dir /tmp/results --output-name spatial-rf-result.json
```

Output contains `rf_request`, `provenance`, and `evaluation`. Keep all three and
the original request together. `evaluation.config_sha256` must equal
`provenance.rf_config_sha256`; `evaluation.input_sha256` pins the complete derived
RF request including receiver. Extracting `rf_request` and passing it to direct
`rf` mode reproduces `evaluation`; preserve the sidecar because direct `rf` output
does not contain canonical placement/source evidence. RF output is an analysis
artifact, **not** a `ScenarioConfig` and not input to the simulation start endpoint.

## Operator workflow: snapshot → existing simulation start endpoint

This is the actual configured-fluid endpoint workflow, separate from RF analysis.
It is documented for an authorized deployment; this workstream has not started a
live run or collected external calibration data.

1. Assemble a strict `SnapshotRequest` from actual owner exports/configuration.
   Supply real network/workspace UUIDs in `scope`, canonical configured graph IDs,
   directed routes, measured/configured capacity, buffer, queue, delay and demand
   with their sources. Canonical spatial placement alone supplies none of those
   quantities. Keep the full input/source evidence with the output.
2. Run the offline evaluator:

   ```bash
   poetry run python -m scripts.evaluate_twin_physics snapshot --input /tmp/snapshot.json --output-dir /tmp/results --output-name snapshot-result.json
   ```

3. Construct the existing start request from the **actual returned configuration**,
   without hand-copying model fields or adding provenance to the API schema.
   For example, in an operator Python session from `backend/`:

   ```python
   import json
   from pathlib import Path
   from uuid import UUID
   from app.modules.simulation.evaluator import canonical_config, digest
   from app.modules.simulation.schemas import ScenarioConfig
   from scripts.evaluate_twin_physics import write_result

   artifact = json.loads(Path('/tmp/results/snapshot-result.json').read_text())
   config = ScenarioConfig.model_validate(artifact['scenario_config'])
   provenance = artifact['provenance']
   assert digest(canonical_config(config)) == provenance['scenario_sha256']
   network_id = str(UUID(provenance['scope']['network_id']))
   body = {
       'network_id': network_id,
       'scenario_name': 'Explicit configured snapshot evaluation',
       'scenario_config': config.model_dump(mode='json'),
   }
   write_result(Path('/tmp/results'), 'start-request.json', body)
   ```

4. With the existing authenticated session for that network's workspace and
   `write:config` permission, submit through the existing route. For an operator
   shell with `API_BASE` and `TOKEN` provided by the deployment/session:

   ```bash
   curl --fail-with-body --silent --show-error \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     --data-binary @/tmp/results/start-request.json \
     "$API_BASE/api/v1/simulations/start"
   ```

   HTTP 202 and `data.simulation_id` identify the queued run; they are not a
   completed or passed result. Preserve that ID alongside the snapshot provenance.
   The start API authorizes the network/actor, not the external evidence hashes.
   Existing configured simulation persistence and the independent simulation
   worker must already be operational in the deployment. Operator worker entry:
   `PYTHONPATH=. poetry run python scripts/run_simulation_worker.py --batch-ticks 8`.
5. Poll the existing authenticated
   `GET /api/v1/simulations/{simulation_id}` (requires `read:topology`). Check
   `data.state`, progress and validation failure reason. On completion, verify
   `data.input_sha256` and `data.run_output.input_sha256` equal the retained
   `provenance.scenario_sha256`; inspect objective checks/risk gate independently
   of completion. With identical inputs/model, the worker output hash should equal
   the offline `evaluation.output_sha256`. Retain actual API response evidence.

The generated config has `action_binding=null`. This workflow does not bind an
intent, authorize physical changes, calibrate RF, or submit RF evidence as a safety
gate. Comparison uses the existing compare endpoint and workload/model compatibility
rules documented above. No public API fields or endpoints were added.

### Follow-up verification

Run from `backend/`:

```bash
poetry run pytest tests/unit/test_spatial_rf.py tests/unit/test_twin_physics.py tests/unit/test_simulation_evaluator.py tests/unit/test_simulation_output_schemas.py -q --no-cov
poetry run ruff check app/modules/simulation/rf.py app/modules/simulation/snapshot.py app/modules/simulation/spatial_rf.py scripts/evaluate_twin_physics.py tests/unit/test_spatial_rf.py
poetry run ruff format --check app/modules/simulation/rf.py app/modules/simulation/snapshot.py app/modules/simulation/spatial_rf.py scripts/evaluate_twin_physics.py tests/unit/test_spatial_rf.py
```

Follow-up scoped gate: **107 passed**. Analytical canonical test rotates both parent
and AP by π/2, applies the explicit antenna offset, verifies world/RF coordinates
and the actual wall crossing, and preserves IDs with spaces/slashes. Rejection
tests cover missing evidence/geometry, fallback ancestors, unknown accuracy,
identity/hash mismatch, tilted walls, RF bounds, subresolution wall height and
subnormal service budget. Spatial CLI output retains provenance and reproduces
direct RF evaluation. No external/physical calibration or live endpoint acceptance
is claimed.
