# ADR020 Deployment Package

## ADR-028 runtime contract — 2026-09-24 (current source)

Fresh builds from this source target schema **0030** (`backend/app/core/schema_version.py`;
`deploy/schema_contract.py` also reads the Alembic head, and `init`/fresh `start`/the
initializer refuse a contract that lags it). Sections below that describe 0027–0029 images,
builds or acceptance runs are historical records. This is a source/configuration change
verified by unit tests (`VALIDATION.md`); no new image, live deployment, backup/restore or
lab qualification is claimed.

**Services.** One API, six workers and three supervised core loops, plus the gateway and three
stores: `stream-retention` (C14 archive-before-delete of every domain stream and the DLQ into
the 0700 `stream_archive` volume; `python -m scripts.stream_retention schedule`),
`telemetry-retention` (archive-before-delete telemetry loop; its DSN is derived from the staged
runtime secrets) and `asset-gc` (runs `python -m app.modules.network.asset_gc` every
`NANFO_ASSET_GC_INTERVAL_SECONDS`, default 86400, on the API's asset volume; preview with
`run --rm asset-gc python -m app.modules.network.asset_gc --dry-run`). `deploy/supervise.py`
relays their output, writes a work-coupled heartbeat only after completed cycles, forwards
SIGTERM and returns the child's exit status. Every lifecycle service uses
`restart: unless-stopped`, so the backend watchdog's exit 70 and a retention refusal exit 3
restart the container; `manage.py autoheal` covers running-but-unhealthy containers
(`OPERATIONS.md`). `telemetry-retention-cli` (profile `retention`) keeps the finite operator
invocations (dry-run/restore/reconcile).

**Roles and secrets (C24).** Every backend service sets `APP_ENV=production` and an explicit
`NANFO_SERVICE_ROLE`. Only the API mounts `runtime_secrets_api` (JWT signing key and the
verify-only previous keys of a rotation); workers mount `runtime_secrets_worker`, and the
entrypoint refuses to start a worker that can see a JWT key. Redis disables `default`;
applications authenticate as `nanfo` (`+@all -@dangerous +info +client|setname +client|id`,
all keys and channels; `REDIS_USERNAME=nanfo`), rotation and healthchecks as `nanfo-admin`.
Only SHA-256 ACL hashes enter the generated Redis config. The Redis, Neo4j and gateway
entrypoints/configurations are baked into their images (`Dockerfile.redis`,
`Dockerfile.neo4j`, `Dockerfile.frontend`); no runtime file is bind-mounted from the checkout.

**Keys.** `init` also creates the C15 lab command key (`secrets/lab_command_key`, 32 random
bytes as 64 hex characters). volume-init stages it root-owned 0400 into `lab_secrets` for the
lab and UID 10001 0400 into `execution_secrets` for the execution worker only
(`NANFO_LAB_COMMAND_KEY_FILE=/run/nanfo-lab-key/lab_command_key`). The C21 Ed25519
receiver-health keypair is generated as well: the public key
(`secrets/receiver_health_public_key.pem`) is staged for the verifiers — the API, autonomy
and execution workers read `NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE=/run/secrets/receiver_health_public_key.pem`.
The signing key goes to `receiver/receiver_health_private_key.pem`, a 0700 directory that no
container (not even volume-init) mounts. Install it only on the separately packaged FRR
receiver as `NANFO_RECEIVER_HEALTH_PRIVATE_KEY_FILE` (0400/0600); afterwards it may be removed
from the deployment host. `NANFO_RECEIVER_HEALTH_LEGACY_HMAC=true` is for frozen runtimes only
and is set nowhere in this package.

**Images.** Multi-arch index digests, verified against Docker Hub on 2026-09-24 as the latest
patch releases of their lines:

| Store | Pinned reference |
| --- | --- |
| PostgreSQL | `postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652` |
| Redis (base of `Dockerfile.redis`; ≥ 7.4.6 for CVE-2025-49844) | `redis:7.4.11-bookworm@sha256:c6eabf748fc7a61dbb5a705c78bcf3d6377b1127a97d0ce965c11c44ba46896f` |
| Neo4j (base of `Dockerfile.neo4j`) | `neo4j:5.26.31-community-trixie@sha256:ab3aafb0020e6fed65bb2b59f7db1fabd7ee0568c4da46f3cc3b8fad77801d61` |

PostgreSQL stays on bookworm (same glibc/collation as the previous 17.6-bookworm). Neo4j no
longer publishes ubi9/bullseye 5.26 variants after 5.26.24; trixie keeps the su-exec, tini
and UID 7474 layout the entrypoint relies on. `manage.py build` also builds the Redis image.
The backend image context is a precise allowlist: host tools (`deploy/{manage,verify,
gateway_config}.py`, `backend/scripts/{test_,verify_,review_}*.py`, `backend/scripts/acceptance/`)
never enter it, and the embedded report PDF font ships in both build paths.

