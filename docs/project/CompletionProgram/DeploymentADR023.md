# ADR023 deployment integration handoff

## Current receiver-health9–11 final release (2026-09-20)

Supersedes earlier image pins below; all previous evidence remains historical and
unchanged. **Distributed29passed/0failed/4blocked**, deployment216passed, focused
receiver-client regressions31passed, installed-image smoke20passed. Schema0027;
snapshot `nanfo-adr023-frozen-yvofvp9n`; zero source drift;329 installed runtime Python
files match UID10001. Full archive/assets/history/backup/fresh-restore and failover
acceptance passed again after exact0600 health-key admission, post-GET/TTL age check,
full client-config identity and privileged driver import separation fixes.

**Current backend:** `sha256:1e81845557780d170ad945929e3a993f8050660e1b5f658fc859a30c5fa9b053`.
**Current fleet:** `sha256:fac6029493690c0d60ee44117a393091aaa019b7dc579ac8784f2d86599007df`.
Gateway/Neo4j/store image IDs unchanged. Current immutable evidence set is
`DeploymentEvidence-ADR023-20260920/health-final-*`; narrative index:
`LATEST-HEALTH-FINAL.md`. Prior full fleet functional6/6 is reused with exact
snapshot diff:103 fleet/telemetry/Identity/Network/Organization/core/DB/event/CLI/
packaging inputs unchanged, including SNMP transport and pinned packages. No new
physical qualification, trusted config installation or default activation.

Installed smoke verifies real key reader success at0600 and refusal at0644/0640/
0400, hardlink and wrong digest, plus default/partial/missing provider configuration
in production/emulation. No privileged driver module is imported and the client has
no run/driver. No mocked calibration is installed. All campaign resources removed,
shared services untouched; caches and prior exact evidence retained.

## Latest journal-client release acceptance (2026-09-20)

**Deployment216passed; latest distributed29passed/0failed/4blocked**, schema0027,
zero source drift from snapshot `nanfo-adr023-frozen-0bco__84`. Backend/fleet rebuilt
from final journal-client/settings/receiver-health source; locked dependencies cached,
327 installed runtime Python files matched as UID10001. Optional provider overlay
is explicit-only. Full distributed/core/nonempty-archive/assets/history cold restore
passed with default-unconfigured provider availability. Six additional installed-image
factory cases confirmed safe defaults and fail-closed partial/missing configuration
in production/emulation. Authentic calibrated provider/receiver remains uninstalled.

Latest backend: `sha256:e75fa2bdc7f1c0b6c646e0bc0514bed2c808dca268655e4340b2b9b62e504282`.
Latest fleet: `sha256:13be46a557ecb7ea22d6d7f0de2e0792b68b44db3021cf1df99ee4971d509702`.
Gateway/Neo4j/store IDs are unchanged. Current evidence index:
`DeploymentEvidence-ADR023-20260920/LATEST-JOURNAL-CLIENT.md`; immutable appended
`journal-*` matrices, image IDs, source hashes, authenticated checkpoint, checksum
catalog and verified portable evidence archive. All earlier exact evidence remains.
No shared resources mutated, privileged receiver launched or physical qualification
claimed. Prior fleet collection acceptance remains scoped to its prior image; this
release checks package/source parity without relabeling that prior campaign.

## Optional journal-only provider overlay

`compose.autonomous-client.yaml` adds only protected read-only binds and the exact
`NANFO_AUTONOMOUS_PROVIDER_CONFIG` / `NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256`
settings to **api and autonomy-worker**. For two APIs also append
`compose.distributed-autonomous-client.yaml` to configure api2 identically. This is
separate from live-AI configuration and can be combined with its overlays. Base
Compose has no provider setting/mount and retains unavailable provider defaults.
The overlay does not change execution mode, service commands, capabilities or image.
There is no receiver service, namespace mount, privileged driver or receiver loop
in API/AutonomyWorker; the client stages journal work/readback/cancellation only.

Operator installation paths:

- `$NANFO_STATE_DIR/autonomous-config/provider.json` →
  `/var/lib/nanfo/autonomous-config/provider.json` (config byte hash required).
- `$NANFO_STATE_DIR/autonomous-evidence` → `/var/lib/nanfo/autonomous-evidence`;
  set config `evidence_root` to this path. Contains authentic calibration/provider/
  runtime evidence and the independently random >=32-byte HMAC `health_key` artifact.
