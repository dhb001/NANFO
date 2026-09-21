# ADR-023 Geometry handoff

## Backend design — 2026-09-20

Contract recorded before code in `docs/api/SpatialScene.md`, ADR-023 section.
Backend owns Network spatial schemas/transforms/service tests and the Simulation
`spatial_rf` bridge. Existing JSONB/history; no migration or composition changes.

Frontend agent: implement against that exact union and bounds. Box/slab centered
X/Z, base Y=0; wall X=0..length, Y=0..height, thickness centered Z. Wall is a leaf
under floor/room. Optional geometry must preserve absence versus explicit null.
Update **RF scene hashing** to include supplied geometry/material metadata; do not
inject a null key into legacy objects. Test legacy artifact acceptance plus
geometry/material mutation invalidation. Do not render inferred dimensions.

RF bridge accepts legacy explicit walls or `{wall_id, object_id, source}` canonical
references; every canonical wall must be referenced once. No endpoint/material
overrides on references. Known attenuation and existing placement accuracy evidence
are required for RF; absent values stay unknown. Tilt is rejected by RF, allowed in
canonical storage/rendering. See contract for bounds and center-plane limitation.

## Backend delivery and verification — 2026-09-20

Implemented exact discriminated shapes, strict dimensions/materials, wall hierarchy,
omission-preserving default serialization, eight-corner rigid volume transforms,
bounded numerical validation before save, and canonical-reference RF conversion.
Public helpers: Network `world_geometry`, `geometry_corners`, `transform_point`,
existing `world_matrices`; Simulation `CanonicalWall`, existing `build_spatial_rf`.
Storage/read/history routes and JSONB schema remain compatible. Unsupported RF
tilt, unknown attenuation/accuracy, missing/duplicate walls and geometry overrides
are rejected. No material defaults or accuracy values are supplied by this increment.

Verification from `backend/`:

- `poetry run pytest tests/unit/test_spatial_geometry.py tests/unit/test_spatial_scene.py tests/unit/test_spatial_rf.py tests/unit/test_spatial_registration.py tests/unit/test_twin_physics.py tests/integration/test_spatial_endpoints.py --no-cov -q`
  **357 passed**. Includes captured pre-ADR023 scene/adapter/config/evaluation hashes,
  omission versus null, exact API serialization, dimension/material hash invalidation,
  parent/noncommuting rotations, minimum/maximum volumes and RF crossings/tilt.
- `SPATIAL_TEST_DSN=<disposable DSN> poetry run pytest tests/integration/test_spatial_postgres.py --no-cov -q`
  **25 passed** using a separate `postgres:16-alpine` container, loopback ephemeral
  port and UUID-owned schemas. Container `nanfo-geometry-pg-20260920` was stopped
  and automatically removed. Covered geometry save/reload/history/restore, exact
  stored legacy omission and audit/RF hashes, CAS races, authorization and rollback.
- Scoped Ruff on all touched Python files: **passed**. `git diff --check`: **passed**.
- Broader `poetry run pytest tests --no-cov -q`: **2773 passed, 150 skipped,
  11 failed** during concurrent workstream development (before final eight added
  geometry guard tests). Ten failures concern telemetry persistence mocks/counters:
  `integration/test_emulation_ingestion.py`, `test_telemetry_persistence_flow.py`,
  `test_telemetry_synthetic_load.py`, `unit/test_telemetry_consumer.py`,
  `test_telemetry_persistence.py`. One is `test_verify_measured_twin.py` asserting
  acceptance schema0024 while concurrent migration head is0027. Parent/owning agents
  must reconcile those; no full-repository green claim. An earlier120s full-suite
  invocation timed out; the completed invocation used600s and finished in153s.

No migration, configuration, deployment composition, main or frontend edits by
this workstream. No commits or physical measurements. Geometry is operator-supplied
metadata; RF remains the explicitly documented center-plane configured model.

## Frontend integration status

Frontend completion is pending its owning agent's evidence. Required gate: update
scene types/validation/editor/rendering and **RF hashing**, retaining captured legacy
artifact acceptance while rejecting dimension/material mutations. Record frontend
results here in a separate section without overwriting backend evidence.