**Fleet (optional overlay).** `compose.fleet.yaml` gives the SNMP collector a private
`NANFO_SNMP_RUNTIME_DIR` tmpfs (0700, UID 10001) and requires `NANFO_FLEET_EGRESS_SUBNET`
(a pinned unused private /24) so the host `DOCKER-USER` rules that restrict its egress to
UDP/161 keep matching; see `NETSNMP.md`.

**State location.** Without `--state`, `manage.py` keeps an existing in-repository deployment
(`deploy/state/deployment.env`, with a warning that it lives inside the checkout) and
otherwise uses `${XDG_STATE_HOME:-~/.local/state}/nanfo`. State is never moved, and an
evidence-only `deploy/state` directory is not treated as a deployment. Existing ADR-020–
ADR-027 deployments predate the new configuration keys and volumes: `manage.py` refuses them
until an explicit, reviewed upgrade; nothing is regenerated implicitly.

## Current-source schema contract — 2026-09-20 (historical: 0029)

Fresh builds from this source explicitly target **0029**, centralized in
`backend/app/core/schema_version.py`. Initialization, readiness/maintenance,
`manage.py` markers/adoption, archive fixtures and new `verify.py` runs agree.
The verifier records `migration_0029`; this configuration is not a new accepted
deployment or image identity. A fresh start checks the installed checkpoint
before writing its marker, so an old image cannot be mislabeled0029.

Historical0027/0028 (and earlier) images, build records and acceptance evidence below
remain historical. Evidence export preserves their migration names/statuses.
Cold restore remains exact-image/schema, without migrations; current tooling will
not adopt/start an old0027/0028 marker as a current release. Use matching historical
tooling for those images, or a separately reviewed explicit upgrade procedure.
The historical measured-twin verifier remains targeted at0027 and must use its
matching source/runtime, not current0029 readiness. Migration0029 adds no tables;
it invalidates old Autonomy telemetry-coverage claims and requires reconciliation.

Backup/restore0027+ always requires telemetry archive integrity and released
autonomous-execution proof;0028+ additionally requires no unreleased experimental
runs, owned resources or pending actions. This only reads ownership state; it does
not activate a private lab mode or reset/release work. New0029 images still require
their own live deployment/backup/restore acceptance. See `VALIDATION.md`.

## Current Build Handoff

The Docker root is now `/home/.system-data/docker`. The prior image IDs and disk
blockers below are historical. Fresh **real Docker builds** completed under the
build-only project `nanfo-deploy-step15-rebuild`; no application, lab lifecycle,
migration or datastore initialization was started and no project volumes were created.

| Image Tag | Current Exact Local ID |
| --- | --- |
| `nanfo-deploy-step15-rebuild-backend:adr020` | `sha256:55a65205a6ba81c1ce489e9fab1abfba1dd9dd57c24ee2676de76ee5deaddec7` |
| `nanfo-deploy-step15-rebuild-frontend:adr020` | `sha256:7ec667ab18129019d5587610b62ad4b896cb395208ffef2a53003ec1df3931c2` |
| `nanfo-deploy-step15-rebuild-neo4j:5.26.12` | `sha256:feda142d85d1cae43b6a3835b9c9820f4cce2249a288b77b1597e2827e87155a` |
| `nanfo-deploy-step15-rebuild-backend:adr020-ai` | `sha256:68eb136293a728c83ee2126904f7bc7c1f86e8b483ab229eb649925bfc14460d` |
| `nanfo-emulation:operator-paths-adr020` | `sha256:aafbad31e766488bbfd0709a5b12798677505c8bae3cc7b957405b0b16ecee03` |

Use `deploy/core-build-adr020-current.json` for the independent verifier's
`--reuse-build-record`, with these exact backend/frontend/Neo4j/lab/AI IDs. It
includes the stable Poetry lock, readiness/config/graph-checkpoint source hashes
and references to full per-build source manifests under
`/tmp/opencode/nanfo-deploy-step15-rebuild/build-*.json`. This is a new source-built
operator lab, **not** a reconstruction of any historical frozen image identity;
no default or model-specific image alias was changed.

Poetry2.4.1 main-only locked install and final pip check passed. Frontend `npm ci`,
lint, typecheck and production build passed. Lab build passed95 tests with2 opt-in
live skips. The build allowlist includes the lab's hash-required `compose.yaml`,
but no output/commands/results, secrets, `.env`, virtualenvs or model artifacts.
The host-only `deploy/verify.py` is excluded from application images so concurrent
verifier edits do not contaminate release source parity.

