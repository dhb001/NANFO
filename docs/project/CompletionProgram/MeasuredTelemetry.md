# P1 measured read-only telemetry — ADR021 handoff

## Status and scope

Implemented a real SNMPv3 `authPriv` GET transport, an identity-bound adapter,
owner-service authorization composition, and an operator CLI. The transport invokes
the installed standards-based Net-SNMP client; it does not generate measurements.
The default/demo adapter selection is unchanged. This work does not establish
physical acceptance or enable autonomy. API selector settings and a guarded async
composition helper are now delivered; parent wiring in `main.py` remains required.

Owned files:

- `backend/app/modules/telemetry/snmp_config.py`: immutable strict configuration,
  protected file loading and redacted secrets.
- `backend/app/modules/telemetry/snmp_transport.py`: bounded subprocess and IF-MIB
  response parsing.
- `backend/app/modules/telemetry/snmp.py`: counter semantics, pending batches and
  guarded owning-ingestion publication.
- `backend/app/modules/telemetry/snmp_ownership.py`: existing public owner contracts.
- `backend/app/modules/telemetry/snmp_composition.py`: API preflight/guarded action;
  `backend/app/core/config.py`: measured selector configuration;
  `backend/tests/unit/test_snmp_composition.py`: configuration/composition checks.
- `backend/scripts/collect_measured_telemetry.py` and
  `backend/tests/unit/test_measured_snmp.py`, `backend/tests/fixtures/snmp/`.

No migration, public endpoint, event name, or top-level event schema is added.
The existing `telemetry.metric.ingested` contract is used through
`TelemetryIngestionService.ingest`, including stable `event_id` replay. Parent
integration owns shared service/main/dependencies and status docs. The follow-up
request explicitly assigned core configuration to this workstream.

## Design and authorization contract

One process invocation binds **one device and 1–16 explicitly configured
interfaces**. All identities are supplied by an operator-owned immutable binding:
org, workspace, network, device, actor, IP literal, UDP port, expected sysName,
ifIndex and ifName. No discovery, address scanning, hostname/DNS resolution,
device creation, synthetic identity or automatic cross-network reassignment occurs.

`SNMPOwnerBoundary.authorize(binding, publish)` reloads the binding and compares it
with the original, then opens a fresh session and calls:

1. `AuthService.get_profile(actor_user_id)`: active identity and current permissions.
2. `NetworkService.assert_network_workspace_access(...)`: explicit workspace,
   org and current actor membership; `require_write=publish`.
3. `NetworkService.assert_device_workspace_access(...)`: returned network/workspace
   must exactly equal the binding.
4. `DeviceService.list_devices(...)`: active device, exact bound network and
   management IP. Bounded at 32 pages × 200 records; fail closed beyond this limit.

Diagnostics require `read:telemetry` and `read:topology`. Publication additionally
requires existing `write:config` capability and workspace write membership, following
the existing trusted operator-ingestion model. These are current service checks,
not unverified actor UUIDs or JWT claim snapshots. The operator configuration is
the delegated authority boundary; there is no new bearerless public ingestion API.

Authority is checked before **every interface GET**, after the complete collection, on retries,
and immediately before **each** publication. A change during external I/O may
leave an earlier authorized sample published; it blocks later publications.
There is no cross-module atomic authorization/publication transaction.

Inventory currently has no canonical interface-owner API. Interfaces are therefore
explicit **operator bindings**, revalidated against observed ifIndex/ifName, and
tagged `interface_identity_source=operator_binding_and_if_mib`. This is not a claim
that an interface UUID was resolved in inventory. sysName additionally guards
accidental target reassignment; SNMPv3 authentication provides transport peer
authentication. Use device-specific USM credentials. Engine-ID pinning and context
selection are not implemented; default SNMP context is required.

## Dependencies and exact parent wiring

Environment inspection on 2026-09-19:

- Backend Poetry Python **3.14.7**; installed Pydantic used.
- Neither `pysnmp` nor `easysnmp` is installed.
- `/usr/bin/snmpget --version`: **NET-SNMP 5.9.5.2**.
- No package installation or requirements/lock modification was performed.

