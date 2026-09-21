# Latest journal-client deployment acceptance

2026-09-20. This release includes the final optional journal-only provider factory.
Previous README, FINAL-CORRECTED.md, matrices and image evidence remain historical
records of their exact releases; this file identifies the newest accepted images.

| Gate | Passed | Failed | Blocked |
|---|---:|---:|---:|
| Complete deployment source/tests |216|0|0|
| Latest distributed/core/archive live campaign |29|0|4|
| Installed-image fail-closed provider factory |6|0|0|
| Fleet pinned package build +327-file runtime parity |passed|0|0|

Four blocks: optional lab binding, lab congestion, model diagnostic and physical/
measured telemetry survival. No authentic provider installation was supplied, so
calibrated actuation remains unavailable. Synthetic archive fixtures are never
relabeled as measured traffic. No privileged FRR/receiver or training was launched.

## Latest images — linux/amd64

| Service | Exact image ID |
|---|---|
| Backend/API/workers/retention | `sha256:e75fa2bdc7f1c0b6c646e0bc0514bed2c808dca268655e4340b2b9b62e504282` |
| Fleet | `sha256:13be46a557ecb7ea22d6d7f0de2e0792b68b44db3021cf1df99ee4971d509702` |
| Gateway | `sha256:4785f954f79dd113d2d0c4e07dfefec0e2cc1ac32ad50d24c7c4f0b1c602bf74` |
| Neo4j | `sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7` |
| PostgreSQL | `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3` |
| Redis | `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb` |

Fleet snmp/libsnmp40/libsnmp-base remain exactly5.9.3+dfsg-2+deb12u1. Frozen source
snapshot `/tmp/opencode/nanfo-adr023-frozen-0bco__84`,981 files.327 installed runtime
Python files match the source and are readable as UID10001. Source drift is empty.
Locked dependency caches were reused; runtime COPY layers and downstream fleet
packaging were rebuilt with pinned bases/packages. Earlier tags were not overwritten.

## Optional configuration

Added `compose.autonomous-client.yaml` for API/autonomy-worker and
`compose.distributed-autonomous-client.yaml` for api2. Exact settings:
`NANFO_AUTONOMOUS_PROVIDER_CONFIG=/var/lib/nanfo/autonomous-config/provider.json`
and mandatory explicit `NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256`.
Protected read-only non-autocreated config/evidence/source directory mounts only;
base Compose has neither settings nor mounts. Service commands, image, execution
mode, UID and dropped capabilities are unchanged. No driver/namespace attachment,
receiver service, privileged execution or executor run loop is added to API/worker.
Full operator installation instructions are in DeploymentADR023.md.

Installed-image probes exercised the actual provider factory in production and
emulation for unconfigured, partial-hash and missing-file configuration. Executor
stays unavailable; default safety remains uncalibrated, invalid-config safety becomes
unavailable. JournalExecutionClient has no run method. The Python dependency graph
does import `emulation.autonomous_frr` definitions; importing definitions is not
instantiating a driver, attaching a namespace or running commands. The probe records
this accurately. Two initial probe assertions were corrected (default safety enum
and module import expectation); no production changes were made to satisfy them.
No synthetic trusted installation was introduced. Genuine provider/receiver activation
remains an external prerequisite rather than a passed deployment claim.

## Live acceptance and retention

Executed from frozen source with2400s outer timeout plus bounded cleanup:

```bash
python deploy/verify.py --live --agents-idle --distributed --work-root /tmp/opencode
```

Private run `/tmp/opencode/nanfo-deploy-verify-fnh8dvek`: all29 runnable cases pass,
including schema0027/runtime grants, both APIs, delegated follower readiness,
leader-stop/gateway takeover/rejoin, database outage, stale heartbeat, worker/API
restart, assets/history/registration, CSV/PDF, one eligible archive-backed deletion,
eleven-volume encrypted backup/distinct fresh restore, exact578-byte archive/record,
retained historical/ever-pinned rows, tombstone replay rejection and old-token denial.
The optional calibration overlay was not live-enabled without authentic assets.
All newly owned containers/networks/volumes were removed. Shared services unchanged.

The prior successful corrected-run private backup was hash-verified and authenticated
before relocation to ignored0700 `deploy/state/adr023-private-evidence` to preserve
tmpfs quota headroom; exact earlier public evidence remains unchanged. No repeat
quota failure occurred. Prior full fleet collection6/6 remains scoped to its prior
image; latest fleet validates package/source parity, not a new full collection run.

## Evidence

- `journal-summary.json`, `journal-images.json`, `journal-distributed-result.json`.
- `journal-distributed-authenticated-checkpoint.json`, source hashes and zero-drift
  record, build logs and exact cleanup ledgers.
- `journal-installed-factory-checks.json`, executed probe scripts and fleet parity.
- `journal-release.json`, `journal-distributed-evidence.tar` (verified export),
  trusted archive SHA256 and `journal-checksums.json` for this appended generated set.
- Complete deployment tests216passed, scoped Ruff and whitespace checks passed.

This narrative is separate from immutable checksum catalogs. All previous evidence
sets are retained; no physical qualification is inferred from software acceptance.