Optional AI **image build is now complete**: `uv sync --locked --no-dev` installed
the independent CPU runtime, without backend dependency mixing or weights. The
existing loader installed seccomp and Landlock ABI10 as UID10001 inside Docker's
default security profile with read-only root, dropped caps and noexec scratch.
Subsequent confined torch/numpy/pydantic/gymnasium imports and a CPU tensor passed.
No custom seccomp profile, privileged API or executable scratch is needed on this
host. See `deploy/ai-build-adr020-current.json`. Original frozen checkpoint/history
artifacts are absent: full model inference is still unverified and must use external
read-only copies and the independently pinned registry. Do not substitute invented
weights or label this as autonomous activation.

Executed commands (all build-only):

```sh
python3 deploy/manage.py --state /tmp/opencode/nanfo-deploy-step15-rebuild init \
  --project nanfo-deploy-step15-rebuild --email step15-rebuild@example.com
python3 deploy/manage.py --state /tmp/opencode/nanfo-deploy-step15-rebuild build --service backend
python3 deploy/manage.py --state /tmp/opencode/nanfo-deploy-step15-rebuild build --service frontend
python3 deploy/manage.py --state /tmp/opencode/nanfo-deploy-step15-rebuild build --service neo4j
python3 deploy/manage.py --state /tmp/opencode/nanfo-deploy-step15-rebuild build --service backend --with-ai
python3 deploy/manage.py --state /tmp/opencode/nanfo-deploy-step15-rebuild build --service lab
```

Existing services and volumes were not altered. Only the known failed lab-test
build container from this attempt was removed after the corrected build passed.
The waiting verifier may reuse these images in its separately owned fresh projects.

This package runs one API, five independent workers, a frontend gateway and three
private stores. It is not certification of Step9/10 autonomy, live inference,
physical control, or disaster recovery acceptance. Defaults leave lab control and
model diagnostics unavailable. No existing `nanfo_*` service is a deployment target.

## Fresh Install

Requirements: Linux Docker Engine, Compose v2 or newer, Python 3.12+, about 6 GiB
available memory and sufficient private disk space (build preflight requires 3 GiB
free, 6 GiB for optional AI). Docker access is host-root
equivalent. Use a dedicated operator account. Buildx is recommended; `manage.py`
also supports the legacy Docker builder using a newly staged, allowlisted context.
No host virtualenv, site-packages, `.env`, credentials or generated artifacts enter
that context. Docker installs dependencies from the checked-in locks.

Choose a **new**, absolute state directory with an existing private parent and a
unique `nanfo-deploy-*` project. Commands below never reuse shared development DBs.

```sh
python3 deploy/manage.py --state /srv/nanfo/instance1 init \
  --project nanfo-deploy-instance1 --email operator@example.com --port 8787
python3 deploy/manage.py --state /srv/nanfo/instance1 config
python3 deploy/manage.py --state /srv/nanfo/instance1 build
python3 deploy/manage.py --state /srv/nanfo/instance1 start
python3 deploy/manage.py --state /srv/nanfo/instance1 status
```

`init` generates eight independent random passwords (PostgreSQL admin/owner/runtime,
Redis application and admin, Neo4j, JWT signing key, bootstrap), the C15 lab command key
and the C21 receiver-health keypair, without overwriting any file. The state, `secrets`
and `receiver` directories are 0700; source secret files are 0600. The nonsensitive
`deployment.env` contains project, paths, image tags, email, loopback port and the allocated
proxy/gateway subnets only. `--state` is optional (see "State location" above).
Read the bootstrap password locally from `secrets/bootstrap_password` using a
trusted password manager; never put it in command arguments, logs or screenshots.
The bootstrap actor has the existing Admin role; no example organization, network,
device or fabricated telemetry is seeded.

`start` first runs `volume-init`, starts private stores, runs the fresh-only
`initialize` command and then starts application services. Initializer refuses any
existing public table and creates `nanfo_owner` (migration owner) separately from
`nanfo_runtime`. Runtime has table DML, sequence usage and function execution but no
schema CREATE, ownership, role membership, superuser, migration-table writes or
audit UPDATE/DELETE. Database triggers remain enforced. Future schema upgrades
require an explicit reviewed release/migration procedure; `start` never migrates an
initialized installation and refuses changed image IDs. Failed first initialization
leaves evidence and resources intact, and requires operator reconciliation rather
than automatically rerunning or deleting volumes.