**Python dependency delta: none.** Parent must provision `/usr/bin/snmpget` in
the collector runtime, with OpenSSL SNMPv3 SHA-256/AES support (Debian/Ubuntu
package `snmp`; RPM-family `net-snmp-utils`; validate the actual image/package
version). Numeric OIDs need no MIB download. The backend image is not claimed to
contain the host's binary. Parent should pin its distribution package/image through
the existing release manifest and run offline diagnostic and hardware gates there.

**Operator CLI requires no main/service factory changes.** With existing DB/Redis
configuration and an execution mode matching the binding:

```bash
# From backend/, after secret-manager/operator provisioning (commands are examples).
poetry run python -m scripts.collect_measured_telemetry \
  --binding /run/nanfo-snmp/binding.json \
  --credentials /run/nanfo-snmp/credentials.json --dry-run

# Actual authorized GETs; two observations produce one rate interval; no publication.
poetry run python -m scripts.collect_measured_telemetry \
  --binding /run/nanfo-snmp/binding.json \
  --credentials /run/nanfo-snmp/credentials.json --diagnostic --samples 2 --interval 10

# Actual authorized GETs and existing telemetry event publication.
poetry run python -m scripts.collect_measured_telemetry \
  --binding /run/nanfo-snmp/binding.json \
  --credentials /run/nanfo-snmp/credentials.json --publish --samples 2 --interval 10
```

`--dry-run` validates files and executable metadata without executing the binary,
opening DB/Redis, or contacting a device. It explicitly emits `scope_checked=false`.
It does not certify installed crypto support, credentials, membership or reachability.
`--diagnostic` prints measurements without publishing. Exit 0 means the requested
operation completed; 2 is unavailable/failed and 130 is operator interruption.
Errors contain fixed diagnostic codes, not response bytes or exception traces.
No automatic retry hides failures in the bounded CLI (1–100 cycles, 1–300s delay).

### Delivered API composition helper (follow-up integration)

Exact import and signature:

```python
from app.modules.telemetry.snmp_composition import build_measured_snmp_poll_action

async def build_measured_snmp_poll_action(
    *, settings: Settings,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    redis: Redis,
    ingestion_service: TelemetryIngestionService,
) -> Callable[[], Awaitable[None]]: ...
```

Parent `main.py` must branch **before** the existing runtime adapter factory:

```python
if settings.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower() == "measured_snmp":
    runtime_poll_action = await build_measured_snmp_poll_action(
        settings=settings,
        session_factory=AsyncSessionLocal,
        redis=redis,
        ingestion_service=ingestion_service,  # same instance used by collector
    )
    interval_seconds = settings.TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS
else:
    # Keep existing emulation/demo/stub factory and generic action wiring here.
    ...

# Use runtime_poll_action and interval_seconds in existing start_runtime_loop;
# keep the existing poll_max_attempts/backoff/sustained-failure settings.
```

Delivered settings (environment variables with these exact names):

| Setting | Default / validation |
|---|---|
| `TELEMETRY_RUNTIME_ADAPTER_MODE` | `stub`; recognizes `measured_snmp` configuration, preserving legacy selector/fallback behavior |
| `TELEMETRY_MEASURED_SNMP_BINDING_PATH` | `None`; absolute Path, no traversal/control characters; required for measured mode |
| `TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH` | `None`; same path validation, distinct from binding; required for measured mode |
| `TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS` | `10.0`, finite 1–300 seconds between completed loop cycles |
| `TELEMETRY_MEASURED_SNMP_POLL_TIMEOUT_SECONDS` | `60.0`, finite 1–300 seconds for one whole action/preflight authorization |

Selector matching uses strip/lower, consistent with existing main/factory semantics.
Legacy unknown-selector fallback stays intact; `measured_snmp` in demo execution
mode is rejected. The **binding** remains the source of per-request transport timeout
(`timeout_seconds=2.0`, 0.1–10s), `max_interval_seconds=120.0`, and
`max_pending_seconds=30.0`. Settings do not override the pinned binding/digest.

