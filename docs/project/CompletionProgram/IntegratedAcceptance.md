# ADR021 integrated local service acceptance — 2026-09-19

## Latest0027 postreview refresh — PASS25/25,2026-09-20

Reran both **unchanged** actual integration lanes after the geometry, retention
replay/accessor and pin Core corrections. **Inventory15/15 and measured/retention10/10
passed on their first attempts**, both exit0/status`passed`, actual/runtime schema
0027, no failures, blockers or source drift. No production, deployment, verifier
or test implementation changes were required for this refresh.

The existing source gate was preserved exactly: all backend app Python, all Alembic
Python, outbox worker, verifier and backend lock are fingerprinted before and after.
Deployment/docs are already outside that gate; no subset was introduced to mask
concurrent edits. Each result retains its exact stable manifests.

Fresh durable credential-free files in[IntegratedEvidence-0027/](IntegratedEvidence-0027/README.md):

| File | SHA-256 | Bytes |
|---|---|---:|
| [inventory-result-postreview.json](IntegratedEvidence-0027/inventory-result-postreview.json) | `d2a26ee24605cf7e5abecfcb85887ceab121ce4fd722a173d8b94302e15da1ab` |56729|
| [measured-result-postreview.json](IntegratedEvidence-0027/measured-result-postreview.json) | `5f2ea62d9734b62e9cda9c6edff28abd5f1a5ef44bd04a6b70817f77b1461e5e` |59252|

Separate`checksums-postreview.json` catalog; earlier stable results, drift attempts
and original catalogs remain unchanged. Exact-byte no-overwrite export verified
original hashes,0027/passed/stability/cleanup and credential exclusion. Original
temporary results:`measured-twin-acceptance-_db04_73` and
`measured-twin-acceptance-oagzuikf` under`/tmp/opencode/`.

### Actual results and scoped tests

Inventory ran**09:09:50.482–09:10:20.389 UTC**; measured ran
**09:09:50.222–09:10:23.976 UTC**, both2026-09-20. The detailed25-case scope below
was repeated without additions. Geometry history/restoration/tenant/conflict/invalid
dimension cases, private CAS and outbox interruption/replay passed. Measured owner
authorization, real SNMP/Redis/PostgreSQL, history/cursor/manager denials and actor
revocation passed. Report source commit pinned3 actual records;14 unpinned records
were archived/deleted/restored with exact history equality, and28 tombstone replay
attempts were denied. No synthetic source values or mocked persistence booleans.

```sh
# backend/ — same commands as the0027 campaign below
poetry run pytest tests/unit/test_verify_measured_twin.py \
  tests/unit/test_spatial_geometry.py tests/unit/test_spatial_scene.py \
  tests/integration/test_spatial_endpoints.py tests/unit/test_retention_complete.py \
  tests/unit/test_telemetry_persistence.py tests/unit/test_telemetry_consumer.py \
  tests/unit/test_measured_snmp.py tests/unit/test_snmp_composition.py --no-cov -q
#382 passed in15.59s
poetry run ruff check scripts/verify_measured_twin.py tests/unit/test_verify_measured_twin.py
#All checks passed
```

No failures or nondeterministic retries occurred in this postreview refresh. The
actual lanes are the integrated evidence; the scoped regression selection exercises
the reviewed contracts without claiming unrelated full-suite/deployment coverage.

### Cleanup independently confirmed

- Inventory PostgreSQL PID1437043/TCP40289; RedisTCP48053, exact container
  `0c19d37b248e1d30baf05a06d869588b63f7dbf035fa301cf55d0a9d874bf33f`,
  `nanfo-adr021-redis-1aec0b81407c45b2b469eb4427066734` and its`-data` volume.
- Measured PostgreSQL PID1437030/TCP44209; RedisTCP57661, exact container
  `75ae0515559164627bc5880fb11f790e72d44078987453f701cd266fe9acb45f`,
  `nanfo-adr021-redis-cbe397b52f4a42a7893a5d3388bf319a` and its`-data` volume;
  SNMP PID1438882/UDP56384.
- All result cleanup assertions true. Independent label-filtered Docker lists
  returned no verifier containers/volumes;`ps` found none of the exact PIDs;`ss`
  found none of the four TCP/one UDP listeners. Private credentials, databases,
  CAS/report/archive/SNMP state removed. Shared services/data untouched.

Existing limitations remain: topology projection substituted/unverified; websocket
manager uses collecting transport, not actual network sockets; no new fleet,
autonomous execution, full Compose or physical qualification claim.

## Current0027 acceptance — PASS,2026-09-20

**15/15 inventory/spatial/assets/outbox/geometry cases and10/10 measured/retention
cases passed**, both exit0 with installed/runtime schema0027 and no blockers.
Updated only the owned verifier/tests/handoff/evidence. No deployment/main changes,
shared store mutation, image pull/build, external device or other agent lab operation.
The original14/8 checks remain; one geometry and two actual retention cases extend
the respective lanes. No authentication/owner permission bypass was introduced.

### Current migration and contracts

The verifier requires sole repository head0027 and executes the actual full Alembic
chain0001–0027, including retention tombstones/receipts0025, fleet0026 and Autonomy
0027 owner tables. Parent runtime head matched0027. Fleet/execution table migration
is verified; fleet scheduling or autonomous execution is not exercised by these lanes.

Read ADR023,`RetentionComplete.md` and`Geometry.md` before changes. Retention uses
actual persisted SNMP values and the public owner contracts: no fabricated pin,
receipt, tombstone, measurement or qualification. The verifier now records explicit
`source_changed_during_acceptance` blockers and exact changed paths in addition to
before/after hashes; whole-source stability remains enforced.

```sh
# backend/
poetry run python -m scripts.verify_measured_twin --live \
  --redis-image-id sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
poetry run python -m scripts.verify_measured_twin --live --measured-snmp \
  --redis-image-id sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
```

### Added geometry acceptance through real authenticated HTTP

- Existing14-case lane passed again: inventory remains unpublished until worker,
  actual Redis outage/retry and byte-stable post-XADD replay, audit dedup, spatial
  conflicts/tenant denial/history/restore, non-root CAS and session logout.
- Save five objects through mounted spatial PUT: explicit building box, floor slab,
  room box, wall with thickness/material and the actual inventory-associated device.
  Unknown material attenuation remains null; fixture provenance is explicit.
- Revision4 exact roundtrip through GET and history/detail; current foreign actor
  history GET/PUT403, stale PUT409, zero-width/bad wall parent/out-of-range material
  each422. Denials leave scene/history unchanged.
- Restore geometry-free revision3 body with expected4 creates **revision5**; absent
  device geometry stays omitted, and stored geometry revision4 remains unchanged.
  Existing earlier scene-history checks preserve revisions1/2 while restoring3.
