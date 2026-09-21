# Current final receiver-health release — fixes9–11

2026-09-20. This is the current accepted image set. Earlier release narratives,
checksums, matrices and pins are retained as historical exact-source evidence.

| Gate | Passed | Failed | Blocked |
|---|---:|---:|---:|
| Final distributed/core/archive deployment |29|0|4|
| Complete deployment tests |216|0|0|
| Receiver-client focused regressions |31|0|0|
| Installed-image private-key/default/import smoke |20|0|0|
| Earlier packaged fleet functional evidence, reused with exact diff |6|0|0|

Four live matrix blocks remain optional lab binding, lab congestion, model diagnostic
and physical/measured telemetry survival. Synthetic archive fixtures are explicitly
separate. No default activation, authentic calibration, privileged receiver/FRR
execution, model qualification or training was performed.

## Current image IDs (linux/amd64)

| Runtime | Exact ID |
|---|---|
| Backend/API/workers/retention | `sha256:1e81845557780d170ad945929e3a993f8050660e1b5f658fc859a30c5fa9b053` |
| Fleet | `sha256:fac6029493690c0d60ee44117a393091aaa019b7dc579ac8784f2d86599007df` |
| Gateway | `sha256:4785f954f79dd113d2d0c4e07dfefec0e2cc1ac32ad50d24c7c4f0b1c602bf74` |
| Neo4j | `sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7` |
| PostgreSQL | `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3` |
| Redis | `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb` |

Net-SNMP snmp/libsnmp40/libsnmp-base remain exactly5.9.3+dfsg-2+deb12u1.
Snapshot `/tmp/opencode/nanfo-adr023-frozen-yvofvp9n`,984 files.329 installed runtime
files matched exact hashes as nonroot UID10001 for backend and fleet; zero source
drift. Locked dependency caches retained, changed runtime COPY layers rebuilt.

## Executed acceptance

From that frozen source, with2400s outer bound and bounded cleanup:

```bash
python deploy/verify.py --live --agents-idle --distributed --work-root /tmp/opencode
```

Private run `/tmp/opencode/nanfo-deploy-verify-e5vhtnkm` passed all29 runnable cases:
schema0027/runtime grants; leadership/delegated follower, takeover/rejoin; database
outage, stale heartbeat, restart; nonempty archive receipt-backed deletion; eleven
encrypted volumes; distinct fresh restore; exact archive/record bytes, historical
and ever-pinned retention, permanent tombstone replay rejection; assets/registration/
history; CSV/PDF/workflows; old-session denial; exact owned resource cleanup.

Source test commands:

```bash
# Repo root, existing backend environment:
/home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python -m pytest deploy/tests deploy/test_lifecycle.py -q
# backend/:
poetry run pytest tests/unit/test_receiver_health_review.py tests/unit/test_execution_client.py --no-cov -q
```

Installed-image smoke uses no network, read-only root, dropped capabilities and
private noexec tmpfs. Both production and emulation modes exercise10 cases each:
unconfigured/partial/missing-file providers unavailable; no privileged driver imports;
exact0600 random32-byte health key succeeds;0644/0640/0400, hardlink and digest mismatch
refused. Keys remain inside private temporary directories and are removed at exit.
The real key reader is tested directly without faking an independently validated
installation. Existing provider factory still reports uncalibrated/unavailable by
default and never starts a receiver. Source regressions cover post-roundtrip health
age and full configuration identity in addition to private-key boundaries.

## Precise fleet evidence reuse

`health-final-fleet-source-diff.json` records every added/removed/changed snapshot
path with old/new SHA256 relative to the successful fleet functional snapshot
`nanfo-adr023-frozen-sufx7teb` (image71b316...). Its103 explicitly checked fleet inputs
are byte-identical: Telemetry including SNMP/fleet/persistence, owning Identity/
Network/Organization paths, core/DB/event modules, fleet CLI, health CLI, dependency
locks, Dockerfile/package repository pins, entrypoint and base/fleet Compose.
Changed production files are autonomous execution/client/config/health/FRR contract
and receiver code plus optional journal overlays/verifier. Full path hashes are in
the JSON; this is scoped functional evidence reuse, not a claim of a new live fleet
campaign or physical fidelity. Current image package inventory and329-file installed
parity were rerun. Previous6/6 real-worker result remains in
`corrected-fleet-full-result.json` and is not overwritten or relabeled.

## Durable evidence and cleanup

- `health-final-summary.json`, `health-final-images.json`, full result/status matrices.
- Authenticated archive/pin/tombstone/assets checkpoint and encrypted-volume hashes.
- Exact source hash inventory, zero-drift record, build logs and resource ledgers.
- Installed smoke/probe source, current fleet build/package inventory, fleet diff.
- `health-final-release.json` and verified `health-final-distributed-evidence.tar`,
  trusted archive SHA256 and separate `health-final-checksums.json` catalog.

Earlier private backup from the prior journal release was hash-verified/authenticated
and relocated to ignored0700 workspace storage to retain tmpfs quota headroom. No
earlier public evidence was changed. All new containers/networks/volumes were cleaned;
shared services and caches remain. This narrative is separate from immutable catalogs.