Build loads both protected files (0600), validates execution-mode equality, verifies
the executable metadata and performs current **publication** authorization with the
supplied session factory/Redis. Build performs no SNMP request. It rejects timing
configurations unless the conservative serial transport budget
`interfaces × (binding.timeout_seconds + 1)` is strictly below both the outer poll
timeout and pending TTL; poll interval plus that budget must be below the binding's
maximum rate interval. Defaults support a single interface; larger bindings may
need explicit TTL/budget adjustment. Owner/publication latency can still exhaust
the budget: failure remains bounded and explicit, not a guarantee of freshness.

The returned closure owns one stateful adapter and calls **only**
`adapter.collect_and_publish(ingestion_service)`. Its deadline includes authorization,
transport, publication and serialization wait. Every current-authority recheck and
pending-batch replay rule remains active. Cancellation propagates and reaps the
transport child; timeout and unexpected DB/Redis errors become fixed safe codes
because the runtime runner logs exception text. A timed-out/failed partial publish
retains staged samples for stable-ID retry, subject to the existing TTL. Build failure
must enter parent's existing unavailable/startup-cleanup path, never fallback to demo.

**Do not pass this adapter to `build_runtime_poll_action`**: the generic action omits
per-sample write-authority checks. Do not send `measured_snmp` through the unchanged
legacy factory. The helper does not start a loop or close supplied resources; parent
owns lifecycle and may add runtime adapter counters around the returned action.
Existing ingestion counters already run. `main.py` was not edited by this workstream.

### Local agent availability and isolated transport acceptance path

Read-only host inspection on 2026-09-19 (no daemon started):

- `/usr/bin/snmpd --version` and `--help`: Net-SNMP **5.9.5.2**; foreground `-f`,
  explicit config `-C -c`, private PID `-p` and explicit listen-address options present.
- `pacman -Qi net-snmp`: **5.9.5.2-1**, OpenSSL dependency; installed `snmpd`,
  `snmpget`, `snmpusm`, `net-snmp-config` under `/usr/bin`.
- `systemctl show snmpd.service`: loaded, **inactive/dead**, **disabled**.
- `ss -lun 'sport = :161 or sport = :1161'`: no listeners at inspection time.
- `net-snmp-config --configure-options`: IPv6 enabled; compiled default persistence
  `/var/net-snmp` and config `/etc`. Acceptance must override both with private paths.
  Version/package inspection does not prove successful SHA-256/AES interoperability.

The original proposed isolated **true protocol transport** acceptance procedure
follows. The user subsequently authorized the local transport subset; its actual
results are recorded below (separate from physical-device acceptance):

1. Recheck UDP1161 availability immediately before the campaign. Create a unique
   private 0700 directory under `/tmp/opencode` with private 0700 HOME/config/state
   subdirectories and a 077 umask. Provision fresh throwaway SNMPv3 credentials via
   protected 0600 files, never command arguments or logs. Do not edit `/etc/snmp`,
   `/var/net-snmp`, or use the system `snmpd.service`/create-v3-user helper.
2. Supply an explicit private `snmpd.conf` with `agentaddress udp:127.0.0.1:1161`,
   `sysName nanfo-isolated-snmp`, a dedicated `createUser` using SHA-256/AES, and
   `rouser <private-user> priv -V measured`. Define only read views for `.1.3.6.1.2.1.1`,
   `.1.3.6.1.2.1.2`, `.1.3.6.1.2.1.31`, and `.1.3.6.1.6.3.10.2.1.2`.
   Disable persistent passphrase retention by replacing bootstrap `createUser`
   with the daemon's localized USM state before any restart scenario. All bootstrap
   and localized-key files are secrets (0600). No `rwuser`, public community,
   `extend`, pass-through commands, AgentX master or trap receiver is needed.
