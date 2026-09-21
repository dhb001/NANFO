# ADR024 current source-matched deployment acceptance

Date:2026-09-20. Earlier ADR023 image pins/evidence remain historical and untouched.

| Gate executed in this workstream | Passed | Failed | Blocked |
|---|---:|---:|---:|
| Distributed/core/archive deployment |29|0|4|
| Complete deployment tests |216|0|0|
| Installed-image default/private-key/import smoke |20|0|0|
| Confined actual ADR024 raw-benchmark qualification |1|0|0|

Four deployment matrix blocks: optional lab binding, lab congestion, historical model
diagnostic and physical/measured telemetry survival. The additional confined ADR024
qualification is a separate gate, not a relabeling of historical diagnostic or fresh
observation readiness. Native autonomous activation and physical RF remain blocked.
No RF files/equipment were supplied. No new training, emulation/lab launch or privileged
native-driver action was performed by this deployment workstream.

## Current image identities (linux/amd64)

| Runtime | Exact image ID |
|---|---|
| Backend/API/workers/retention | `sha256:20fa671d52de4ca14f9fbbf83d993a019c49afd3471e67a720827e54b32a5ba1` |
| Fleet | `sha256:ff58e0c92eb0a3d5ba038efb0ea9c4c225fa04b972da0c29c0309175ff0b5d0b` |
| Gateway | `sha256:4785f954f79dd113d2d0c4e07dfefec0e2cc1ac32ad50d24c7c4f0b1c602bf74` |
| Neo4j | `sha256:d544f1ef8033ddfbf3a7cc81cdc1a73f90e503153202ea44d35f293bf43d9db7` |
| PostgreSQL | `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3` |
| Redis | `sha256:90e7a336d044f1abc9e9dbc05d65566850896d11453bbd1dd0fb7e5059f0e8fb` |

Snapshot `/tmp/opencode/nanfo-adr023-frozen-ei7ulj7m`,1003 files.341 installed runtime
Python files matched source as UID10001 for backend and fleet. Current production
source drift is empty. `changes-from-adr023.json` records exact old/new hashes.
Locked dependencies/cache retained; current runtime source copied into new images.
Net-SNMP packages remain5.9.3+dfsg-2+deb12u1. No new large AI deployment image was built;
the optional confined qualification used the existing independent host interpreter.

## Deployment configuration review

New optional JSON fields are **`accepted_service_semantics_sha256`** and
**`accepted_native_backlog_sha256`** in ExecutionClientConfig. They are not new
environment variables or dependency packages. Both default empty; absent empty
sets preserve earlier serialized config identity. Existing explicit protected
`NANFO_AUTONOMOUS_PROVIDER_CONFIG` plus SHA256 and read-only config/evidence/source
mounts already carry these fields. Therefore no Compose or default activation
change is required. Install only independently accepted exact evidence pins;
software v2 burst/clock mappings and native manual-driver readback are not enough
to manufacture service guarantees or a trusted autonomous installation.

Base providers remain unavailable; smoke checks in production/emulation verify
default/partial/missing config, private0600 key admission, unsafe modes/hardlinks/hash
refusal and privileged-driver import separation. No receiver or driver loop runs in
API/autonomy-worker. This campaign did not enable the optional autonomous overlay.

## Full deployment campaign

Executed from the frozen snapshot,2400s bounded outer command with cleanup allowance:

```bash
python deploy/verify.py --live --agents-idle --distributed --work-root /tmp/opencode
```

Private run `/tmp/opencode/nanfo-deploy-verify-5bv6nj_5`. Schema remains0027. All29
runnable cases passed: explicit fresh migration/grants, two-API leader/delegation/
takeover/rejoin, outage/stale heartbeat/restart, assets/registration/history, reports,
nonempty archive receipt-backed deletion, eleven-volume encrypted cold backup and
distinct fresh restore, exact archive/record bytes, historical and ever-pinned
retention, permanent tombstone replay rejection, old-session denial, cleanup.
Archive fixtures are labeled synthetic, not actual measured traffic.

All owned containers/networks/volumes removed, shared service identities preserved.
The immediately previous owned backup was hash-verified/authenticated before relocation
to ignored0700 private workspace storage to preserve tmpfs headroom; earlier evidence
was retained. No source changes were needed to pass this campaign. Independent
`ADR024CodeReview.md` reports approval/no required production changes; its tests are
attributed separately, not added to this workstream's counts.

## Actual confined qualified artifact gate

An existing unexpired offline installation was available at
`/tmp/opencode/nanfo-adr024-installation-check-3y1h6uhj/registry.json`, pinned SHA256
`fab4ca64ac70562167383aa96a100ea34da019f10768e0449767830a5ed8b610`.
Copied36 exact referenced model/source/parent/lineage/plan/audit/five-policy raw/report
files from `/tmp/opencode/nanfo-adr024-evaluation-002` into a private read-only root.
Registry bytes, scope and expiry were unchanged. No fake qualified flags or refreshed
measurement timestamps. Used the current frozen backend entrypoint and existing
`ai-engine/.venv/bin/python` with `-I -B`, Landlock/seccomp, no control/network access,
bounded150s outer deadline and original qualification thresholds.

Result: **PASS**, protocol `adr024-rebuilt-evaluation-v1`, actual checkpoint
`77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614`, parent
`5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5`, unchanged tensor
payload `3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967`.
Original copied/source hashes rechecked after completion. `execution=not_applied`,
`safety_authorized=false`, no live snapshot/action output. Registry expiry remains
2026-09-20T14:21:37.086929Z: this is point-in-time scoped benchmark validation, not
perpetual readiness. No current feed is installed, so fresh observer readiness and
native autonomy are **not ready**. It is not containerized with-AI acceptance.

Private result `/tmp/opencode/nanfo-adr024-deploy-qualification-f9o5h_18`; complete
credential-free receipt/input hash catalog and executed script are retained here.

## Attributed existing live evidence and limits

`attributed-continuous-*` copies the owning continuous-AI campaign result, original
qualification, cleanup and audit receipts from `nanfo-live-acceptance-7ngrbdgv`:
six real fresh frames, four durable recommendation-only decisions, two observations,
staleness/closure/RBAC checks and cleanup. This deployment work did not rerun that lab.
The native42/42 manual-driver evidence remains in `NativeDriverAcceptance.md` and
its owning archive; it is not full autonomous receiver/qualified-control acceptance.
Scoped benchmark PASS, actual recommendations and native readback do not establish
independent service bounds, physical RF calibration or native autonomous readiness.

## Evidence catalog

`summary.json`, `images.json`, full distributed result/status, source SHA256 inventory,
zero-drift record, build logs, authenticated archive/asset/pin/tombstone checkpoint,
resource ledgers, installed smoke receipt and scripts, confined qualification receipt
and immutable registry, attributed continuous receipts. `release.json` plus verified
`distributed-evidence.tar`; trusted archive SHA256 and `checksums.json` cover generated
evidence. This README is separate from the immutable generated checksum catalog.