- No extra endpoint was added: geometry uses existing version1 scene/history APIs.
  These are explicit operator-style fixture dimensions, not surveyed/calibrated RF.

### Actual measured persistence, pin-before-reference and tombstones

The existing8-case lane passed on the new persistence path, including real global
event advisory exclusion/tombstone lookup. Three real local SNMPv3 GETs produced
17 unique measured events/records; history and5-page cursor traversal matched them,
foreign HTTP and manager delivery were denied, repeated ingestion retained17 rows,
and Identity revocation caused zero further GETs/publications and closed delivery.
Websocket uses actual manager/current auth with collecting transport, not a network
socket. Shared domain consumers use local fanout mode; distributed fanout is not
claimed by this campaign.

New real retention sequence:

1. Before measurements, bounded `TelemetryReconciliationService.step` enumerates
   all five installed owner contracts in the newly created workspace. Each completes
   with scanned0/unknown0: this workspace genuinely has no existing owner references.
   No manual coverage-table insertion or assumed historical enrollment is used.
2. Collect and persist actual SNMP values **after** enrollment. Through actual
   authenticated`POST /api/v1/reports/generate`, create a telemetry CSV request
   filtered to`port_rx_bytes`. Report owning source capture freezes the three actual
   rows; its transaction-local before_flush hook creates exactly three Telemetry
   pins. Foreign generation and report detail return403. Report rendering/download
   is not part of this check; acceptance proves queued frozen reference/pin commit.
3. Resolve current writable membership through Organization before invoking the
   trusted internal retention contract. Assessment returns3 pinned/14 eligible,
   zero missing owners/unknown coverage. Actual archive-before-delete writes and
   checksums14 private archive files; receipt/tombstone/delete commits together.
   Authorized history shows exactly the3 pinned source rows; foreign history403.
4. All14 receipts and permanent event tombstones exist, active rows are absent.
   Real `TelemetryPersistenceService.persist_event` rejects both original and
   changed-tenant payload replay for every archived event: **28 replay denials**.
   A foreign-workspace internal restore rejects; no fake archived() return value.
5. After actual current authority check, restore14 records from verified bytes;
   authorized history is **exactly equal** to original17 rows, including original
   IDs, observed/created timestamps, values and tags. Permanent tombstones remain.
   Subsequent actor revocation and replay checks still pass.

This exercises the Report owner hook and all five owners' empty-workspace
enumeration/wiring. It does not claim nonempty references were generated for every
owner or historical production coverage. The owner's separate cross-owner/race
tests remain documented in`RetentionComplete.md`. Retention operations are internal
operator contracts with real authority checked by this verifier, not invented
public retention endpoints.

Measured intervals in final run:6.30s and6.37s, RX/TX rates377441.2698412699 and
399619.46624803764bps; counter growth615432 octets per direction. These are real
loopback counters including local protocol/database traffic, not isolated goodput
or physical line-rate calibration. Measurement provenance remains`measured_snmp`,
SNMPv3/authPriv, non-synthetic; loopback nominal speed remains10Mbps metadata.

### Results and root causes retained durably

Final exact results and all partial attempts:
[IntegratedEvidence-0027/](IntegratedEvidence-0027/README.md).

| Final lane | Exact result SHA-256 | UTC interval |
|---|---|---|
| Inventory15 cases | `b3961157e57a8d28aad7118c3bc9d4448c46422c4dfcea5b1ec15cf552652011` |08:46:36.893–08:46:52.111|
| Measured/retention10 cases | `5932961885a980b380170e4b33bad52a672cb945d8e3b9ab57acbb77d96250eb` |08:47:52.815–08:48:16.188|

Original directories:`measured-twin-acceptance-g97dkfg6` and
`measured-twin-acceptance-k94ncz7_` under`/tmp/opencode`. Both final manifests are
stable **within their own runs**; they are not asserted to be one simultaneous
whole-tree snapshot. The export verifies pinned exact-byte hashes,0027, functional
statuses, cleanup, expected stability status and credential exclusion. The catalog
records byte lengths and source drift paths; old0024 evidence is unchanged.

**No functional/application assertion failed.** Six earlier complete functional
runs were correctly partial because other workstreams edited sources during them:

- First inventory/measured pair: Autonomy execution contract, FRR contract and
  safety provider changed.
- Second pair: Autonomy safety/FRR installation files changed.
- Third measured attempt: Autonomy causal_frames changed.
- Fourth measured attempt: readiness, distributed realtime, main and causal_frames
  changed. This verifier did not edit those files.

All six are exported as`*-source-drift-*.json`, with original statuses/hashes; no
partial attempt was relabeled or stability check relaxed. Final reruns passed after
their source windows were stable. Fresh source additions after a completed run do
not inherit that run's acceptance; manifests identify the exact accepted bytes.

### Tests and cleanup

```sh
poetry run pytest tests/unit/test_verify_measured_twin.py \
  tests/unit/test_spatial_geometry.py tests/unit/test_spatial_scene.py \
  tests/integration/test_spatial_endpoints.py tests/unit/test_retention_complete.py \
  tests/unit/test_telemetry_persistence.py tests/unit/test_telemetry_consumer.py \
  tests/unit/test_measured_snmp.py tests/unit/test_snmp_composition.py --no-cov -q
#362 passed in6.67s
poetry run ruff check scripts/verify_measured_twin.py tests/unit/test_verify_measured_twin.py
#All checks passed
#After adding explicit source-drift diagnostics: verifier20 tests passed in3.01s.
```

New verifier tests assert actual0027→0021 migration ancestry and generated geometry
roundtrip preserves unknown attenuation and omitted legacy device geometry.

Final resources removed exactly:

- Inventory PostgreSQL PID1390557/TCP45679, RedisTCP35091, container
  `806d846003be15a45ed7ff5d6341903953b2a35035804e1d37c6356cfc014f4f`,
  name`nanfo-adr021-redis-3537303d10ae413c89e7831a81ba80d4`, owned`-data` volume.
- Measured PostgreSQL PID1395445/TCP56175, RedisTCP41253, container
  `55078d2da3dda78187ab6c201c3539b3fe3b6f8fe153ba1e73e330dd66130002`,
  name`nanfo-adr021-redis-6a229b26102441e0a1abf39972b722b3`, owned`-data` volume;
  SNMP PID1395910/UDP42155.

Every final and partial run has all cleanup assertions true: graceful stops,
process reaping, exact container/labelled-volume deletion, private PG/CAS/report/
archive/SNMP/credential tree removal, port release. Independent Docker label listings
found no verifier resources and process checks found none of the final PIDs.
No full Compose, physical acceptance, graph projection, actual network-websocket,
fleet scheduling, autonomous execution or production retention qualification claim.