3. Launch only the owned foreground child, without shell interpolation, with
   isolated `HOME`, `SNMPCONFPATH`, `SNMP_PERSISTENT_DIR`, `MIBS=""`, `LC_ALL=C` and
   argv `/usr/bin/snmpd -f -C -c <private-conf> -p <private-pid> -Ln`.
   `-C` prevents ambient config reads; the explicit config must include any private
   localized-state file needed for subsequent restart tests. Private persistence
   must stay enabled for this **agent** (unlike the short-lived collector clients).
   Bound overall campaign time, retain the owned process handle and verify the
   listener is loopback-only. Never start/stop another daemon or touch port161.
4. Choose an observed local interface's actual ifIndex/ifName (not invented counter
   values). A loopback interface can prove GET/auth/parser behavior but often reports
   unknown speed: rates should then be unavailable. Use an appropriate full-duplex
   interface with reported capacity if testing rates; agent collection remains
   read-only. Generate only explicitly authorized local traffic for delta tests.
5. For a transport-only test, call `NetSNMPTransport.get(binding, interface)` with
   `execution_mode=emulation`, `environment=emulation`, loopback target/1161 and the
   dedicated sysName. Keep results in the test process; do not publish using invented
   inventory identities. Record actual typed protocol responses, actual counter
   increments, auth/view denial, timeout and cleanup. A fixture-free local agent
   validates transport interoperability but does **not** establish physical fidelity.
6. For the composed API/CLI acceptance, provision an isolated existing inventory
   mapping and active authorized actor through owner contracts, then use this helper
   with disposable parent-provided sessions/Redis/ingestion. No authorization bypass
   or dummy owner callback is acceptable for the publication claim. Validate two
   observations and existing event/persistence consumers, scope denial and revocation.
7. Stop/reap only the owned child, remove private secret/state files and verify the
   owned socket disappears. Record outcomes and blocked rate cases honestly.
   Publication remains unexecuted; the local transport campaign below is complete.

### P2 review fix and real local SNMPv3 acceptance — completed 2026-09-19

**Review P2 fixed:** `MeasuredSNMPAdapter.poll` now invokes current owner authority
immediately before **each** `transport.get`, retaining pre-batch, post-batch, retry
and per-publication checks. The regression revokes authority during the first GET
of a two-interface binding and asserts only the first GET occurs, no publication
occurs, and neither pending nor previous state advances. In-flight reads are not
retroactively undone; a denied next check prevents the next external read.

Scoped verification after the fix:

```text
poetry run pytest tests/unit/test_measured_snmp.py tests/unit/test_snmp_composition.py --no-cov -q
100 passed
poetry run ruff check app/modules/telemetry/snmp.py tests/unit/test_measured_snmp.py \
  tests/unit/test_snmp_composition.py
All checks passed!
```

**Actual transport campaign: PASS.** At `2026-09-19T19:22:40Z`–`19:22:52Z`, a new
owned foreground `/usr/bin/snmpd` (Net-SNMP5.9.5.2) ran exclusively on
**`127.0.0.1:42351/UDP`**, an unused ephemeral high port selected immediately before
launch. The exact owned PID was **271245**. `/proc/<pid>/fd` socket-inode correlation
with `/proc/<pid>/net/udp{,6}` confirmed its only UDP listener was
`0100007F:A56F` (IPv4 loopback42351), not a wildcard or IPv6 socket.

- Launched with `-f -C -c <private-conf> -p <private-pid> -Ln`, isolated HOME,
  config and persistent directories under `/tmp/opencode`, 0700 directories and
  077 umask. Bootstrap config and client credential JSON were verified **0600**.
- Fresh randomly generated USM username/auth/privacy credentials, **SHA-256/AES**,
  `rouser ... priv -V measured` and only the documented read views. No SET request,
  write user, public community, shared configuration change or external-device poll.
- Agent argv/environment were checked credential-free. Agent stdout/stderr were
  discarded and client exceptions remained fixed diagnostic codes; secret config
  content and localized state were neither printed nor copied into evidence.
- The production `NetSNMPTransport.get` subprocess/parser path collected all ten
  required OIDs successfully. An acceptance-only subclass captured successful raw
  stdout after the actual `_execute` returned; it did not replace GET results.
  **No incompatible flags or missing IF-MIB objects were observed.**