Open `http://127.0.0.1:8787`. Only the gateway publishes a host port, bound explicitly
to loopback, forwarding to non-root nginx port 8080. `/health` is liveness. `/ready` is
private: the gateway answers it with 404, while the API container's healthcheck (and
`verify.py`, through `docker compose exec`) call it on 127.0.0.1:8000. It checks the exact
current-source schema 0030, PostgreSQL, Redis, Neo4j, API lease and event consumers. Worker
health uses the existing `check_worker_health.py --worker NAME` and actual completed
loop progress under each container's private `/run/nanfo` tmpfs, not process existence;
the supervised loops use `supervise.py check --loop NAME` the same way.
The backend reads only `WORKER_HEARTBEAT_PATH` (`/run/nanfo/heartbeat.json`, one
`.<loop>` file per loop); the unread legacy duplicate variable was removed (ADR-028).

## Stop And Restart

```sh
python3 deploy/manage.py --state /srv/nanfo/instance1 stop
python3 deploy/manage.py --state /srv/nanfo/instance1 start
```

Stop closes gateway/API admissions, verifies the domain-owned maintenance checkpoint,
then stops workers and stores. If physical execution or overrides remain unresolved,
workers and stores stay running for recovery and the command fails. The optional lab
is never stopped or started implicitly. Never force-stop recovery to obtain a backup.
No lifecycle command runs `down -v`, prunes Docker, deletes volumes or touches another
project. Destructive verification cleanup requires a separate explicit verifier flag.

For direct operator Compose commands always specify project, env file and file:

```sh
docker compose --project-name nanfo-deploy-instance1 \
  --env-file /srv/nanfo/instance1/deployment.env -f deploy/compose.yaml ps --all
```

Do not invoke an unscoped default `up` to initialize a deployment. Do not use
`--scale api=2`: the mandatory Redis singleton lease rejects a second API owner.
Uvicorn access logging is disabled and gateway logs omit query strings and Referer,
including WebSocket bearer query parameters. Error detail is deliberately restricted.

## Persistence Interface

All names are Compose logical volumes, expanded to `<project>_<logical>` with no
global `container_name` or external volume aliases:

| Logical Volume | Owner And Mounts |
| --- | --- |
| `postgres_data` | PostgreSQL `/var/lib/postgresql/data` |
| `redis_data` | Redis `/data`; AOF enabled, `appendfsync always`, noeviction |
| `neo4j_data` | Neo4j `/data`, including system database and transaction logs |
| `reports` | UID10001 mode0700; report worker RW, API RO |
| `network_assets` | UID10001 mode0700; API and `asset-gc` RW, maintenance RO |
| `telemetry_archive` | UID10001 mode0700; `telemetry-retention` (+ `-cli`) RW, maintenance RO |
| `stream_archive` | UID10001 mode0700; `stream-retention` RW only (C14 archives) |
| `lab_output` | root:10001 directory0750; lab RW, API/execution/autonomy RO |
| `lab_commands` | UID10001 directory0750; execution worker RW (files 0640), lab/API/autonomy RO |
| `lab_results` | root:10001 directory0750; lab RW, API/execution/autonomy RO |
| `runtime_secrets_api` | UID10001 mode0700; runtime passwords, JWT key (+ verify-only previous keys), C21 public key; API only |
| `runtime_secrets_worker` | UID10001 mode0700; runtime passwords and C21 public key, **no JWT key**; workers |
| `execution_secrets` | UID10001 mode0700; C15 `lab_command_key` 0400; execution worker only |
| `lab_secrets` | root mode0700; C15 `lab_command_key` root 0400; lab only |
| `init_secrets` | UID10001 mode0700; all eight passwords 0400; initializer and rotation helper only |

Privileged `volume-init` runs with no network and only CHOWN/FOWNER/DAC_OVERRIDE.
It refuses nonempty volumes, never recursively changes evidence, and stages secret
copies per role because local Compose file secrets do not implement UID remapping;
`volume_init.py restage NAME` atomically replaces one staged secret in every volume
holding it (rotation). Application entrypoint requires `NANFO_SERVICE_ROLE` and
`APP_ENV`, rejects symlinks, multi-link/nonregular/oversized/unprotected secret files,
loads only the role's allowlist, validates the C15/C21 key files it is pointed at, and
execs the existing command as UID10001. Runtime never receives PostgreSQL owner/admin or
bootstrap passwords. Store wrappers read explicit secret files; Redis receives a
generated private config holding ACL password hashes rather than a password argument.
Neo4j wraps its shipped entrypoint and does not request or download APOC/plugins.
The C23 lab runs as root without DAC_OVERRIDE, so the lab volumes are owned by root with
group 10001 and the execution worker writes 0640 commands (`NANFO_UMASK=027`) that the lab
reads through its supplementary group 10001.

API/workers/gateway have read-only roots, dropped capabilities, no-new-privileges,
bounded resources/logs and noexec tmpfs. Neo4j alone needs executable scratch for
its bundled JNA native library. No API/worker has a Docker socket, host PID/network,
physical NIC or privileged execution. Noexec writable mounts do not prohibit loading
already-installed Python packages from the read-only image.