## Latest inventory refresh after asset corrections: PASS14/14

Reran the unchanged inventory/spatial/assets/outbox lane after the asset owner's
crash-orphan hardlink recovery and authority recheck after final response read
corrections. **Exit0,14/14 cases passed, no failures or blockers**, actual/runtime
schema0024, source unchanged during execution. Measured SNMP was not rerun; its
earlier passing evidence remains intact below.

```sh
# backend/
poetry run python -m scripts.verify_measured_twin --live \
  --redis-image-id sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
```

Run time: **2026-09-19T21:53:58.268Z–21:54:11.430Z**. Exact credential-free durable
result: [inventory-post-asset-fixes-result.json](IntegratedEvidence-0024/inventory-post-asset-fixes-result.json).
SHA256 **`5ca8c9d5721450fb70289bb71ea5028c66e665b141f0b673cfd0b49129476632`**,
46347 bytes; separate [post-asset-fixes-checksums.json](IntegratedEvidence-0024/post-asset-fixes-checksums.json).
Original:`/tmp/opencode/measured-twin-acceptance-sxow0og6/result.json`.
Export validated original digest, passed status/schema/stability/cleanup and
credential exclusion, then verified exact copied bytes. All older results and
their checksums are retained unchanged.

Corrected source hashes recorded in both before/after manifests:

- `app/modules/network/asset_storage.py`:
  `a7a6c69b06bb1ebfc734bcb14228febb4fb0fcbd6372b8deb7061ccd5d907a54`
- `app/modules/network/service.py`:
  `9995b5d45d8fb96145eb2bc1f4ee75d49102999e50f27fb71adc8452950591d4`

Actual mounted HTTP auth, spatial reload/conflict/tenant denial, immutable history
and restore to revision3, private non-root CAS upload/reload/binary download/tenant
denial, real Redis outage/worker retry, stable post-XADD replay, audit dedup,
persistence restart and logout all passed. Inventory retained6 stream entries,
5 distinct events and5 audit rows. The unchanged14-case campaign verifies integrated
compatibility; targeted crash/race behavior is covered separately by regressions.

```sh
poetry run pytest tests/unit/test_asset_storage.py tests/unit/test_asset_service.py \
  tests/unit/test_network_schemas.py tests/unit/test_network_service.py \
  tests/integration/test_asset_endpoints.py tests/integration/test_network_endpoints.py \
  tests/unit/test_verify_measured_twin.py --no-cov -q
#181 passed in6.19s
poetry run ruff check scripts/verify_measured_twin.py tests/unit/test_verify_measured_twin.py
#All checks passed
```

This selection includes actual subprocess exit after link and fresh-store recovery,
unproven-alias preservation, and the unit final-response-read revocation check.
The asset owner's separate8 real-PostgreSQL regressions remain recorded in
[Assets.md](Assets.md); those opt-in cases were not rerun here. No verifier/test or
application/deployment source changes were needed for this refresh.

Cleanup: PostgreSQL18.6 PID**835766**, TCP**42075**; Redis7.4.10 loopback**41295**,
exact container`f33328d1bb2ff2a0b5d921f57d3dc57dc073f71592437e3297f32acc43584c88`,
name`nanfo-adr021-redis-dea543c213ef4e39b9a738711380f469` and its`-data` volume.
Exact processes/containers stopped gracefully and removed, owned volume removed,
private credentials/database/CAS tree removed, ports closed. Independent labelled
Docker listings found no verifier resources. No shared service/data was accessed.
Existing graph substitution, collecting websocket transport and local-only limits
remain; this does not qualify a rebuilt deployment image or backup/restore.

## Current0024 acceptance: PASS — both lanes complete, mismatch closed

After the parent's runtime-head/model-import integration, both unchanged verifier
lanes were rerun against fresh private services. **Both exited0/status`passed`:14/14
inventory/spatial/assets/outbox cases and8/8 measured-telemetry cases, no failures
or blockers.** Actual database and runtime `SCHEMA_HEAD` both equal0024; complete
repository migration chain and stable before/after source hashes confirmed.

Durable credential-free exact results are now stored in the repository:

| Lane | Durable result | Exact SHA-256 |
|---|---|---|
| Inventory, spatial history/restore, CAS, outbox | [inventory-result.json](IntegratedEvidence-0024/inventory-result.json) | `5c922ae9616d0678c840f442fb4fa7a2e1131d34a779671a174777755fb9a78e` |
| Measured SNMP, persistence/history/cursor, manager auth/revocation | [measured-result.json](IntegratedEvidence-0024/measured-result.json) | `ed035d60a51b67852e270d70e43210dbe7140413ab9d145c5c341d64b5ff3244` |

[checksums.json](IntegratedEvidence-0024/checksums.json) records exact hashes and
byte lengths (46347/48320). The export helper checked pinned original hashes,
passed statuses, runtime0024, all cleanup assertions and credential exclusion;
published without overwrite and verified exact-byte equality. No credentials,
tokens, configuration bodies, logs or database dumps were copied. Source manifests
and actual measurement/cleanup summaries survive deletion of temporary files.

Original results:
`/tmp/opencode/measured-twin-acceptance-19tb4_x0/result.json` and
`/tmp/opencode/measured-twin-acceptance-_tasizi5/result.json`.
Final runs completed2026-09-19 at**21:36:01.924Z** and**21:36:05.800Z**, respectively.

The full checks described in the historical0024 section below were repeated:
restore creates revision3 while1/2 remain unchanged; private UID1000 CAS bytes and
registration reload/download match; inventory6 entries/5 distinct events/5 audit
rows; measured17 unique events/17 records/19 entries including replays,18 authorized
metric frames,0 foreign metric frames,0 GETs after actor revocation. Keyset history
returns all17 measurements in5 pages and denies tenant/filter/tampered cursor reuse.
Three actual SNMP reads remained baseline/measured/measured.

Final exact owned resources, all removed:

- Inventory PostgreSQL PID**748081**, port**42369**; Redis**60487**, container
  `86645bd99626b3b061d43699d26f21d96dde9bf58301de665aa0ddd701b3ef50`,
  `nanfo-adr021-redis-7f832eef44294e4d9d247921fb2f1f80` and its`-data` volume.
- Measured PostgreSQL PID**748082**, port**46027**; Redis**42943**, container
  `e54e5b134db9e59b9dea2ab5e6ba12e472e56e80c4b81c96d1f3c816f28da7cc`,
  `nanfo-adr021-redis-1a5a42d0d05e4396ad5f3de0c71d3f91` and its`-data` volume;
  SNMP PID**749308**, UDP**59944**.