- Bound observed interface **ifIndex1 / ifName`lo`**, expected sysName
  `nanfo-isolated-snmp`, with `execution_mode=emulation`, `environment=emulation`.
  Ephemeral UUIDs were used only to satisfy transport configuration shape; they
  were not claimed owner-validated and never published. No DB/Redis or Docker was
  used or mutated, and no owner-service authorization callback was bypassed for
  a publication claim. This was expressly transport-level acceptance.

Actual measurements (RX and TX happened to match for loopback):

| UTC observation | sysUpTime ticks | RX octets | TX octets | Derived interval | RX/TX rate |
|---|---:|---:|---:|---:|---:|
| 19:22:40.228868 | 10 | 133530918 | 133530918 | baseline | unavailable |
| 19:22:46.246830 | 612 | 133599207 | 133599207 | 6.02s | 90749.501661bps |
| 19:22:52.268073 | 1214 | 133667497 | 133667497 | 6.02s | 90750.830565bps |

Each interval included 64×1024-byte UDP payloads between two new owned ephemeral
loopback sockets, followed by a six-second wait. Actual total counter growth was
**136579 octets per direction**. These counters include IP/UDP and SNMP traffic,
and potentially other local traffic; they are not isolated traffic-generator
payload-goodput totals. `counter_rates` returned `baseline`, then `measured` for
both intervals. EngineBoots stayed1 and discontinuity stayed0. Measured request
durations were14.633ms,11.038ms,14.248ms.

The local agent reported `ifSpeed=10000000`, `ifHighSpeed=10`, i.e. **10Mbps nominal
loopback capacity**. Applying the adapter's speed formula gives about0.9075%
busiest-direction utilization. That denominator is agent-reported loopback metadata,
**not measured physical capacity**; no physical utilization calibration is claimed.

Negative cases all exercised actual authenticated/failed protocol requests:

| Case | Actual result |
|---|---|
| Wrong expected sysName | Rejected: `invalid_or_incomplete_snmp_response` |
| Wrong expected ifName for ifIndex1 | Rejected: `invalid_or_incomplete_snmp_response` |
| Correct USM username/privacy but newly generated wrong auth passphrase | Rejected: `snmp_request_failed`; no measurement returned |

**Cleanup verified:** terminated the exact owned process handle and awaited it
(exit0); no process-name kill or system-service operation. Removed the complete
private bootstrap/credentials/localized-state tree. Rebound/released UDP42351 to
confirm it was free. Independent post-run `ss` showed no listeners on161,1161,42351;
`systemctl show snmpd.service` still reported **inactive/dead/disabled**.

Credential-free evidence is retained at:
`/tmp/opencode/snmp-acceptance-h284yvhb/result.json`, with five actual typed stdout
transcripts `response-1.txt` through `response-5.txt`. The generated private tree
has been deleted. Temporary runner source: `/tmp/opencode/accept_local_snmp.py`
(contains secret generation logic, no credential values). This checked-in section
is the durable result summary if temporary artifacts are later removed.

Response SHA-256 (three counter observations, followed by the two identity-denial
responses; the failed authentication returned no retained stdout):

```text
1 e5dc2a4a74fa8a89030c121580d6658fe3753e74efa362bd98674209457513c4
2 00f1d3465ed03ee24ce2d94ac318e9ad35a01538c1e92f7f758e4ebc2817c1a7
3 29ccf9706c1f7d52c73b5ed1542390f2b01656324607fe993c4d757604063b88
4 d9dab0feb4e72cb9e53502e07fca2ef3a5b2fe13233f643ab18bef2eb318c80d
5 53ebf27a598ca17a51a8a37bfcc02c6c774b81bf31aa34ca3ca345aa61dda8d2
```

Remaining: integrated owner-authorized DB/Redis persistence/replay/websocket
acceptance, actual physical device/firmware compatibility and independent capacity/
traffic calibration, real reset/restart/speed changes, view-denial/missing-OID cases,
intended scale/freshness and deployment-image compatibility. The existing fixture
tests remain fixture evidence; this new campaign adds **real local SNMP transport**
evidence without upgrading those tests or the loopback device to physical acceptance.