Binding is the read-only `${NANFO_STATE_DIR}/binding` directory. Optional model inputs
are `${NANFO_STATE_DIR}/models` and the separate protected `model-registry` directory.
Populate copies as root-owned files readable by UID10001, never group/world writable;
the binding and registry readers reject files owned by an arbitrary host user even
when bind-mounted read-only. Empty unconfigured directories confer no capability.
Back up these directories with the declared volumes and original secret files.

## Optional Lab

The lab is opt-in and never started by `manage.py start` or a package build. Two
mutually exclusive overlays exist (ADR-028 C23):

- **Successor (default), `compose.lab.yaml`.** `network_mode: none`, `cap_drop: [ALL]`
  plus only `NET_ADMIN`, `NET_RAW`, `SYS_ADMIN` (namespace/OVS/FRR management),
  `no-new-privileges`, read-only root and `nosuid,nodev` tmpfs scratch for `/run`, `/tmp`,
  the Open vSwitch state directories and `/var/log`. It mounts the three lab volumes and
  the root-owned C15 command key (`lab_secrets`, `NANFO_LAB_COMMAND_KEY_FILE`) only, runs
  as root without DAC_OVERRIDE and reads 0640 commands through group 10001. It is a new
  runtime: its results need fresh qualification before any claim.
- **Frozen (historical reproduction only), `compose.lab.frozen.yaml`.** The recorded
  privileged end-of-life image (Debian 11 / Python 3.9), `NANFO_LAB_FROZEN_IMAGE`,
  receives no key material and runs with mailbox control pinned off: it predates C15 and
  cannot accept the MAC'd commands of the current execution worker. Compose refuses to
  render it unless `NANFO_LAB_FROZEN` is set, and `manage.py` requires exactly
  `NANFO_LAB_FROZEN=1` and prints a warning. Never use it for new qualification claims.

Neither lab may receive credentials, binding, models, host devices, a Docker socket,
host networking or host PID. `verify.py` refuses any other capability, a writable or
credential mount, and a privileged lab without the frozen acknowledgement.

Build the successor from `emulation/Dockerfile` with either `python3 emulation/control.py build`
(AI-Lab) or `manage.py build --service lab` (allowed after initialization, because the lab
image is pinned separately and never recorded in `initialized.json`): both use the same
sources (`emulation/` minus its
`.dockerignore` entries), tag `nanfo-emulation:successor-<first 12 hex of the source digest>`
and label `org.nanfo.lab.source-sha256`; the historical `operator-paths-adr020` tag is never
moved. Record the exact local sha256 image ID or
`name@sha256:` registry digest in `NANFO_LAB_IMAGE` in `deployment.env`, and use the
approved operator enrollment/binding workflow in `emulation/README.md`. `manage.py lab`
accepts only such immutable references and starts only an initialized deployment (so the
lab volumes carry the volume-init layout and the staged key). Set
`EMULATION_BINDING_DIGEST` to the verified binding digest. Explicitly set emulation
mode, snapshot adapter (`emulation`), and `EMULATION_CONTROL_ENABLED=true` only after
binding authorization and recovery evidence are checked. Admission performs read-only
mailbox validation; only the execution worker writes (HMAC-signed, 0640) commands. The
root lab publishes 0640 observations/results/journal with group 10001 inside root:10001
0750 directories, which the unprivileged readers can read without allowing producer
writes to binding. The SDN runtime needs only the capabilities above; the FRR experiment
modes that `emulation/control.py` launches additionally need `NET_BIND_SERVICE` and are not
part of this package's lab service.

```sh
python3 deploy/manage.py --state /srv/nanfo/instance1 lab start      # status | stop
NANFO_LAB_FROZEN=1 python3 deploy/manage.py --state /srv/nanfo/instance1 lab start --frozen
```

Never delete `.journal.json` or replay an old physical command into a new lab run.
Restore stays control-disabled until durable execution and override state reconcile.

## Optional Frozen AI

`Dockerfile.backend --target with-ai` builds a completely separate
`/opt/nanfo/ai-runtime` from `ai-engine/uv.lock` with `uv sync --locked --no-dev`.
It uses Python3.12.14 and the exact torch2.8.0+cpu/gymnasium1.2.0/numpy2.2.6/
pydantic2.11.7 environment. Backend Poetry dependencies never enter that environment.
No weights, history, calibration or registry are embedded. An operator must provide
the hash-pinned source/checkpoint/history registry and read-only external artifact
copies, then explicitly build/use `compose.ai.yaml` with a distinct `NANFO_AI_IMAGE`
and `NANFO_MODEL_REGISTRY_SHA256`. Keep `/tmp` noexec and confinement enabled.
`manage.py ... build --service backend --with-ai` builds a distinct `:adr020-ai`
tag without changing the recorded normal runtime image.
The existing subprocess validates Landlock ABI5 and seccomp; unsupported kernels
remain unavailable rather than weakening sandboxing. This is historical diagnostic
inference only, not live autonomy or proof of qualification.