- `$NANFO_STATE_DIR/autonomous-source` → `/var/lib/nanfo/autonomous-source`;
  set config `source_root` to this path. Install the exact independently reviewed
  receiver/instrument source layout; never substitute a mutable working tree.

Provision directories owned/readable by10001,0700; files0600, no symlinks or writable
ancestors. No host path is auto-created. Mounts and settings contain no secret values;
the health key stays in the protected evidence directory, shared only with separately
admitted receiver identities. All three directories participate in encrypted external
directory backup when these overlays are selected. Pass the same full file list to
backup/restore. Freeze external producers during backup; never install test artifacts.

```bash
docker compose --env-file "$STATE/deployment.env" \
  -f deploy/compose.yaml -f deploy/compose.distributed.yaml \
  -f deploy/compose.autonomous-client.yaml \
  -f deploy/compose.distributed-autonomous-client.yaml config --quiet
```

The operator must explicitly configure `EXECUTION_MODE=emulation` and genuine
`nanfo.autonomous-provider-installation/v1` trust pins before clients can install.
Partial/invalid/production configuration fails closed. Receiver health must be fresh,
scope-matching, TTL-bound and HMAC-authenticated; its absence cannot create readiness.
No authentic installation is available in this campaign, so optional provider
actuation remains unavailable and no physical qualification is claimed.

## Corrected-source final acceptance (2026-09-20)

Supersedes the fleet blocker in the earlier live update below. Snapshot
`nanfo-adr023-frozen-sufx7teb` includes the Net-SNMP private0700 `cert_indexes` fix
(stderr still fatal) and final FRR authority source. **Final distributed29passed/
0failed/4blocked**, zero source drift, schema0027, all archive/assets/history and
backup/fresh-restore gates repeated against the corrected backend image. Original
singleton core evidence remains scoped to its original image; no redundant singleton
campaign was run. No live FRR mutation, model qualification or training was launched.

Packaged SHA-256/AES private SNMP acceptance: **1passed/0failed**. Full packaged fleet
CLI acceptance: **6passed/0failed/0blocked**, real private PostgreSQL/Redis at0027,
two valid loopback agents and bad third identity,12 persisted measured records,
deduplication, degraded/healthy heartbeat, SIGSTOP staleness, SIGKILL/restart and actor
revocation. This proves worker CLI plus explicit owning persistence, not end-to-end
API consumer/socket delivery, ambiguous-ack crash timing or physical-device fidelity.
Acceptance-only derivative images add private snmpd/probe scripts; shipped fleet
application bytes are unchanged and324 runtime files match the frozen source.

Final backend: `sha256:312ac3ca2be31f79858c2f49d27c7aca410e04542978b7445b3d0e13f28899a4`.
Final fleet: `sha256:71b31676560195b54b5480507c71c857f064ebaa7cb3f0f793e2fcd8080c9e5a`.
Gateway/Neo4j/store image IDs remain in `final-images.json`.

New `final-*` and `corrected-*` evidence is appended under
`DeploymentEvidence-ADR023-20260920/`; the original records/checksums remain intact.
One corrected distributed attempt hit tmpfs EDQUOT during backup authentication
(19passed/2failed/12blocked). Three exact owned private backups/keys were copied to
ignored0700 `deploy/state/adr023-private-evidence`, hash-verified and authenticated
before removing their tmpfs copies. The same source/images then passed the complete
distributed campaign. No shared resources or other agents' files were removed.
All newly owned containers/networks/volumes were cleaned; package caches retained.

## Authorized live campaign update (2026-09-20)

Final frozen-source **core28passed/0failed/5blocked**, **distributed29passed/0failed/
4blocked** at schema0027. Actual nonempty archive deletion and exact bytes/receipt/
pin/tombstone cold restore passed with eleven volumes, assets/registration/history,
old-session denial and distributed leader takeover. All owned campaign resources
were cleaned; shared services and earlier evidence were preserved.

Durable matrices, image IDs, source hashes, authenticated checkpoints, build logs,
failed attempts and verified evidence archives:
`DeploymentEvidence-ADR023-20260920/README.md`.

Optional fleet image built with exact pinned Net-SNMP packages, but packaged transport
acceptance **failed**: Debian's fresh-request `cert_indexes` creation message reaches
stderr and the backend transport rejects it despite successful SNMP output. Fleet
runtime admission stays blocked pending the owning transport fix and a focused
source-matched rebuild/retest. No physical collection, privileged FRR, fake model
qualification or autonomy activation was performed. The initial source-only record
below remains historical; this update records the subsequently authorized campaign.