Both results confirm graceful stop/reaping, exact container/volume removal,
private credential/database/CAS/SNMP tree removal and released ports. Independent
label-filtered listings found no verifier-owned Docker resources. No verifier,
test, application or deployment code changed during this final rerun; only durable
evidence and this handoff were added/updated. Earlier182-test and lint gates remain
recorded below; the two live reruns are the new verification for parent alignment.

Scope remains local-service acceptance. Neo4j projection is substituted/unverified;
websocket transport is an explicitly collecting substitute with real manager/auth,
not live network sockets. No full Compose, physical calibration or retention
execution claim is added. Prior mismatch runs below remain historical evidence.

## Historical0024 acceptance before alignment:22 functional cases passed, partial status

Both integrated lanes now use the **actual complete repository migration chain
through0024**, with a sole-head assertion. The copied/truncated0021 migration path
has been removed. Fresh PostgreSQL18.6 and exact-image Redis7.4.10 instances ran
in separate owned labs; the measured lane also used a private local SNMP agent.

**14/14 inventory/spatial/assets/outbox cases and8/8 measured-telemetry cases
passed.** Both verifier commands correctly exited2/status`partial` because the
parent runtime still advertised`SCHEMA_HEAD="0021"` at execution. Recorded blocker:
`parent_runtime_schema_head_mismatch`. The actual installed database revision was
0024 in both labs; service assertions were not relaxed to accept0021. Parent must
complete `backend/app/core/runtime_health.py` alignment to0024. This workstream did
not modify that file or any deployment/shared source. No other runtime regression
was observed in these cases. Both source manifests were stable during execution.

### Commands and new live results

```sh
# backend/; each command owns distinct ports, cluster, container and volume
poetry run python -m scripts.verify_measured_twin --live \
  --redis-image-id sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
poetry run python -m scripts.verify_measured_twin --live --measured-snmp \
  --redis-image-id sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
```

| New/current-schema check | Actual result |
|---|---|
| Complete0001–0024 chain | **PASS twice**, real repository env.py; sole Alembic head0024; no revision copying/truncation |
| Spatial history GET/detail | **PASS** — first history contains revision1; detail equals original saved scene; foreign tenant list/detail403 |
| Historical restore | **PASS** — change placement to revision2, restore revision1 body with current expected revision2 → **new revision3**; fresh scene GET equals restored body; revision1 and2 detail bodies remain unchanged; history ordered3,2,1 |
| Private non-root asset CAS | **PASS** — API process UID1000, new0700 root supplied via`NETWORK_ASSET_ROOT`; registered87-byte minimal glTF metadata fixture uploaded through actual API, stored`local_cas`, registration preserved on fresh list; verified binary download exactly matches; foreign list/download403 |
| Telemetry keyset traversal | **PASS** — actual measured17 rows traversed in5 pages of size4; stable upper tuple; descending observed_at/record_id order; every expected event exactly once |
| Cross-tenant cursor reuse | **PASS** — requesting owner network with foreign token403; replaying cursor under foreign actor's own authorized workspace400 |
| Cursor filter/tamper | **PASS** — changed metric with original cursor400; modified token400 |

All prior inventory publication, actual auth/spatial409, Redis outage/retry,
byte-stable post-XADD replay, actual audit dedup, Redis restart and logout cases
were rerun in the14-case lane. It retained6 stream entries/5 unique events/5 audit
rows. The measured8-case lane reran real guarded helper→SNMPv3→Redis→consumer→DB,
both authorized ordinary history endpoints/tenant403, manager delivery, persistence
replay and actor revocation before the next GET. It again retained17 unique events,
17 persisted rows,19 entries including2 replays,18 authorized metric frames,
0 foreign metric frames and0 extra GETs after revocation.

Measured loopback RX/TX counters were679580666→680058523→680315828 octets;
intervals6.26s/6.35s yielded610679.8722044729/324163.77952755906bps per direction.
They include concurrent local lab traffic. Nominal agent capacity10Mbps is not
physical calibration. Websocket remains the actual manager/auth with a collecting
transport substitute, not network sockets. The asset body is a storage-only fixture,
not a frontend rendering/physical model acceptance. Graph projection remains
substituted in inventory consumption and unverified.

### Exact resources, cleanup and retained evidence

Inventory lane UTC21:28:46.313–21:28:59.265:

- PostgreSQL PID735535/port54915; Redis127.0.0.1:41249.
- Container`33e345ad12b951db0b816d88197bf567a3f6fac4dec5a4c7028bead79b086e84`.
- Name`nanfo-adr021-redis-179e967b0c534255ab1835c16c6d168e`, owned volume suffix`-data`.
- `/tmp/opencode/measured-twin-acceptance-6haeu097/result.json`
- **SHA256`84a5ee937d2422befd47cde97ffc820a9a35f79645fad9b34a87af5d420d4f87`**.
- Asset SHA256`2b89d5d19db835f4d47e1f08e4ebac5dcb715f8c85d1a33d2968347567b3170c`.

Measured lane UTC21:28:46.316–21:29:07.262:

- PostgreSQL PID735536/port35601; Redis127.0.0.1:43471; SNMP PID736155/UDP47906.
- Container`dcc13037dc1bc223f0b562a1e793adc42801477c1c37db1fe9c2820a5121d59f`.
- Name`nanfo-adr021-redis-129acb041ce844ecb08c21730dec7e50`, owned volume suffix`-data`.
- `/tmp/opencode/measured-twin-acceptance-gcrqcnfq/result.json`
- **SHA256`0e280e27a4a38d35a20c587b5d3a8a19fc3187fb1c6a58b9ee2f295796ae8f15`**.
- Traversed measured records SHA256
  `ec02ce4e72a837f48cc8da699f7b8e9a6b651380c1fb529cd5c88d9a6ee9afba`.

All cleanup fields passed in both results: exact processes gracefully stopped/reaped,
exact owned containers and labelled volumes removed, private CAS/database/SNMP/
credential trees removed, TCP ports closed and SNMP UDP released. Independent
label-filtered Docker listings returned no verifier containers/volumes; `ps` found
none of these three PIDs, and `ss` found none of the five assigned listeners.
No shared data/listener, deployment, system service, frontend fixture or other lab
was modified. Existing exact local Redis image only; no pulls/builds.

### Verification

```sh
poetry run pytest tests/unit/test_verify_measured_twin.py \
  tests/unit/test_measured_snmp.py tests/unit/test_snmp_composition.py \
  tests/unit/test_telemetry_lifecycle.py tests/integration/test_telemetry_endpoints.py --no-cov -q
#182 passed in4.56s
poetry run ruff check scripts/verify_measured_twin.py tests/unit/test_verify_measured_twin.py
#All checks passed
```