## Recovery And Diagnostics

The independent operations workstream owns `backup_restore.py`, `maintenance.py`,
`retention.py`, `diagnostics.py` and their tests. Use each CLI's `--help` for its exact
arguments. Diagnostics execute the credential-loading entrypoint before the internal
maintenance command. Backup must close admissions, verify no unresolved physical
state, quiesce writers and stop stores before reading volume bytes. Never tar live DBs.
Retain encrypted backups off-host with separately protected encryption keys and
original deployment secrets. Never include plaintext credentials in evidence reports.
Restore only to a different fresh `nanfo-deploy-*` project, with identical pinned
images, copied protected secrets and fresh binding/model directories. Do not run the
fresh database initializer on restored data. Verify schema, datastore readiness,
same report bytes, workflow state and a new login before opening the gateway.
Invalidate only the approved auth-session families and stale API lease after all old
owners are confirmed stopped. Redis streams/pending work and recovery journals survive.

After `backup_restore.py restore` returns `restored_verified`, leave all source
owners stopped and all target writers stopped. The target must have its own private
`deployment.env` with the restored image tags and original copied secrets, but no
`initializing` or `initialized.json` from the source. Resume explicitly:

```sh
python3 deploy/manage.py --state /srv/nanfo/restored start \
  --restored /srv/nanfo/backups/backup1 \
  --encryption-key-file /srv/nanfo/keys/backup.key
```

This authenticates the backup manifest, verifies distinct source/target projects,
stopped owners, exact image/mount/secret/volume inventories and report/model/schema
checkpoint, then reruns the approved session invalidation check before creating
the local lifecycle marker. It never calls the fresh initializer or extracts over
existing volumes. Failures leave writers stopped; do not hand-create a marker to
bypass them. This adoption command supports the base Compose layout; optional
overlay restoration stays with the explicit backup-tool workflow.

## Capacity Limits

`REPORTS_MIN_FREE_BYTES` defaults to 67108864 (64 MiB), with a validated range of
1 MiB to 1 TiB. Report admission checks the protected report filesystem before
reading sources or persisting a new job; idempotent replays remain readable.
Workers recheck before rendering and publication, reserving the configured free
floor plus the full maximum artifact size. Exhaustion or unavailable storage
refuses new work with `REPORT_STORAGE_UNAVAILABLE`, without removing any existing
report. `/ready` exposes `checks.report_storage` and numeric
`storage.reports.{available_bytes,min_free_bytes,required_bytes,ready}`; low bytes
or exhausted inodes returns503. Existing downloads do not require spare capacity.

This is a **free-space admission guard, not a hard quota or reservation**. Other
processes/concurrent writers can consume space after a check. Default local named
volumes have no per-volume size quota. Provision dedicated quota-enforced storage
with the host storage administrator, set the free floor within that quota, and
monitor Docker/store filesystems before admitting large workloads. This package
does not alter host filesystem quotas, prune data, or promise protection against
all datastore/host disk exhaustion. PostgreSQL and Neo4j total durable data remain
unbounded by this application guard. Redis has a192MiB noeviction admission limit;
AOF and streams can still require more disk. Docker logs are independently capped.

Retention (ADR-028): the supervised `telemetry-retention` and `stream-retention` loops
archive before they delete, in bounded batches, into their private archive volumes, and
refuse (exit 3 after repeated refusals) on unsafe conditions such as a non-`noeviction`
Redis, low archive disk or pending/changed entries; domain-stream entries that are still
pending in a consumer group are never eligible. Archive volumes are part of every backup.
The report orphan cleanup is separately opt-in, bounded, backup-gated and requires stopped
writers; it never deletes referenced artifacts. Audits, diagnostic/config/alert histories
and uncertain execution evidence are not age-deleted. Full Step15 hard-quota/capacity
acceptance is not claimed from these guards.

**PostgreSQL connection budget.** `max_connections=200` (compose `command`), sized for
every SQLAlchemy pool at the backend defaults `DB_POOL_SIZE=5` + `DB_MAX_OVERFLOW=5`:

| Consumer | Worst-case connections |
| --- | --- |
| API, plus `api2` when distributed | 2 × 10 = 20 |
| Six workers | 6 × 10 = 60 |
| `telemetry-retention` (application pool + retention engine default 5 + 10) | 10 + 15 = 25 |
| `asset-gc` | 10 |
| `fleet-worker` (optional) | 10 |
| Concurrent worker healthchecks | 6 |
| One-shot maintenance/rotation/initializer | 10 |
| `superuser_reserved_connections` | 3 |
| **Total** | **144 of 200** |