## Scope and status

Deployment source integration at **schema0027**. Inputs: DistributedRealtime,
RetentionComplete, Fleet, AutonomousExecution and ContinuousAI handoffs plus ADR023.
Backend `main`, config, readiness and runtime-health belong to the distributed/parent
owners; this work does not edit them. Existing evidence directories, build records
and historical matrices are retained. No build, pull, container launch, migration,
training, live collection or shared-service mutation was performed for this handoff.

### Delivered

- Fresh initializer migrates to the parent's `SCHEMA_HEAD`0027 and verifies runtime
  grants for all0025/0026/0027 tables. Current lifecycle markers, adoption and verifier
  require0027. Historical0019/0021/0024 backup validation/export remains available;
  historical images cannot be silently adopted as this release.
- Eleven owned volumes, including **telemetry_archive**: fresh0700 directory owned
  by10001; only explicit retention jobs mount it writable, maintenance mounts it
  read-only. No API needs archive write access. Cold all-volume backup includes bytes
  together with PostgreSQL receipts/tombstones/pins. Bounded maintenance validates
  every receipt's bytes/checksum/identity and hashes receipts, permanent tombstones,
  pins, coverage and reconciliation. Restore compares that proof before session
  invalidation/resume. Checkpoint cap is10000 rows per table and overall120s; exceeding
  a bound refuses rather than silently truncating. Orphan bytes are retained/backed.
- Maintenance blocks **every unreleased autonomous execution**, including verified
  policies, stale leases and uncertain recovery. It never clears execution fences.
  Admissions include api2 when present; backup stops all configured writers, including
  fleet/retention, before cold archive. Restore still starts stores only.
- `telemetry-retention` is a one-shot **retention profile**, with no automatic start,
  scheduler or age threshold. Its deployment wrapper uses the existing owner CLI and
  secret-derived runtime DSN. Explicit workspace/time window/operation required;
  archive path fixed to the private volume for apply/restore. Owner CLI enforces31-day
  windows, finite batches and pin/coverage guards. Pre-enrollment, unknown historical,
  backfilled and ever-pinned records remain retained. Deployment never auto-enrolls
  owners or deletes old history.
- Optional **fleet** overlay/profile uses an independent `with-fleet` image;
  API `TELEMETRY_FLEET_ENABLED=true` and adapter `stub` disable local polling while
  retaining domain consumers. Read-only non-autocreated binding/credential directory
  mounts, private tmpfs, fixed UID10001, no capabilities/host ports. Only the fleet
  service joins the additional outbound network for explicitly installed SNMP targets.
  Direct project PostgreSQL retains advisory-session semantics. Worker command is the
  existing `python -m scripts.run_fleet_collector`.
- Fleet health CLI `deploy/check_fleet_health.py` reads existing Redis fleet health
  keys plus schema/DB/Redis checks; it never starts a collection sweep. Bounded16 scans,
  256keys,256KiB/value,5s budget; all manifest devices must have fresh acknowledged
  publications and fresh worker heartbeat. Missing/stale/malformed remains unavailable.
  Health aggregates configured fleet coverage; it is not proof that this particular
  replica owns a device, nor downstream persisted ingestion. API readiness still
  reports fleet capability `external_unverified` per the distributed owner's contract.
- Net-SNMP **5.9.3+dfsg-2+deb12u1** and matching libraries pinned from actually
  inspected Debian snapshot metadata. Signed repository locations, release date and
  index/package hashes: `deploy/NETSNMP.md`. Fleet target intentionally amd64. APT
  signature verification remains enabled. Image/SHA-256+AES execution gates pending.
- Optional **distributed** overlay starts api+api2 in distributed mode, one Uvicorn
  worker each, shared stores/report/assets/binding/lab volumes, no extra public port.
  Gateway uses least-connections upstream, bounded failure marking and Docker DNS
  re-resolution (including container recreation); existing safe logging/CSP/WS upgrade
  handling remains. Gateway waits for both APIs' `/ready`. The verifier only accepts
  `api_consumers=delegated` for a fresh distributed follower with zero local consumers
  and no collector. `--distributed` adds leader-stop/follower-promotion/gateway/rejoin
  acceptance and includes api2 in restart/backup/restore ownership.