The verifier now rejects a changed/ambiguous migration head rather than silently
copying a subset; a regression test verifies actual0024→0023→0022→0021 ancestry.
Parent runtime-head alignment is explicitly reported and prevents a green overall
status while allowing useful functional evidence. Reexecute after parent alignment
to refresh final integrated status/source hashes. These checks do not exercise
evidence-pin lifecycle/retention execution or replace full Compose/backup/physical
acceptance.

## Historical0021 continuation: actual measured SNMP owner-to-history pipeline

**Seven measured-pipeline cases passed**, using a fresh schema0021 PostgreSQL18.6
cluster, a newly owned Redis7.4.10 container and private foreground Net-SNMP agent.
This adds actual measurement/publication evidence to the earlier twelve-case
inventory/spatial/outbox campaign below; they are separate runs with separate
source manifests. No application/shared source changes were made by this workstream.

```sh
# backend/
poetry run python -m scripts.verify_measured_twin --live --measured-snmp \
  --redis-image-id sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
# exit0;7 passed,0 blocked,0 failed
```

### Schema compatibility and actual scope

`--measured-snmp` now selects a distinct lane: migration0021, real owner inventory
setup and the five measured-pipeline cases. The verifier copies unchanged revision
files0001–0021 plus the actual Alembic env into its private migration directory,
then upgrades explicitly to0021. Concurrent0022–0024 files are never traversed or
applied, even when their down-revision chain is incomplete. The result includes
hashes of all visible source, including newer files, but that does not imply those
migrations ran. Source hashes were unchanged during the successful campaign.

An initial attempt retained as
`/tmp/opencode/measured-twin-acceptance-69wtefzw/result.json`
(`f673de67026cdef6c157740950c4613f5ea1b8645f3743d89373b2b83bff09ba`)
passed migration/inventory then failed with`ProgrammingError`: concurrently updated
spatial replacement began writing revision history requiring0022. All its resources
were removed. The measured continuation excludes those unrelated spatial writes;
it does not patch/skip their new persistence or silently apply later migrations.
**Parent handoff:** current spatial-history service requires0022; earlier spatial
acceptance is for its recorded source revision. Telemetry ingestion, consumer,
ordinary page-based history and websocket authorization **did run successfully
against0021 with the recorded current sources**. No0024 evidence-pin, retention or
cursor-mode acceptance is claimed.

### Real protocol, authority and persistence results

Campaign UTC: **2026-09-19T21:20:07.971Z–21:20:32.532Z**.

| Check | Actual result |
|---|---|
| Migration / owner inventory | **PASS** — exact schema0021, real active identities/roles/memberships; actual authenticated app.main network/device POST routes provision a device at127.0.0.1; owning Organization service resolves its org/workspace |
| Guarded measured helper | **PASS** — protected0600 binding pins actual actor/org/workspace/network/device, unique sysName and observed`lo`/ifIndex1; actual `build_measured_snmp_poll_action`, `SNMPOwnerBoundary`, adapter, ingestion publisher and NetSNMP subprocess/parser run without authorization substitution |
| Actual measurements | **PASS** — three real SNMPv3 authPriv GETs, SHA-256/AES; baseline followed by two measured intervals; exact integer counter tags independently reconstruct all four RX/TX rate samples |
| Real bus/persistence | **PASS** — actual Redis Streams loop,`TELEMETRY_HANDLERS` and `TelemetryPersistenceService`;17 unique events produce17 PostgreSQL records; initial drain has zero pending/dead-letter entries |
| Durable replay | **PASS** — remove one real handler completion marker and append the identical measured envelope again; consumer executes owning idempotency path, row count remains17; a second replay after revocation likewise leaves17 rows |
| Actual authorized history | **PASS** — `/api/v1/telemetry/history?network_id=…` and `/api/v1/telemetry/device/{id}` return17 rows; persisted IDs, metrics, values, units, identities, source and all provenance tags match actual published envelopes; both foreign-tenant requests return403 |
| Actual websocket manager | **PASS, collecting transport substitute** — actual singleton manager, queue and per-delivery `authorized_workspaces` reload real JWT/session/Identity/Organization/Network state;17 owner metric frames plus one legitimate replay; foreign actor gets zero metric frames and close1008 |
| Revocation before next GET | **PASS** — committed `User.is_active=false` in owned Identity table; next real guarded action rejects, observation-only transport wrapper sees **zero additional GET calls**, Redis stream length unchanged; history returns401 |
| Existing connection revocation | **PASS** — replay an already measured envelope after actor revocation; actual manager denies delivery, emits unauthorized error and closes owner1008; no new metric frame or persisted row |

The observer wraps `NetSNMPTransport.get` solely to count attempts and record the
typed result **after calling its unmodified real implementation**. It never returns
fixtures, changes counters or replaces authority. Real Redis global initialization
is used for consumer health counters and websocket authorization; HTTP overrides
only provide the same real owned DB/Redis infrastructure. Real telemetry consumer
also invokes its existing alert-owner handler; no alert generation is claimed
(the existing measured-alert contract does not admit this source as an emulation
observation). No topology handler or Neo4j process is required for this telemetry
stream. Graph projection remains unverified.

### Observed counter evidence

| UTC GET completion | sysUpTime ticks | RX octets | TX octets | Interval | RX/TX bps |
|---|---:|---:|---:|---:|---:|
|21:20:16.897712|124|651170208|651170208|baseline|unavailable|
|21:20:23.207980|756|651399302|651399302|6.32s|289992.40506329114|
|21:20:29.832144|1418|651645493|651645493|6.62s|297511.78247734136|

EngineBoots1 and discontinuity0 throughout; total RX/TX growth **475285 octets per
direction**. Three baseline metrics followed by seven metrics per measured interval
give **17 events/records**. Each gap includes64×1024-byte datagrams between two
newly owned loopback sockets and a six-second sleep. The agent counters also
include PostgreSQL/Redis/SNMP and other local loopback traffic; these values are
not isolated generator goodput. Agent-reported10Mbps loopback speed is nominal
metadata, not measured physical link capacity or utilization calibration.

All records retain`source=measured_snmp`,`synthetic=false`, emulation environment,
SNMPv3/authPriv provenance, binding digest, real observed counters and rate quality.
The measurement origin is actual local protocol/counters, not a synthetic adapter.
The websocket substitute implements only send_text/close to collect manager output;
this is **not network-socket handshake, browser or websocket route acceptance**.

### Private resources and cleanup

- PostgreSQL PID**717400**, loopback TCP**52045**, private Unix socket directory;
  fresh generated SCRAM credentials, no existing cluster/data accessed.
- Redis exact container
  `90297b694961bdc54c382bf30d790afd03ac730a0adee9b337bc9db050a9e76a`,
  name`nanfo-adr021-redis-72783cf13d6f4645ae1befd5ef814519`,
  owned volume with suffix`-data`, host**127.0.0.1:45813**. Existing exact image
  above; no pull/build/shared mounts or app Docker socket.