## Configuration and secret handling

Illustrative binding (IDs and TEST-NET address are placeholders, not a runnable lab):

```json
{
  "version": 1,
  "org_id": "00000000-0000-4000-8000-000000000001",
  "workspace_id": "00000000-0000-4000-8000-000000000002",
  "network_id": "00000000-0000-4000-8000-000000000003",
  "device_id": "00000000-0000-4000-8000-000000000004",
  "actor_user_id": "00000000-0000-4000-8000-000000000005",
  "target": "192.0.2.10",
  "port": 161,
  "sys_name": "edge-switch",
  "interfaces": [{"if_index": 2, "if_name": "eth2"}],
  "execution_mode": "production",
  "environment": "physical",
  "timeout_seconds": 2.0,
  "max_interval_seconds": 120.0,
  "max_pending_seconds": 30.0
}
```

`production/physical` and `emulation/emulation` are the only valid mode/environment
pairs. Environment is an operator assertion, not automatic physical attestation.
Unknown fields, malformed/boolean numeric inputs, duplicates and nonfinite limits
fail validation. Only unicast IPv4/IPv6 literals are accepted (no IPv6 zone syntax).

Provision credential JSON from the configured secret manager into a private runtime
directory, outside source control. Fields are `username`, `auth_passphrase`,
`priv_passphrase`, optional `auth_protocol` (`SHA-256` default, `SHA-512`, or explicitly
selected legacy `SHA`), and `priv_protocol` (`AES` only). No v1/v2c, noAuth, MD5,
DES, downgrade or default credentials. Read-only USM/VACM rights must be configured
on the device by its owner. This adapter has no SET path.

Both binding and credential input files must be regular **0600**, owned by root or
the collector UID. Every path component is opened without following symlinks;
non-sticky writable ancestors and writable immediate parent directories are denied.
Files are bounded at 64KiB, duplicate JSON keys rejected. Secret strings are redacted
Pydantic values; supported single-token ASCII characters are
`A-Z a-z 0-9 _ . @ ! % + = : / -`, passphrases 8–128 characters, username 1–32.
Whitespace, quoting, backslashes, `#` and control characters are deliberately refused
to prevent net-snmp config directive injection. Provision compatible secrets rather
than escaping arbitrary config text. Rotation is loaded on each request.

Each request creates a private 0700 temporary directory and an exclusive 0600
`snmp.conf`; both are removed on success, failure and cancellation. Isolated HOME,
`SNMPCONFPATH`, `SNMP_PERSISTENT_DIR`, no MIBs, disabled persistent load/save,
disabled debugging and packet dumps prevent use of ambient credentials/configuration.
Secret values never enter argv, environment, output payloads, or logged exceptions.
The selected client executable is absolute, regular, executable, operator/root-owned,
and not group/world writable. Standard OS package directories must remain trusted.

The subprocess uses `create_subprocess_exec` with no shell, stdin closed, one GET
for ten fixed OIDs per interface, no client retransmissions, 0.1–10s transport timeout,
timeout+1s wall deadline, and independently capped 16KiB stdout/stderr pipes. It is
killed/reaped on timeout, overflow and cancellation. stderr and nonzero exit status
fail closed without printing either stream. At most 16 sequential requests make
a collection; no walk or unbounded table response. At the maximum request deadline
this can take 176s plus owner-service latency; choose poll/pending limits accordingly.
An early observation older than the pending TTL blocks the complete batch.
OS SIGKILL cannot execute cleanup: use a private ephemeral runtime/tmpfs and normal
service cleanup policy for abandoned 0700 directories; no secure-erasure claim.

## Measurement and counter contract

The numeric standard OIDs are sysUpTime, sysName, snmpEngineBoots, ifIndex, ifName,
ifHCInOctets, ifHCOutOctets, ifSpeed, ifHighSpeed and ifCounterDiscontinuityTime.
The exact queried OIDs are emitted by dry-run. All must be readable in the USM view;
missing/unsupported OIDs, wrong types, partial responses, duplicates, extra OIDs,
wrong names/indexes, malformed or out-of-range counters reject the entire cycle.
Counter32 fallback is intentionally absent: HC-counter support is required.