`stream-retention` uses Redis only. Raising pool settings, adding APIs or overlays requires
raising `max_connections` together with the container `mem_limit` (1 GiB) and `pids_limit`
(300; one backend process per connection); `test_postgres_connection_budget_covers_every_pool`
keeps the budget honest.

## Network Exposure

Keep the loopback binding. Before remote use, terminate TLS at a separately managed
reverse proxy with a trusted certificate, WebSocket Upgrade forwarding, request-size
limits and query-redacted access/error logs. Proxy to loopback8787; do not publish the
stores. Configure the exact HTTPS origin in backend CORS rather than wildcards, and
verify login, authorized downloads and WebSockets over HTTPS. Docker's private bridge
uses plaintext internal protocols; hosts with untrusted local tenants need additional
network/TLS isolation beyond this single-host package.

**Client addresses behind the host TLS proxy (R06).** Every connection to the
loopback-published port reaches nginx from the Docker bridge gateway of the pinned
`gateway` network (`NANFO_GATEWAY_SUBNET`, `NANFO_GATEWAY_BRIDGE_IP`; `init` allocates an
unused private /24 and its `.1` gateway). The gateway trusts `X-Forwarded-For` and
`X-Forwarded-Proto` **only from that address** (`set_real_ip_from <bridge>/32`,
`real_ip_recursive on`, rendered at start from `NANFO_GATEWAY_TRUSTED_HOP`); headers from
any other peer are ignored and the scheme falls back to nginx's own. Consequently the host
proxy must:

- **overwrite** `X-Forwarded-For` with the connecting client's address — never append a
  client-supplied chain (nginx: `proxy_set_header X-Forwarded-For $remote_addr;`, not
  `$proxy_add_x_forwarded_for`; HAProxy: `http-request set-header X-Forwarded-For %[src]`;
  Caddy strips untrusted client values by default) — because anything it forwards is
  trusted;
- set `X-Forwarded-Proto https`, forward `Upgrade`/`Connection` and `Sec-WebSocket-Protocol`
  (C1 subprotocol bearer), keep `X-Request-ID` if you want end-to-end correlation (nginx keeps
  a well-formed client value, otherwise issues its own), and connect to `127.0.0.1:<port>`
  on the same host so the peer is the bridge gateway.

Without a host proxy, every browser appears as the bridge gateway, which collapses the
per-client login limits into one bucket; do not expose the loopback port through other
forwarding (SSH tunnels, `socat`) without the same header discipline. The API trusts only
nginx's fixed proxy-network address (`FORWARDED_ALLOW_IPS`) and receives exactly one hop.