- SNMP agent PID**717994**, **127.0.0.1:60110/UDP**, unique
  sysName`nanfo-pipeline-a02bacbc199e`. `/proc` owned-socket inode correlation
  confirmed the sole UDP listener`0100007F:EACE`. Agent argv/environment checked
  secret-free. `-f -C -c … -p … -Ln`, private HOME/config/persistence,077 child
  umask,0600 credentials/binding/bootstrap; read-only `rouser … priv -V measured`
  and narrow IF-MIB/sysName/engineBoots views. No SET, walk, discovery or external
  target. No agent restart/localized-key reuse was needed in this campaign.
- Actual consumer task cancelled/awaited; both manager subscriptions removed;
  clients/engine closed. Exact SNMP/PostgreSQL processes stopped gracefully and
  reaped, SNMP UDP rebound successfully, both TCP ports closed, exact labelled
  Redis container/volume removed and **entire private secret/state/data tree deleted**.
  Independent label-filtered Docker listings returned no verifier resources.

### Durable summary, hashes and tests

```text
/tmp/opencode/measured-twin-acceptance-t6wtf1ai/result.json
/tmp/opencode/measured-twin-acceptance-t6wtf1ai/result.sha256
result SHA256:8dc47d39004a308d8ecc6f9da3d42f08013e1e707be0f181143abdeb36c44fd5
measured envelopes SHA256:d4c2978979a308a31ebb85e4612fcd204cee23c14b62f91a070ad7cadc8ec1d7
authorized history SHA256:e77963bade5ae5fb6eaec6495af654f2508036942a654950a66b81b68e4c21d8
binding SHA256:901e8d1a4e4c08d971d38c166015e44cd485374099017403915a2410ee8d1fd4
```

Credential-free summary retains typed real counters, versions, exact source hashes,
17 unique published/persisted IDs counted,19 stream entries including two replays,
18 owner metric frames,0 foreign metric frames,3 real GET calls and0 after revocation.
Tokens, credentials and binding bodies are not retained. This report preserves the
outcome/measurements/hashes if temporary artifacts are removed.

```sh
poetry run pytest tests/unit/test_verify_measured_twin.py \
  tests/unit/test_measured_snmp.py tests/unit/test_snmp_composition.py --no-cov -q
#118 passed in3.32s
poetry run ruff check scripts/verify_measured_twin.py tests/unit/test_verify_measured_twin.py
#All checks passed
```

The new verifier tests additionally reject synthetic provenance/incorrect derived
rates and validate private read-only agent configuration, child umask and absence
of credentials in arguments/environment. Physical device/firmware compatibility,
independent capacity calibration, full application startup/Compose, real websocket
network transport, graph projection and current0024 lifecycle acceptance remain
separate gates. This run did not exercise telemetry partial-publish crash recovery;
the adapter's pending batch remains in-memory as documented.

## Earlier outcome: PASS for the scoped PostgreSQL/Redis/HTTP lane

**All12 live verifier cases passed on2026-09-19 after explicit authorization of
one new disposable Docker Redis.** This supersedes the Redis-blocked outcome below;
earlier attempts remain historical evidence. Graph projection, full Compose,
physical acceptance and live measured-SNMP publication remain unverified.

### Executed local campaign

```sh
# backend/ — exact image was inspected locally first; no pull/build performed
poetry run python -m scripts.verify_measured_twin --live \
  --redis-image-id sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2
# exit0, status passed,12 passed,0 blocked,0 failed
```

Observed stores: private host **PostgreSQL18.6**, new container **Redis7.4.10**
(existing local `redis:7-alpine` image, linux/amd64). Time:
**2026-09-19T19:42:11.495Z–19:42:21.727Z**. Source before/after hashes match.

| Previously blocked case | Actual integrated result |
|---|---|
| Authenticated mounted HTTP inventory | **PASS** — actual `app.main` routes via HTTP ASGI; wrong-password401, two genuine bcrypt/JWT/session logins, current DB identity/membership checks; create network/device and PATCH spatial reference; three new pending outbox rows, attempts0, no inline Network stream append |
| Spatial HTTP reload/conflict/tenant | **PASS** — unauthenticated401, initial revision0 GET, linked-device PUT revision1, identical fresh-session GET, stale PUT409/`SPATIAL_REVISION_CONFLICT`, foreign tenant GET/PUT403; scene unchanged and exactly one matching spatial audit |
| Actual Redis outage/worker retry | **PASS** — stop exact owned Redis container; real independent outbox worker exits nonzero, all five events remain pending and first row records attempt1/ConnectionError; same container restarted and subsequent worker succeeds |
| Post-XADD interruption | **PASS** — real append followed by deterministic cancellation before PostgreSQL acknowledgement; row remains leased/unpublished; after actual lease expiry the independent worker publishes the identical full stored envelope including event ID/timestamp |
| Actual consumer/audit replay | **PASS** — real Redis `run_consumer_loop` and actual Identity handler; six entries/five distinct event IDs, five audit rows, zero pending entries, zero dead letters; direct repeated handler delivery also leaves five audit rows |
| Redis persistence restart | **PASS** — graceful stop/start of exact container with its own AOF volume; exact stream IDs/fields and acknowledged pending-state retained |
| Logout denial | **PASS** — actual logout endpoint then same bearer token returns401 on spatial GET |

The five PostgreSQL cases in the earlier matrix were also rerun and passed in this
same campaign. Authentication/authorization was never mocked or overridden. The
only HTTP dependency overrides supplied actual owned PostgreSQL sessions and Redis.
ASGITransport still does not run the Neo4j-dependent lifespan. The actual-lifespan
measured-selector smoke remains separate offline evidence, described below.

**Topology substitution:** no new Neo4j instance was authorized or started. The
Redis consumer handler registry used a receipt recorder in place of graph work;
five unique receipts were observed. It checks dispatch/dedup only, not actual
topology projection or websocket fanout. Audit handling was real. Neither fixture
coordinates nor this Redis integration establishes physical measurement fidelity.

### Isolation and exact cleanup

The new `--redis-image-id` option accepts only an exact sha256 image ID and always
uses `docker create --pull=never`. It does not accept an external Redis URL or any
shared port. Each invocation generates its own UUID name/owner label and labelled
data volume, validates image/label/mount/loopback port binding, copies a generated
0600 password config into that new volume and starts the exact recorded ID.
Application settings are generated privately in memory; the app gets no Docker
socket or shared mounts. Container command/environment contain no password.
Redis stdout has Docker log driver`none`; no credential-bearing logs are retained.
The container uses a read-only root filesystem, resource limits, no-new-privileges,
all capabilities dropped except`DAC_OVERRIDE`, and root UID to read the copied
0600 config/write the owned volume. This is lab provisioning, not a deployment
least-privilege claim. Readiness requires an actual authenticated Redis PING,
rather than merely observing Docker's port-forward listener.

