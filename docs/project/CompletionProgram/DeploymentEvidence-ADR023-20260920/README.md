# ADR023 source-matched deployment acceptance — 2026-09-20

| Campaign | Passed | Failed | Blocked | Result |
|---|---:|---:|---:|---|
| Core singleton | 28 | 0 | 5 | Core gates passed |
| Distributed two-API | 29 | 0 | 4 | Core and leader failover gates passed |
| Optional fleet image/package inventory | 1 | 0 | 0 | Exact pinned packages built |
| Optional packaged Net-SNMP transport | 0 | 1 | 0 | Runtime incompatibility reproduced; fleet admission blocked |

Both verifier matrices contain33 cases. Core's five blocked cases: optional
distributed failover, lab binding, lab congestion, model diagnostic, measured telemetry
survival. Distributed passes failover and has the other four blocked. No privileged
FRR/lab or model qualification was launched. `step15_complete=false` and
`all_green=false` remain intentional. The verifier exits1 for incomplete Step15 even
when `core_passed=true`; results must be read from the matrix, not exit status alone.

## Executed source and commands

Snapshot: `/tmp/opencode/nanfo-adr023-frozen-cwfy3yhl`,974 files.
Runtime source fingerprint:
`06e3e96baf1b632dc3a7b2a5b420f4bbab03cd07fc0c400c344860539ab54706`.
324 installed Python runtime files matched hashes and were readable as UID10001
before initialization. Both campaigns used the same frozen bytes and identical image
IDs. Locked Poetry/npm stages used available caches; no global pruning or retagging
of previous evidence images. Serial `docker build` supports the installed legacy
builder without buildx; datastore pulls were missing-only.

Executed from the snapshot, each with an outer2400s timeout and150s termination
cleanup allowance:

```bash
python deploy/verify.py --live --agents-idle --work-root /tmp/opencode
python deploy/verify.py --live --agents-idle --distributed --work-root /tmp/opencode
```

Core private run: `/tmp/opencode/nanfo-deploy-verify-d_iukq6u`.
Distributed private run: `/tmp/opencode/nanfo-deploy-verify-ui7t5pi2`.
Private backup keys, credentials, encrypted full data backups and unfiltered driver
logs are not published. Authenticated checkpoint projections, source hashes, build
logs, exact matrices, typed resource ledgers and verified portable evidence archives
are published here. `checksums.json` covers the generated evidence files; this README
is the narrative index. `release.json` uses an export-safe source subset; complete
inventories remain in `core-source-sha256.json` / `distributed-source-sha256.json`.

## Images (linux/amd64)

- Backend/API/workers/retention: `sha256:3b88dd14d4045d263f6dbc051f9abdd6abdc9a03861d4152014eab95f111f2b3`
- Gateway: `sha256:4785f954f79dd113d2d0c4e07dfefec0e2cc1ac32ad50d24c7c4f0b1c602bf74`
- Neo4j: `sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7`
- PostgreSQL: `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3`
- Redis: `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb`
- Optional fleet: `sha256:ebb2f22d0226ea88ad36b2fe467a28b751f851216bb8310f825deeaec55db6de`

## Archive and restore proof

Each campaign reconciled all five owners through the real bounded CLI, retained one
pre-enrollment record and one released-but-ever-pinned record, and archived/deleted
exactly one eligible post-enrollment record. The578-byte canonical archived record
was checksum/identity validated before backup and after distinct fresh restore.
Eleven encrypted named volumes include telemetry archive, DB receipts, one permanent
tombstone, one pin, five coverage and five reconciliation entries. Their authenticated
hashes matched on restore. Scoped CLI restore recreated the exact record bytes;
replayed old event ID was rejected both before and after row restoration. These are
explicitly synthetic deployment fixtures, not measured traffic or physical evidence.

Both runs also preserved a61-byte model asset, registration, spatial history,
CSV/PDF reports and workflows; revoked old login sessions; tested actual database
outage, SIGSTOP stale heartbeat, API/worker restart and cleanup. Distributed additionally
proved one leader/one delegated follower, stopped the leader, served through the
promoted follower and rejoined the old API, then backed/restored both-API composition.
Multi-socket correctness remains the owning distributed integration test's scope.

## Fleet limitation reproduced in the packaged runtime

Net-SNMP `snmp`, `libsnmp40`, `libsnmp-base` all installed exactly
`5.9.3+dfsg-2+deb12u1` from signed pinned snapshots. An acceptance-only derivative
installed matching `snmpd`; it ran nonroot with no capabilities, read-only root,
private tmpfs and `--network none`, binding only its container loopback1161.
Fresh random SHA-256/AES credentials remained private and were removed with tmpfs.

The unchanged backend transport rejects every fresh-request stderr. Debian Net-SNMP
prints `Created directory: /tmp/nanfo-snmp-.../cert_indexes` during initialization,
even with exit0 and a436-byte successful SNMP response. Thus installed
`NetSNMPTransport.get` returns `snmp_request_failed`. A diagnostic reproduced the
exact stderr; it did not suppress it or claim transport acceptance. Required owner
fix: create the private certificate-index directory before spawning (or another
reviewed equivalent), retaining strict error handling and credential protection.
Rebuild the small fleet runtime and rerun packaged transport/fleet collection after
that backend change; do not repeat unrelated core/archive baselines solely for it.

Fleet leasing/spool/ingestion/heartbeat acceptance through the image profile remains
blocked by this transport failure. No production target was contacted. The legacy
builder traversed the earlier with-AI stage during fleet build, installing cached/
locked dependencies only; no inference, qualification or training ran.

## Preserved attempts and cleanup

- Attempt1:3passed/2failed/28blocked, missing buildx in Compose build path; no services.
- Attempt2:3passed/2failed/28blocked, freezer mistakenly excluded frontend source
  directory named `state`; corrected exclusion to `deploy/state/` only.
- Attempt3:6passed/2failed/25blocked, frozen directories inherited0700 and were copied
  unreadable to UID10001. Corrected snapshot source directories to0755 and added full
  installed runtime hash/readability gate. No backend application fix was required.
- Final campaigns passed all requested core gates. Their exact owned containers,
  networks and volumes were removed by the verifier. Two failed legacy frontend
  builder containers were identified by exact IDs/commands and removed. Optional
  SNMP probe containers were removed. Earlier shared containers and caches remained.
- Post-freeze source changes are test fixes plus AST-equivalent parentheses in the
  host verifier; no shipped runtime bytes changed. Drift records and the exact
  executed verifier are included. Scoped final verifier/deployment tests:86passed;
  prior complete deployment suite211passed. Scoped Ruff/whitespace checks passed.