- Raw `port_rx_bytes` / `port_tx_bytes`: octets, `unit=bytes`.
- `interface_speed_bps`: ifSpeed in bits/s below saturation; saturated ifSpeed
  uses ifHighSpeed × 1,000,000 (RFC2863 Mbps). Zero/unknown capacity yields no rate.
- `port_rx_bps` / `port_tx_bps`: Counter64 delta × 8 / interval seconds.
- `throughput_mbps`: busiest direction in decimal Mbit/s.
- `link_utilization_percent`: `max(rx_bps, tx_bps) / speed_bps * 100`.
  This is **full-duplex/busiest-direction** utilization, not RX+TX or airtime.
  Scope initial acceptance to full-duplex interfaces; half-duplex/shared-media
  semantics require an explicit later contract. ifHighSpeed rounding remains a
  device-reported capacity approximation, not an independently calibrated line rate.

Interval is modular sysUpTime centiseconds, checked against local monotonic elapsed
time, request durations and 5%/1s tolerance. Wall-clock timestamp is local UTC at
response completion (not a device-provided UTC timestamp). First sample, restart,
discontinuity change, speed transition, stale/zero interval or inconsistent agent
clock yields raw measurements with a specific `rate_quality`; no fabricated zero
rate. Counter64 wrap is accepted only when modular delta fits speed × interval;
capacity also rules out multiple wraps. Decreases consistent with resets and
physically excessive rates are unavailable, not silently clamped to 100%.
sysUpTime wrap is supported with unchanged engineBoots and plausible elapsed time.
Agents must correctly expose restart/discontinuity semantics; nonconforming agents
that silently reset to larger values cannot be perfectly diagnosed from two samples.

All records use `source=measured_snmp`, `synthetic=false`, protocol/security/method,
mode/environment, scoped identities, binding digest, ifIndex/ifName, OID/capacity
provenance and rate-quality tags. `port_no` carries ifIndex for existing aggregation
partitioning. Raw Counter64 integers are also preserved as exact decimal strings in
tags: canonical ingestion persists numeric values as float, which cannot represent
every integer above 2^53. Rates are calculated from integers before that conversion;
interval start/end counters are included for independent reconstruction.

Pending observations and derived samples remain in memory until **all** publications
succeed. Retries recheck authority and replay identical event IDs; the existing
consumer idempotency contract handles partial publication. TTL expiry blocks the
retained batch rather than silently marking it fresh. Process restart loses pending
state and establishes a new baseline: **no durable outbox/crash recovery is claimed**.
Binding changes require restart; do not manually acknowledge an un-published batch.
CLI diagnostic acknowledges its own nonpublished samples solely to compute the next
diagnostic interval. Concurrent external polling/acknowledgment is unsupported.

## Verification and remaining acceptance

Tests use checked-in protocol-response transcripts and owner doubles, plus the
actual telemetry publisher with fake Redis. The transcripts are **hand-authored
protocol fixtures**, not recordings captured from a physical device. Subprocess
limit/cancellation tests launch only short local Python children, never an SNMP
agent, Docker, training or a real-device poll. See the fixture README for exact
values and limits.

Completed checks (2026-09-19, backend Poetry environment):

Follow-up API composition/configuration gate:

```text
poetry run pytest tests/unit/test_snmp_composition.py tests/unit/test_measured_snmp.py \
  tests/unit/test_config_dsn_safety.py tests/unit/test_telemetry_foundation.py \
  tests/unit/test_telemetry_scaffold.py --no-cov -q
203 passed

poetry run ruff check app/core/config.py app/modules/telemetry/snmp_composition.py \
  tests/unit/test_snmp_composition.py
All checks passed!
```