Successful run resources:

```text
PostgreSQL: PID321336,127.0.0.1:52915 and private0700 Unix socket directory
Redis host binding:127.0.0.1:37841
Container ID:c30d32ab4c89031ddbc647a685fbec5f9fd1029b3b78ae78506cb856cd45c1f4
Container name:nanfo-adr021-redis-a039287ec0db4d12a999e78da8d4a3e9
Volume:nanfo-adr021-redis-a039287ec0db4d12a999e78da8d4a3e9-data
Owner label:org.nanfo.adr021.acceptance=a039287ec0db4d12a999e78da8d4a3e9
```

All final cleanup assertions passed: graceful PostgreSQL/Redis stop, exact child
reaped, exact container removed, exact labelled volume removed, private
password/config/database tree removed, both selected ports closed. Independent
label-filtered container and volume listings returned **no resources** from this
verifier. Every earlier failed Docker attempt's own container/volume/tree was also
removed. No shared listener/data was accessed, image pulled, Compose build launched,
system service changed or other agent lab operated.

### Retained credential-free evidence and checks

```text
/tmp/opencode/measured-twin-acceptance-g0ehl0_2/result.json
/tmp/opencode/measured-twin-acceptance-g0ehl0_2/result.sha256
result SHA256:8537ba6c4a33bea4ee57b114a2be8e747ca59796cc30376033b7d8321c478a9a
stream envelopes SHA256:dd56be62033fa3890ba4d73645ed206aa4d524c57d1963876fb5dae6fcf17ecf
HTTP scene SHA256:4d0fb21a54c4f54b947c4168a373cbd18f1a88d765e39302f1c2a68a5526c48f
```

The result retains exact source hashes, versions, resource IDs, counters and
cleanup assertions. This durable handoff retains its digest/outcome without
credential values. Scoped Ruff passed; verifier/startup plus existing measured
composition tests: **50 passed in2.48s** (16 verifier/startup,34 composition).
Added tests reject image tags/external addresses, deny foreign-label stop,
check no-secret/no-shared-mount container arguments and authenticated readiness,
and verify cleanup selects only exact owned IDs/volume, never prune/force.

Earlier Docker attempts are preserved under `/tmp/opencode/`:

| Directory suffix (`measured-twin-acceptance-…`) | Actual outcome | result.json SHA256 |
|---|---|---|
| `3jvi8wuv` | Config copy into read-only root failed; moved config to the newly owned data volume | `fc76631556915c503795b6f9322d4627e9c45a9bb16a36302d9178b2c90cfaa9` |
| `x4uwq07a` | Redis exited during startup; cleanup complete, non-graceful startup failure retained | `62ef51e25e8ada4c153aab514f07a0989f5ec396548ea384c366678a947b871c` |
| `ldp2g7fz` | Redis startup exit1 persisted after changing log destination | `926c786b5c9394bb2e2379d2dc1f0916c37884a1e8858961f342bcb324a871fd` |
| `fgvh6m_m` | Port-proxy readiness raced Redis exit; ConnectionError retained | `83d2bb496e7881d33a9c6e0166b18374dcf0e07f0c9351bef8d0eac27eaf96df` |
| `1ykpwiu0` | Attached startup diagnostic established config permission denial; retained ConnectionError; added explicit DAC capability and authenticated readiness | `3d7b4c84fdf8abc1d2aea44c2ae030a0b4323db468deed5e3b749867fd4c7da9` |

These were verifier provisioning defects. No parent application or deployment
source fix was required. Only the verifier, its tests and this handoff changed.
The XADD failure is an injected cancellation at a real append/acknowledgement
boundary; Redis availability interruption is an actual container stop/start.
Neither is claimed as host power-loss recovery or worker SIGKILL acceptance.

## Historical outcome before scoped Docker authorization: PARTIAL

**Five real PostgreSQL cases passed; seven Redis-dependent integrated cases are
blocked.** No full Compose, physical-network, live SNMP publication, Neo4j projection
or full application startup acceptance is claimed.

Read the current NetworkOutbox, SpatialBackend, MeasuredTelemetry,
DeliverySecurity and Deployment handoffs before execution. Parent source integration
was present: `app.main` mounts the spatial router and selects the measured helper;
`runtime_health.SCHEMA_HEAD == "0021"`, `WORKER_LOOPS["network"] == ("outbox",)`;
Alembic imports the Network outbox and spatial metadata.

### Environment blocker

PostgreSQL **18.6** is installed (`/usr/bin/initdb`, `/usr/bin/postgres`). Redis,
Valkey and Neo4j are **not installed as private host executables** in the searched
locations. Checked PATH, `/usr`, `/usr/local`, `/opt`, `/home/DHB`, `/tmp`, and the
package cache; `pacman -Q redis valkey neo4j` reports absent packages. No packages
were installed or downloaded. The existing Redis6379 and Neo4j7474/7687 listeners
belong to shared containers and were not used. No Docker operation was performed.

Consequently, authenticated HTTP acceptance cannot honestly pass: real login/session
checks require real Redis, and substituting it would violate this campaign's
contract. The verifier retains those cases as blocked and exits **2**, not success.

## Delivered ownership

- `backend/scripts/verify_measured_twin.py`: opt-in, self-provisioning local verifier.
- `backend/tests/unit/test_verify_measured_twin.py`: verifier isolation/failure tests
  and actual `app.main` lifespan measured-selector smoke.
- This acceptance report. No application, deployment, shared source, dependency,
  sprint or journal changes were made by this workstream.

The verifier generates new database, Redis and JWT credentials per run; boots only
its own private cluster/child processes; chooses distinct ephemeral high loopback
ports; uses SCRAM PostgreSQL authentication and a0700 Unix socket directory. Redis,
when available, uses a0600 config, password authentication and private AOF with
`appendfsync always`. Secrets never enter process arguments or retained evidence.
No supplied DSN or shared service address is accepted. Private child stdout/stderr
are discarded because driver/migration failures can include credentials. Failure
evidence retains fixed verifier codes or exception class names only.

### Actual live matrix

Final run: **2026-09-19 19:34:19.376–19:34:22.488 UTC**.

