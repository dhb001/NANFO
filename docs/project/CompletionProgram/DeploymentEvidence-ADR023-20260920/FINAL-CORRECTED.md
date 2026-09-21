# Final corrected-image acceptance

Date:2026-09-20. This is the current release result; the original README and matrices
are retained as historical evidence, including the now-resolved Net-SNMP blocker.

| Gate | Passed | Failed | Blocked |
|---|---:|---:|---:|
| Corrected distributed/core/archive campaign |29|0|4|
| Packaged Net-SNMP SHA-256/AES transport |1|0|0|
| Packaged full fleet CLI |6|0|0|
| Exact pinned fleet package build/inventory |1|0|0|

The four distributed blocks remain optional lab binding, lab congestion, historical
model diagnostic and physical/measured telemetry survival. Actual synthetic archive
fixture survival is independently passed, never counted as measured traffic. No live
FRR launch, model qualification, autonomous actuation or training occurred.

## Final images (linux/amd64)

| Runtime | Exact image ID |
|---|---|
| Backend/API/workers/retention | `sha256:312ac3ca2be31f79858c2f49d27c7aca410e04542978b7445b3d0e13f28899a4` |
| Fleet | `sha256:71b31676560195b54b5480507c71c857f064ebaa7cb3f0f793e2fcd8080c9e5a` |
| Gateway | `sha256:4785f954f79dd113d2d0c4e07dfefec0e2cc1ac32ad50d24c7c4f0b1c602bf74` |
| Neo4j | `sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7` |
| PostgreSQL | `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3` |
| Redis | `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb` |

Acceptance-only SNMP derivative: `sha256:1e28594b60848453be3221182c4808a76b186e34e7e71835e6270085138395d6`.
Full-worker derivative: `sha256:94ea3f41311b80b51105b647cd76a67cf38f9c6db9ed780bda0bc1c2bf11fdb8`.
These add snmpd/probes only, not altered backend/fleet behavior. Fleet inventory:
snmp/libsnmp40/libsnmp-base all exactly `5.9.3+dfsg-2+deb12u1`.

## Scope and reproduction

Frozen snapshot `/tmp/opencode/nanfo-adr023-frozen-sufx7teb`,975 files. Installed
UID10001 hash/readability checks cover324 runtime Python files; fleet parity also
passed324. `final-distributed-source-drift.json` is empty. Includes the final FRR
authority correction as source; no live authority/calibration claim follows.

Executed from the snapshot:

```bash
python deploy/verify.py --live --agents-idle --distributed --work-root /tmp/opencode
```

Final private run `/tmp/opencode/nanfo-deploy-verify-b_fzalg0` completed all29 runnable
gates: fresh0027 initialization, leadership/delegation/takeover/rejoin, outage/restart,
nonempty archive receipt-backed deletion, eleven-volume encrypted cold backup,
distinct fresh restore, exact578-byte archive and row restoration, permanent
tombstone replay rejection, retained historical/ever-pinned records, assets and
registration/history, reports/workflows and old-token denial. Every owned resource
was removed by exact campaign identity. Shared services were unchanged.

Full fleet runner/probe sources are preserved in `corrected-adr023_fleet_full_run.py`
and `corrected-fleet-full-probe.py`. The real `scripts.run_fleet_collector` CLI runs
against direct PostgreSQL and Redis on a new internal Docker network with no host
ports. Two actual private loopback snmpd processes use random protected0600 credential
and binding files; the third target deliberately pins the wrong sysName. Read-only
container filesystem, dropped capabilities and private writable tmpfs were used.
Collection/persistence produced12 measured records with owning-service deduplication.
Bad-third degraded health, healthy two-target manifest, SIGSTOP staleness,
SIGKILL/restart and current actor revocation were verified. Agent/worker children,
containers, network, ephemeral DB and secrets were removed. This is CLI/process and
owner-persistence acceptance, not deployed API consumer/fanout, physical firmware,
or an injected ambiguous-ack crash test. No fake authorization boundary was used.

## Retained failures and storage correction

`corrected-distributed-result.json` is the earlier **19pass/2fail/12blocked** run:
backup creation completed but independent authentication hit `OSError122 EDQUOT`
while decrypting Neo4j's archive on tmpfs. `df` had reported free capacity. No
application change was needed. Exact earlier owned backups/keys were copied to
ignored private workspace storage, hashes verified, authenticated, then removed from
tmpfs with location pointers retained. The old public evidence was never replaced.
`private-backup-relocation-summary.json` records scope. The final repeat used the
same source and image IDs and passed backup authentication and fresh restore.

`corrected-fleet-attempt1-result.json` is a probe harness parsing failure: structured
worker log lines precede final CLI JSON. Parsing its final line fixed the harness;
application code did not change. Final six proofs are in
`corrected-fleet-full-result.json`; successful transport in
`corrected-snmp-result.json` supersedes earlier `fleet-net-snmp-failed.json`.

## Evidence index

- `final-acceptance-summary.json`, `final-images.json`, `final-distributed-result.json`.
- `final-distributed-authenticated-checkpoint.json`: archive/pin/tombstone and asset
  integrity projection, authenticated from the private cold-backup manifest.
- `final-distributed-evidence.tar`: verified portable evidence export using
  `corrected-release.json`; trusted digest in `final-distributed-archive-sha256.json`.
- `corrected-checksums.json` and `final-checksums.json` cover their respective appended
  generated evidence sets; earlier `checksums.json` remains unchanged. This narrative
  is separate from the immutable generated catalogs.
- Prior singleton core28pass/0fail/5blocked evidence remains scoped to its original
  image; the corrected image is accepted by the full distributed campaign.