Tests cover legacy defaults/selectors, env-loaded paths/limits, protected-file and
mode failures, timing-budget admission, preflight authorization without a device
request, supplied dependency ownership, post-build revocation, real adapter guarded
publication, stable-ID retry after partial failure, redacted exceptions and deadline
cancellation. Initial composition lint flagged fixture-import shadowing; fixture
registration was corrected, and the final test/lint run above passed. API lifespan
integration remains parent's gate after its `main.py` wiring; no such runtime wiring
or local agent launch is implied by these isolated composition tests.

Earlier adapter/regression gate:

```text
poetry run pytest tests/unit/test_measured_snmp.py \
  tests/unit/test_telemetry_foundation.py tests/unit/test_telemetry_scaffold.py \
  tests/unit/test_telemetry_persistence.py --no-cov -q
145 passed (65 new measured-SNMP tests; 80 existing telemetry regression tests)

poetry run ruff check app/modules/telemetry/snmp.py \
  app/modules/telemetry/snmp_config.py app/modules/telemetry/snmp_transport.py \
  app/modules/telemetry/snmp_ownership.py scripts/collect_measured_telemetry.py \
  tests/unit/test_measured_snmp.py
All checks passed!

poetry run python -m scripts.collect_measured_telemetry --help
Passed; offline dry-run also covered by the tests.
```

An initial test run had one incorrect test import (`STREAM_KEY`) and 56 passes;
the test was corrected to the existing `stream:telemetry` contract, then regression
and additional failure cases passed. Manual protocol review corrected TimeTicks
handling to typed `-One` output rather than `-Ot`'s type-suppressing representation.
The final tests include continuous stdout/stderr flooding, bounded timeout and
cancellation/reaping, secret redaction/permissions/cleanup, tenant/device denials,
revocation between publications, partial-batch replay, counter and clock wraps,
reset/speed changes, capacity anomalies and real publisher/fake-Redis event checks.

Parent/integrated acceptance still required:

1. Provision the selected runtime image's Net-SNMP package, private credentials and
   binding from the configured secret manager; confirm SHA-256/AES support and
   the live device's **read-only** VACM view for all ten OIDs. Verify `/proc` argv,
   process environment and logs contain no credentials; verify runtime files 0600
   and temporary cleanup, including stop/kill policy.
2. In an authorized isolated physical lab, bind an existing active full-duplex device
   and interface through current owner services. Capture timestamped actual SNMP
   responses and inventory/ifName/IP mapping. Record device/firmware, client version,
   OID support, scope and clock uncertainty. Dry-run alone cannot pass this gate.
3. Collect at least three real intervals under idle and independently measured
   directional traffic; reconstruct integer deltas, time intervals, line capacity,
   bps/Mbps and busiest-direction utilization. Include a >4.29Gbit/s interface if
   claiming ifHighSpeed hardware compatibility. Compare against an independent
   device counter/traffic-generator record with a predeclared tolerance.
4. Exercise actual wrong-password/privacy/view, unreachable/timeout and missing-OID
   cases; confirm no fallback samples, plaintext errors or lingering children.
   Use controlled owner-approved counter-discontinuity/restart and speed-change
   cases; verify fresh baseline and recovery. Actual Counter64 overflow is normally
   impractical: retain the wrap fixture test as software evidence, not hardware proof.
5. In the real owning DB/Redis pipeline, deny cross-org/workspace/network bindings,
   wrong device/IP/name/index, inactive inventory and revoked actor/write membership;
   verify denial before transport or the next publication as applicable. Test
   revocation between samples and binding replacement during a pending batch.
6. Publish through `collect_and_publish`, verify persistence, exact event IDs and
   per-interface history/authorized websocket delivery. Interrupt Redis midway,
   retry within TTL and prove consumer deduplication; expire a pending batch and
   verify explicit block. Restart and demonstrate documented baseline/data-gap
   behavior, not a durable-recovery claim.
7. Verify intended poll cadence/resource use and freshness across the maximum
   intended interface/device count; parent owns scheduling/backoff/health integration.
   Obtain separate owner review before extending beyond default-context full-duplex
   IF-MIB devices or consuming these metrics in physical safety/autonomy decisions.