| Case | Actual result |
|---|---|
| Migration0021 | **PASS** — fresh real cluster, actual Alembic `env.py`, complete chain to0021; installed revision equals parent runtime head and worker registration matches |
| Inventory/outbox atomic path | **PASS** — actual Network/Device services, real Organization membership; network and device committed, two persisted envelopes, attempts0, publication timestamps null; no publisher/Redis on mutation path |
| Spatial save/reload/audit | **PASS** — typed scene linked to real created device, revision1 reload through fresh session; exactly one actual Identity audit row |
| Spatial conflict/tenant | **PASS (service boundary)** — stale write409, second real tenant write/read403; subsequent owner reload unchanged and audit count stays1 |
| Actual audit handler replay | **PASS (direct handler invocation)** — both real inventory envelopes passed twice to `handle_audit_event`; exactly two durable event-ID audit rows; no Redis consumer claim |
| Actual `app.main` HTTP login/inventory | **BLOCKED** — private Redis unavailable |
| HTTP spatial GET/PUT/reload/409/tenant403 | **BLOCKED** — same prerequisite; service checks above are not relabeled HTTP evidence |
| Redis outage/independent worker retry | **BLOCKED** |
| Real XADD interruption/retry/stable IDs | **BLOCKED** |
| Actual Redis bus/Identity audit dedup | **BLOCKED** |
| Redis AOF restart preservation | **BLOCKED** |
| Logout/session denial over HTTP | **BLOCKED** |
| Neo4j topology | **UNAVAILABLE / NOT EXERCISED**; future local Redis run explicitly uses a topology receipt substitute |

Fixture coordinates use `source=acceptance-fixture`, unknown accuracy. They are
neither measured spatial data nor physical calibration. Identity/Organization
repositories bootstrap the two local actors and workspaces; subject inventory and
spatial mutations execute real owning services. Audit direct replay does not mark
the inventory outbox published.

### Cleanup and evidence

Final private PostgreSQL port **32999**, exact owned PID **295666**. Redis port
**55635** was selected but no Redis process started. SIGTERM/await completed
gracefully; the entire freshly allocated private cluster/password/state tree was
removed. Both selected ports were confirmed closed, all exact child handles reaped.
An independent `ps -p` check found none of the four campaign PostgreSQL PIDs alive.
No process-name kill, system-service start/stop, shared database mutation or reused
cluster occurred.

Credential-free final evidence:

```text
/tmp/opencode/measured-twin-acceptance-7w4qsha5/result.json
/tmp/opencode/measured-twin-acceptance-7w4qsha5/result.sha256
SHA256 666cbb1001135aca2406bad6de3002a1a0820a39dc198c09653d3b4fedf02853
pending envelope summary SHA256
5acae2b3caccf700bfb985b0cc5b1f78ba67a567427fd4ceb91fdecc25426b05
```

Result contains before/after exact source hashes for application Python, migrations,
outbox worker, verifier and backend lock; **source_unchanged=true** during the run.
Hashes establish byte integrity, not deployment/image authenticity. This checked-in
report retains the outcome/digest if temporary evidence is later removed.

Earlier attempts remain retained, with their private service trees also removed:

| Evidence directory under `/tmp/opencode/` | Outcome / correction | result.json SHA256 |
|---|---|---|
| `measured-twin-acceptance-8rrbxrcr` | Verifier migration invocation failed: repository has no `alembic.ini`; corrected to Config/script_location + actual env.py | `f1a0778f6a72803f1d4b925908628b867378a0dc7c377a3c4d1901d5ac64f937` |
| `measured-twin-acceptance-b3713sln` | Three PostgreSQL cases passed; Redis blocked | `683268b0c9d6cec4f84228e014db262b847ff94a8df938da7e825c5c9e794878` |
| `measured-twin-acceptance-9ylxogn3` | Four PostgreSQL cases passed, verifier direct audit replay hit detached ORM row after scene service expiration; corrected by snapshotting envelopes while session remains open | `9435e2632a72381fce9f75742bf85054a1c2c08bcf31621f648d263074f96d90` |

Both failures were verifier defects, not parent application bugs. No parent source
fix was required by the executed cases.

## Startup wiring smoke and scoped tests

```sh
# backend/
poetry run pytest tests/unit/test_verify_measured_twin.py \
  tests/unit/test_snmp_composition.py --no-cov -q
# 43 passed in2.39s (9 verifier/startup,34 existing composition)

poetry run ruff check scripts/verify_measured_twin.py \
  tests/unit/test_verify_measured_twin.py
# All checks passed
```

The startup tests enter **`app.main.app.router.lifespan_context`**, select normalized
`measured_snmp`, substitute the build helper only in tests, run the actual collector
loop/action and assert the configured cadence, retry arguments and same ingestion
instance/session factory/Redis passed to the helper. Both legacy factory and generic
poll wrapper raise if accidentally reached. Shutdown stops the actual collector and
reaps background tasks. RuntimeError/ValueError build failures leave the collector
unavailable, stop it and never select a demo fallback. Redis/Neo4j/lease infrastructure
is explicitly substituted for this offline smoke. It proves composition, not a
physical GET, owner-authorized measured publication or real startup dependencies.

Verifier tests additionally cover explicit live opt-in, newly generated isolated
configuration,0600/no-clobber secret writes, environment restoration on failure,
exact-handle cleanup with unrelated-tree preservation, bounded kill escalation,
canonical hashes and credential-canary exclusion from retained failure evidence.

## Historical resume plan (executed above using the authorized Docker option)

Provide an installed trusted standalone Redis executable (Redis7+ commands are
required), then run from `backend/`:

```sh
poetry run python -m scripts.verify_measured_twin --live \
  --redis-server /absolute/path/to/redis-server
```

This command's Redis-dependent branch is implemented but **has not been live
validated here**. It authenticates by actual `/api/v1/auth/login`, uses the actual
mounted `app.main` routes through HTTP ASGI and overrides only DB/Redis dependencies
with the new real local stores. It checks401/403/409, fresh-session reload and
unchanged state/audit on denied writes. ASGITransport does not start the Neo4j-bound
lifespan; the distinct smoke above is the only startup evidence.

The live publisher branch stops its exact Redis child, runs the real independent
`run_network_outbox_worker --once` and checks deferred pending rows. After restart,
a narrow XADD wrapper performs the **real Redis append** then injects cancellation
before PostgreSQL acknowledgement; lease expiry and the real worker must replay
the identical event ID, timestamp and complete envelope. Six stream entries must
represent five distinct inventory events. Real `run_consumer_loop` and Identity
audit handler must deduplicate; the only consumer substitute is an explicitly
labeled topology receipt recorder because no private Neo4j exists. It finally
checks durable audit replay, Redis AOF restart, session logout denial, worker
heartbeat and exact cleanup. This deterministic boundary interruption is not a
worker SIGKILL or a physical failure claim.

Remaining release gates include private Redis execution above, real Neo4j projection,
measured SNMP owner-authorized ingestion/persistence, actual full startup, deployed
runtime-role grants, source-matched Compose/image/backup-restore acceptance and
physical calibration. The PostgreSQL owner-role lab does not certify deployment
least-privilege grants or Redis durability under host power loss.