- Optional **live-ai** overlay installs the same protected hash-pinned registry,
  read-only model/evidence and actual observation roots on API and autonomy-worker,
  using the independent `with-ai` interpreter. Distributed supplemental overlay installs
  the identical configuration on api2. No sample registry, checkpoint, observations,
  calibration or driver is generated. Default safety/executor remain unavailable.

## Composition rules

Base `manage.py` lifecycle is the singleton package. Optional compositions use explicit
Compose file lists consistently for start, stop, backup and restore; do not use the
base-only lifecycle against an overlaid project. Render before admission:

```bash
docker compose --env-file "$STATE/deployment.env" \
  -f deploy/compose.yaml -f deploy/compose.distributed.yaml config --quiet

# Both fleet and distributed: final supplemental overlay is required for api2.
docker compose --env-file "$STATE/deployment.env" \
  -f deploy/compose.yaml -f deploy/compose.distributed.yaml \
  -f deploy/compose.fleet.yaml -f deploy/compose.distributed-fleet.yaml \
  --profile fleet config --quiet
```

Set `NANFO_FLEET_IMAGE` to the admitted source-matched image ID. Manifest paths use
`/var/lib/nanfo/fleet/manifest.json`, bindings inside that root, and credentials under
`/var/lib/nanfo/fleet-credentials`. Provision existing directories root/10001-owned,
not group/world writable; files0600 owned/readable by10001 (root-only0600 is not
readable by the nonroot worker). Mounts never create missing configuration directories.
Provision actual write-authorized actor/device bindings per Fleet.md. Freeze host
producers during backup; external protected directories are encrypted backup inputs.
Restart workers after replacing the manifest. Never run legacy measured_snmp polling
for the fleet's devices. Runtime profile is explicit, e.g. `--profile fleet up -d
--no-build fleet-worker` only after migration and binding admission.

For continuous recommendations add `compose.live-ai.yaml`; with distributed serving
also add `compose.distributed-live-ai.yaml` last. Provide `NANFO_AI_IMAGE` and
`NANFO_LIVE_MODEL_REGISTRY_SHA256`; missing/partial installation blocks providers.
Do not combine this with the historical `compose.ai.yaml` diagnostic registry without
an explicit combined installation review. `verify.py --model` retains its historical
singleton diagnostic campaign; it is not the live-provider acceptance command.

**Calibrated autonomy remains blocked:** no authentic installation/causal safety
frames, attested baseline or matching-runtime execution qualification was supplied.
Linux/FRR historical model qualification does not authorize OVS dispatch. The admitted
`compose_autonomous_lab` interface requires an already running owned lab, real driver,
independently validated calibration and disabled manual/experiment controllers.
There is no environment boolean that safely manufactures those prerequisites; no
privileged autonomous service is started by this package. Keep durable journals and
resource exclusion until actual exact compensation is verified.

## Explicit bounded retention policy / scheduled invocation

Use a scheduler-managed job with reviewed workspace, UTC start/end, fixed finite batch
and timeout bounds. Invoke one operation, record its output/continuation, then exit.
No ambient rolling historical cutoff is installed. Reconciliation must finish for all
five owners after all old unpinned writer binaries are drained. Unknown history stays.

```bash
# Repeat owner=report,intent,alert,simulation,autonomy until complete=true.
docker compose --env-file "$STATE/deployment.env" -f deploy/compose.yaml \
  --profile retention run --rm --no-deps telemetry-retention \
  python /opt/nanfo/deploy/telemetry_retention.py reconcile \
  --workspace-id "$WORKSPACE" --owner "$OWNER" --batch-size 100 --max-batches 10

# Safe scheduled assessment; reviewed fixed window <=31days, no deletion.
docker compose --env-file "$STATE/deployment.env" -f deploy/compose.yaml \
  --profile retention run --rm --no-deps telemetry-retention \
  python /opt/nanfo/deploy/telemetry_retention.py dry-run \
  --workspace-id "$WORKSPACE" --start-time "$START" --end-time "$END" \
  --batch-size 100 --max-batches 10 --timeout-seconds 30

# Only explicitly admitted apply jobs replace dry-run with apply above.
# --after is the prior JSON next_position for the SAME workspace/window.
docker compose --env-file "$STATE/deployment.env" -f deploy/compose.yaml \
  --profile retention run --rm --no-deps telemetry-retention \
  python /opt/nanfo/deploy/telemetry_retention.py restore \
  --workspace-id "$WORKSPACE" --record-id "$RECORD" --timeout-seconds 30
