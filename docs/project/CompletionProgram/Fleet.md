# ADR023 collector fleet handoff

## Design and ownership

Telemetry owns `fleet*.py`, migration **0026 after0025**, and
`backend/scripts/run_fleet_collector.py`. The manifest is an operator-protected
file listing individual existing SNMP bindings and credential paths, never an
inventory scan, credential search or vendor discovery mechanism. Existing
`measured_snmp` API composition remains available for parent integration.

Each device has a PostgreSQL schedule and expiring fenced lease. A session advisory
lock additionally excludes replicas while an external operation is outstanding;
its dedicated connection uses AUTOCOMMIT (no transaction across external I/O).
Short repository transactions commit before SNMP or Redis operations. A watchdog
renews leases or cancels collection on failure; every GET and publication checks
current manifest, binding, owner authority and live lease. Abrupt process death
releases the advisory lock; takeover waits for lease expiry as well.

The complete measured batch is committed to PostgreSQL before its first publish.
The spool preserves sample event IDs and a stable batch correlation ID across
crash/restart. Delivery is at least once: a Redis success followed by a lost spool
ack replays that event ID through existing ingestion/dedup. Absolute freshness
deadlines never renew on replay. Expired samples become explicit terminal outcomes,
never zero-filled data. Restart starts a fresh rate baseline; wall/monotonic clocks
are not translated into invented intervals.

## Operator wiring

Run from `backend/` with the backend environment installed:

```sh
NANFO_FLEET_MANIFEST_PATH=/run/nanfo/fleet/manifest.json \
  poetry run python -m scripts.run_fleet_collector
```

`--once` executes one bounded sweep and emits credential-free operator health JSON.
SIGTERM/SIGINT cancel tasks, reap outstanding snmpget children and close dedicated
lock sessions. SIGKILL recovery needs no manual spool import. PostgreSQL and Redis
connection settings and `EXECUTION_MODE` use existing backend settings. All fleet
settings are separate, prefixed `NANFO_FLEET_`:

| Setting suffix | Default | Bounds / meaning |
|---|---:|---|
| `MANIFEST_PATH` | required | protected manifest |
| `CONCURRENCY` | 4 | 1–32 active devices per worker |
| `LEASE_SECONDS` | 30 | 3–300; renew every one-third lease |
| `DB_TIMEOUT_SECONDS` | 2 | 0.1–10; strictly below renewal interval |
| `PUBLISH_TIMEOUT_SECONDS` | 3 | 0.1–30; also bounded by remaining sample TTL |
| `SCAN_SECONDS` | 1 | 0.1–30; round-robin bounded admission |
| `HEALTH_TTL_SECONDS` | 90 | 10–900; stale worker key expires |

Example **manifest only** (replace UUID and paths with provisioned values):

```json
{
  "version": 1,
  "targets": [{
    "device_id": "00000000-0000-4000-8000-000000000004",
    "binding_path": "/run/nanfo/fleet/device-a.json",
    "credentials_path": "/run/nanfo/secrets/device-a-snmp.json",
    "interval_seconds": 10.0,
    "backoff_max_seconds": 300.0,
    "poll_timeout_seconds": 25.0
  }]
}
```

Files must be regular, mode0600, owned by worker UID or root, without symlinks;
ancestor directories must meet the existing protected-file boundary. Manifest
limit is256 unique device IDs **and64KiB**, whichever is reached first. Each binding
uses existing `SNMPBinding` v1 (explicit unicast IP/port, sysName,1–16 named interface
indices, org/workspace/network/device/actor scope and physical/emulation labels).
Credentials retain the existing SNMPv3 authPriv protected JSON schema. Never embed
credentials in manifest/environment/argv. Paths are absolute. Manifest replacement
requires a worker restart; live changes fail closed before subsequent I/O.