The gateway serves a strict same-origin policy on every response (CSP
`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'
data: blob:; font-src 'self'; connect-src 'self' blob: data:; worker-src 'self' blob:;
object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'`,
`Permissions-Policy`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`), immutable hashed `/assets/` (missing assets 404), a
revalidated `index.html`, static-only gzip, and answers `/ready`, `/api/docs`,
`/api/redoc` and `/api/openapi.json` with 404. `POST /api/v1/auth/login` is limited at the
edge to 10/min per real client (burst 5) with a JSON 429 envelope, in addition to the API's
own C11 limits. Access logs are JSON with `request_id`, `request_time` and
`upstream_status` and never contain query strings or Referer; errors log at `warn`.

## Packaging Verification 2026-09-12

Verified with real Docker builds, not host site-packages:

- Backend Poetry2.4.1 lock check, 48 main dependencies including asyncpg0.30.0,
  Python3.12.14 and dependency consistency passed. The coordinated lock refresh
  adds only Ruff0.15.6 in the dev group; runtime dependencies did not change.
- Frontend Node22.22.0 `npm ci`, lint, typecheck and production build passed.
- Fresh project `nanfo-deploy-step15-package` migrated to0019, authenticated the
  dedicated bootstrap actor, and reached healthy API/gateway/all five workers.
- Runtime DB identity was `nanfo_runtime`, all public tables owned by `nanfo_owner`;
  runtime schema CREATE, migration UPDATE and owner membership were false while
  reports INSERT was true. Application UID was10001.
- Maintenance-gated stop and subsequent restart passed without migration or lab use.
- Compose config and scoped packaging Ruff checks passed. Independent deployment
  operations/verifier suite passed83 tests; those tests are owned by other agents.

Built local images (not registry-pushed):

| Image | Exact Local ID |
| --- | --- |
| `nanfo-deploy-step15-package-backend:adr020` | `sha256:00aad16e9ef1763c3b62fdc61aa2f34c9855f42e62edf6ef0cc87b58e14ea1ee` |
| `nanfo-deploy-step15-package-frontend:adr020` | `sha256:9f8206ed5a0a8553fe5ec27ebcfd47e3d3539fcf87fa50a838e161c4996ac96d` |
| `nanfo-deploy-step15-package-neo4j:5.26.12` | `sha256:ec7023058bfc067054cd89778bde826ffe22a97c25dd96647a9ff9f47bbee62b` |

State: `/tmp/opencode/nanfo-deploy-step15-package`; loopback gateway8787.
The optional AI locked dependency stage installed all19 exact runtime packages,
but final image creation was blocked by host Docker disk exhaustion. Only this
workstream's failed build containers/intermediates were removed to recover space;
no volumes or shared images were deleted. The package recovered and restarted healthy.
The unnecessary libseccomp apt step was removed: the digest-pinned Python base already
ships libseccomp2 2.5.4-1+deb12u1. AI cache cleanup and disk preflight now avoid repeating
the unbounded build pressure. Final with-AI image and confined inference still require
a rerun after at least6GiB is available. Do not claim them verified from dependency
installation alone. Backup/restore, physical lab and browser acceptance belong to the
independent verifier, not this packaging smoke gate. Original shared stores and the
pre-existing stopped lab were not targeted.

### Final Handoff

Current `poetry check --lock` passes with only the coordinated Ruff0.15.6 dev
addition; no lock regeneration or AI rebuild was needed for this final handoff.
The existing core image's `/opt/nanfo/deploy/maintenance.py`, report operations and
telemetry operations match current source SHA256s. Its maintenance CLI supports
`quiesce`, `checkpoint`, `restore-verify`, `diagnose`; actual diagnose returned schema0019,
model-reference counts and healthy dependencies. Exact maintenance SHA256:
`d1ed480646079350ebb7f870f0251327324e35e69259655606f2d69af5f7ab18`.
All three core image tags above remain available for verifier reuse; the isolated
packaging stack remains running. Do not concurrently run another API owner against
its stores, stop it for another agent without coordination, or delete its volumes
without explicit approval. No cleanup or Docker pruning was performed in this handoff.

The **new report-capacity code is not in that previously built image**. A subsequent
core rebuild must include it before claiming live capacity acceptance. It passed
the complete backend suite (2100 passed,89 opt-in skips); deployment/restore-adoption
tests passed97. Restore adoption is unit-verified, not an independent full restore
claim. Final optional AI image/confinement remains blocked and was not retried with
829MiB root free. Large builds and additional full-stack boot require disk/memory
coordination with the authorized independent verifier.

### Final Core Rebuild

The authorized **core-only** rebuild now includes report capacity/readiness, the
current DB URL fixes, backup maintenance and Network-owned Neo4j graph checkpoint.
This supersedes the earlier source-only capacity handoff, but does not replace the
running packaging stack's image or its `initialized.json` pin.

- New tag: `nanfo-deploy-step15-package-backend:adr020-final`
- Exact ID: `sha256:b69f37bb8f5404b6ef81beef965f11ba90aba7e3ddf0ceec7f66a1ee7e8be108`
- Build record: `deploy/core-build-adr020-final.json`
- Locked Python3.12.14/Poetry2.4.1 main-only Docker dependency stage reused its
  verified clean cache; host and image dependency checks pass. Ruff0.15.6 remains
  dev-only and is absent from the final runtime.
- All216 staged runtime files matched their packaged bytes. Requested config,
  readiness, maintenance, backup and graph-checkpoint files also matched current
  sources. The host verifier changed during build, so automatic full-current-source
  recording correctly refused. Its packaged `deploy/verify.py` is an older copy;
  use the current host verifier. The explicit record retains that exception.
- Final image core imports, UID10001, no AI runtime, dependency consistency and
  56 focused config/readiness/capacity/lifecycle tests passed. Fresh-stack runtime
  acceptance of this exact image remains with the independent verifier.

Executed build command (the new tag is now immutable to this CLI):

```sh
python3 deploy/manage.py --state /tmp/opencode/nanfo-deploy-step15-package \
  build --service backend \
  --image-tag nanfo-deploy-step15-package-backend:adr020-final
```

Verifier reuse is authorized on its **separate fresh project**: set that project's
`NANFO_BACKEND_IMAGE` to the exact ID above or the final tag and use `--no-build`.
Do not change the existing packaging source stack config/pin, migrate its stores,
or restart it onto the final tag. Existing frontend and Neo4j images remain reusable.
No AI build, volume deletion, shared-image pruning or stack restart was performed.
Docker reported5.6GiB free before this core build; optional AI remains blocked by
its6GiB headroom gate and was not attempted. No failed build container required cleanup.