```

A backup must include archive bytes, DB receipts and permanent tombstones together.
Use `deploy/backup_restore.py backup|restore` with **every selected --compose-file**,
the appropriate source/target env file, separate protected encryption key, private
backup directory and distinct fresh target project. All-volume restore authenticates
archives and compares receipt proofs; no implicit migration or writer resume. Historical
0024 archives retain their ten-volume layout and require matching historical tooling.

## Required acceptance commands

Source-only gate (from repo root; use the existing backend environment, not host Python):

```bash
PY=/home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python
$PY -m pytest deploy/tests deploy/test_lifecycle.py -q
git diff --check -- deploy docs/project/CompletionProgram/DeploymentADR023.md
```

After all core integration owners are idle **and the parent explicitly authorizes**
the final source-matched campaign, use a new evidence directory/project (verifier
allocates UUID projects). Both commands below build/pull unless exact reuse evidence
is provided; neither has been executed in this workstream:

```bash
python deploy/verify.py --live --agents-idle --work-root /tmp/opencode
python deploy/verify.py --live --agents-idle --distributed --work-root /tmp/opencode
```

Required results:0027 fresh migration/runtime grants; all worker and per-API readiness;
one leader, delegated fresh follower; gateway takeover/rejoin; unchanged report/asset
bytes; eleven-volume encrypted backup/fresh restore with matching telemetry archive
checkpoint; old-token denial; exact owned-resource cleanup. Empty-archive package
acceptance does **not** prove nonempty telemetry archive/delete/restore races.

Additional owner acceptance (from `backend/`, disposable inputs only, parent-authorized):

```bash
RUN_DISTRIBUTED_REALTIME=1 poetry run pytest tests/integration/test_distributed_realtime_sockets.py --no-cov -q
RETENTION_TEST_DSN="$DISPOSABLE_PG_DSN" poetry run pytest tests/integration/test_retention_complete_postgres.py --no-cov -q
FLEET_TEST_DSN="$DISPOSABLE_PG_DSN" poetry run pytest tests/integration/test_fleet_postgres.py --no-cov -q
FLEET_TEST_DSN="$DISPOSABLE_PG_DSN" FLEET_TEST_REDIS_URL="$DISPOSABLE_REDIS_URL" FLEET_LOCAL_SNMP=1 \
  poetry run pytest tests/integration/test_fleet_local_snmp.py --no-cov -q
NANFO_LIVE_PROVIDER_POSTGRES=1 poetry run pytest tests/integration/test_live_provider_worker.py --no-cov -q
AUTONOMY_TEST_DSN="$DISPOSABLE_PG_DSN" poetry run pytest tests/integration/test_autonomous_execution_postgres.py --no-cov -q
```

Fleet image packaging after authorization (distinct fresh release tag; no retagging
earlier evidence): `python deploy/manage.py --state "$STATE" build --service backend
--with-fleet --image-tag "$NEW_FLEET_TAG"`. Record image ID, source hashes and
`dpkg-query -W snmp libsnmp40 libsnmp-base`; require all exact pinned versions and
`/usr/bin/snmpget --version`. In the isolated provisioned fleet stack run the shipped
health probe through `deploy/entrypoint.py`, observe actual SNMPv3 SHA-256/AES reads,
durable ingestion, crash/replay, stale heartbeat rejection and actor revocation.
Perform a nonempty post-enrollment archive plus ever-pinned control on that disposable
stack, cold backup/restore, exact archive-byte/receipt/tombstone comparison, scoped CLI
restore and old-event replay rejection. These are remaining live release gates, not
claims inferred from mock/source tests. No physical/calibrated autonomy acceptance is
possible without the authentic prerequisites above.

## Verification record

Source-only Compose rendering tested five combinations including both APIs+fleet+AI;
no Docker daemon mutation. Initial host-Python run lacked ReportLab; reran in the
existing backend environment. Corrected test fixture assumptions and retained earlier
evidence. Closing gate: **211 passed**, including five actual Compose CLI renderings
(no daemon required), archive tamper/scope/proof tests, historical0024 export,
all explicit retention operations, fleet freshness/scan bounds, delegated readiness
and both-API quiescence before recovery checks. Scoped Ruff and tracked whitespace
checks passed. No live/package build acceptance is claimed. Python3.14 dependency
deprecation warnings are unchanged.