Per-device interval1–3600s, backoff ceiling1–3600s (at least interval), poll
deadline1–300s. Failure delay is `min(ceiling, interval * 2**failures)`; successful
delivery resets failures. Due times/backoff are shared in PostgreSQL across replicas.
Timeout budgeting checks the existing binding freshness/rate window. A failed
binding or target consumes only its bounded slot; other targets continue. Spool
permits one pending batch/device, at most112 samples/batch. Retain32 terminal batches
per device plus lifetime published/expired counters; these are delivery diagnostics,
not telemetry evidence/history. Pending spool blocks additional collection until
delivery, expiry, or explicit changed-binding terminalization. Downgrade refuses
pending spool. Removed manifest devices are not read or replayed; their pending rows
remain inert until explicitly re-enrolled, then freshness is checked.

The actor must have `read:telemetry`, `read:topology`, **`write:config`**, current
write-capable workspace/org membership, and an active matching device/IP. Under
ADR026, current Identity maps global `Operator` to `read:topology`, `read:telemetry`,
`write:config` and `execute:rollback`; the earlier read-only description is obsolete.
An Operator still needs the actual current membership, scope and binding checks;
the role name alone does not grant fleet authority. Owner checks use the existing
Identity/Network public services in fresh sessions.

## Parent integration / health / dependencies

1. Apply0025 then0026. Import `app.modules.telemetry.fleet_models` in shared
   Alembic metadata registration for autogenerate parity (migration itself imports
   its owning models). No fleet imports are required in API serving processes.
2. Add an explicit fleet worker service/process, protected read-only mounts and
   restart policy. **Disable API measured_snmp polling whenever fleet owns those
   devices.** Existing API composition is deliberately untouched; legacy collectors
   do not acquire fleet leases and must not run for fleet-owned devices.
3. Keep the existing durable domain consumers/persistence enabled. Fleet calls
   `TelemetryIngestionService.ingest`, publishing existing
   `telemetry.metric.ingested`; no new domain events or public routes. A spool
   `published` outcome means Redis publication acknowledged, not proof that all
   downstream persistence/socket consumers completed. Retention0025 tombstones
   and owning persistence provide global event dedup; this agent does not change them.
4. Each worker publishes expiring internal Redis JSON at
   `nanfo:fleet:health:v1:<worker_uuid>`. Schema1 contains worker ID, observed time,
   status, active/configured counts and per-device outcome/failures, next due time,
   lease-active flag, last publication/time/age/freshness, published/expired counts.
   `FleetRepository.health(device_ids)` is the owning DB diagnostic boundary.
   Parent health composition should bounded-SCAN these keys, enforce heartbeat age,
   aggregate the configured device set and preserve missing/stale as unavailable.
   No key or an empty history does not mean zero traffic. Health freshness budget is
   interval + poll timeout + scan; the spool separately enforces binding sample TTL.
   No health REST endpoint or shared runtime-health registration was changed here.
5. Use direct/session-mode PostgreSQL connections, **not transaction-mode PgBouncer**.
   Budget at most concurrency dedicated advisory-lock sessions plus concurrency+2
   pooled owning/authorization sessions per worker. Application transactions do not
   remain open across SNMP/Redis I/O. Watchdog loss cancels and reaps I/O before lock
   release. Hard connection/process loss relies on PostgreSQL session cleanup and
   lease expiry; this is read-only collection, not device-side actuation fencing.
6. Python dependencies are already present: SQLAlchemy/asyncpg, Redis, Pydantic.
   **Parent must package and pin Net-SNMP `snmpget` at `/usr/bin/snmpget`** (Debian
   package `snmp`, plus its version-matched runtime libraries); executable must be
   regular, owned by root/worker and not group/world-writable. Require SHA-256/AES
   support. A writable private temporary directory is needed for0600 per-request
   client configuration. `snmpd` is an acceptance-only package, not a worker runtime
   dependency. Image installation and source-matched deployment acceptance remain
   parent work; no Docker image was built here.

## Validation and evidence boundaries

Commands use opt-in disposable infrastructure only:

```sh
poetry run pytest --no-cov -q tests/unit/test_fleet.py \
  tests/unit/test_measured_snmp.py tests/unit/test_snmp_composition.py
FLEET_TEST_DSN='<private asyncpg DSN>' \
  poetry run pytest --no-cov -q tests/integration/test_fleet_postgres.py
FLEET_TEST_DSN='<private asyncpg DSN>' \
FLEET_TEST_REDIS_URL='<private Redis URL>' FLEET_LOCAL_SNMP=1 \
  poetry run pytest --no-cov -q tests/integration/test_fleet_local_snmp.py
```

The PostgreSQL fixture upgrades the complete chain through0026, downgrades to0025
and upgrades0026 again in unique schemas. Tests cover simultaneous lease claims,
stale-token exclusion, expiry during live I/O, no idle-in-transaction lock sessions,
competing workers, ambiguous publish replay, expiry accounting and per-device backoff.
A real child process is SIGKILLed after spool commit; the new owner reacquires the
released session lock and resumes the exact committed event ID.

Local acceptance uses two actual independently configured loopback `snmpd` endpoints,
SHA-256/AES credentials in private temporary files, matching live inventory and real
Identity/Network authorization, private PostgreSQL and private Redis. A third target
has a wrong sysName and cannot block the two healthy targets. Repeated reads preserve
actual counter provenance, restart replays the exact event through real Redis, and
actor revocation prevents further publication. Loopback has no guaranteed interface
capacity: absent derived utilization is valid and is not filled with invented rates.
This validates local collector runtime, not physical firmware/capacity, production
scale, downstream full-stack consumption or independent hardware fidelity.

The historical ADR023 initial live gate failed with its then-read-only Operator role;
fixture provisioning was corrected to a write-authorized identity and rerun. Private
agent processes are reaped and secret/state directories removed by test cleanup.

**Completed2026-09-20:** combined scoped gate **115 passed in12.66s**, including
all opt-in PostgreSQL/local-SNMP cases (no skips); scoped Ruff passed. Private native
PostgreSQL at loopback55483 was stopped, and the uniquely named
`nanfo-fleet-adr023-redis-20260920` container was removed. No shared daemon was
modified, no image built, and no commit created. Changes are confined to the ten
new fleet/migration/entry/test/handoff files; existing SNMP hooks required no edits.

### Packaged Debian Net-SNMP initialization fix (2026-09-20)

The later packaged gate in
`DeploymentEvidence-ADR023-20260920/README.md` reproduced Net-SNMP
`5.9.3+dfsg-2+deb12u1` creating `cert_indexes` under the isolated
`SNMP_PERSISTENT_DIR` and printing its creation to stderr despite a successful GET.
The existing strict transport correctly rejected that stderr; host-only acceptance
did not expose this packaged initialization behavior.

`snmp_transport.py` now creates an **empty0700 `cert_indexes` directory** inside the
fresh0700 per-request temporary directory **before spawning snmpget**. The directory
uses a fixed child name, is never reused, and is removed together with the0600
credential config on success, failure or cancellation. No certificates, system
configuration, credentials or shared directories are imported. No logging filters,
stderr allowlists or warning suppression were added: any stderr, including the same
directory-creation text if it unexpectedly recurs, still fails the request. SNMPv3
authPriv, executable checks, argument/environment secret isolation, output bounds,
timeouts and child cleanup remain enforced.

Scoped regression **111 passed in1.91s**, Ruff passed. Added a child-process regression
that reproduces the create-and-log behavior and proves private preprovisioning avoids
it; permissions/empty-state/cleanup checks and successful-exit stderr rejection are
also covered. These tests do not claim acceptance of the Debian image. **Deploy agent
handoff:** patch is ready for the small fleet image rebuild and private packaged
transport/fleet gate; preserve the failed packaged evidence and record new source
hash/image ID with the rerun. This fix launched no services, touched no shared
infrastructure and printed no secrets.
