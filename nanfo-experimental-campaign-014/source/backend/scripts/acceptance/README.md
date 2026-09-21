# Step14 Acceptance (ADR019)

Latest actual run: [VALIDATION.md](VALIDATION.md), authorized live **partial** with
8 stage passes and zero remaining stage failures after documented root-cause fixes,
including separately measured alert success. Nine unimplemented physical/policy
cases remain blocked; initial failures are retained in hash-pinned supersessions.
The inventory below describes initial capability; measured alerts are now verified
by the standalone external verifier, not silently credited to the older primary run.

Approved exception: append
`--preserve-stopped-container 1db3c959ff4f712da1d9f5674c120c900f7d5392d2236f6f3d41f68f3620ac55`.
Only that exact ID/name in `exited` state is exempt from idle admission; complete
inspect state/config/image/mount hash must remain unchanged before/after every
stage. Mount set order is canonicalized. No global Compose command is permitted.
`--stages emulation --retry-of /path/to/prior/summary.json` selects an explicit
infrastructure-only retry, with new evidence and unchanged acceptance thresholds.

Scope: acceptance-owned scripts/tests only. No backend module, frontend, AI,
emulation source, deployment config, shared service or model artifact changes.
This runner does not establish production autonomy or general network fidelity.

## Operator Gate

**Do not run live while other agents are editing or using the lab.** Parent/operator
authorization must precede the command. `--agents-idle` is an operator attestation,
not automatic discovery of idle editors. The runner additionally requires unchanged
source/migration hashes over a quiet interval, one migration head `0019`, exclusive
campaign flock, successful system AND user service inspection, no active training/
backend/lab process, and no existing lab/verifier or privileged container (including
stopped containers). Unknown infrastructure is preserved, never stopped for admission.

From `backend/`, after explicit authorization and all agents/migrations are finished:

```bash
poetry run python -m scripts.acceptance.campaign --live --agents-idle \
  --overall-seconds 7200 --stage-seconds 1000 --quiet-seconds 30 \
  --historical-json ../ai-engine/artifacts/adr014-holdout-001/test-report.json \
  --historical-sha256 f323186fee013a3c55acac9e061500c2245c36976db01495a86f48a83c57392b
```

Use the backend Poetry interpreter, not an active AI environment. Both `--image`
and `--operator-image` accept immutable `sha256:...` IDs. Defaults select the existing
ADR018 capture-capable image
`sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c`.
No build, pull, retag, Compose config edit, or replacement of incumbent image aliases
is performed by acceptance code. Docker can fetch missing standard infrastructure
images when its ordinary `run` command requires them. Operator image availability
and compatibility remain pending live validation; never claim a newer tag supports
the manual/capture protocol without evidence.

The default overall cap is two hours (maximum accepted value), stage cap 1,000s
(maximum 1,200s). Admission reserves 180s; an independent overall alarm reserves 120s
for process-group termination, cleanup (90s deadline) and finalization. Processes
receive SIGCONT/TERM/KILL on their owned group, including surviving descendants.
OS/kernel or Docker-daemon failure can still leave an unknown resource; this is a
blocked cleanup, not a reason to delete other containers or claim success.

## Non-Live Commands

```bash
poetry run pytest scripts/acceptance/test_campaign.py -q --no-cov
poetry run ruff check scripts/acceptance
poetry run python -m scripts.acceptance.campaign --plan
poetry run python -m scripts.acceptance.campaign --status /tmp/opencode/step14-OWNER
```

`--plan` runs only the existing pure configured-fluid evaluator and optionally checks
the supplied historical JSON hash. It does not inspect/start Docker, services, APIs,
training, migrations or models. Plan exit 0 means the plan was produced, NOT accepted
network behavior. Live `partial` exits 2, `failed` exits 1. Any required blocked row
keeps the overall result `partial` even if other rows pass or fail. Counts expose both.

## Inspected Commands

The manifest contains exact child argv, source hashes, trigger descriptions and
environment variable names, never credentials. Each child runs
`python -m scripts.acceptance.stage --live --stage NAME --directory OWNED --owner ID --image SHA`.
Its private admission record must match. Stages execute serially.

| Stage | Existing Entry/Controls | Isolation And Compatibility |
| --- | --- | --- |
| emulation | `scripts/verify_emulation.py --live --timeout-seconds 600`; `traffic`, counters/persistence/queries/WebSocket | Calls existing `verify` under parent timeout; owned runtime paths and direct labeled Docker replace shared Compose lifecycle; dedicated PG/Redis/Neo4j; PG upgraded `0019` |
| execution | `scripts/verify_execution.py --live`; SIGKILL, missing receipt, deadline fault, DSCP workloads | Existing `verify` assertions retained; literal migration target and version assertion `0012` become `0019`; immutable image substituted; dedicated PG server encloses verifier-created disposable database |
| operator_override | `scripts/verify_operator_override.py --live`; six existing `CASES` | Existing `verify`, bubblewrap restrictions and physical checks retained; `0016` becomes `0019`; explicit operator image; own PG/Redis/Neo4j |
| actions | Container `python -m emulation.runner --verify-actions` | Existing lab-local real partial-operation/crash/deadline/uncertainty controls, isolated bind paths and labeled container |
| negative | Container `python /acceptance_negative.py` | Acceptance-owned harness uses existing `Lab`/`Actions`; actual link-down, controller SIGSTOP > freshness limit, controller SIGTERM/restart; reject preparation and verify absence/restored probes |
| reports | `python -m scripts.verify_reports --live`; actual PDF/CSV/download/worker | Existing `verify`; `0017` becomes `0019` for its main DB; dedicated infrastructure and report storage; existing disposable-schema tests still explicitly exercise `0017` |
| fixtures | `python -m pytest ... -q --no-cov` | Six reviewed files listed in `stage.FIXTURE_TESTS`; dedicated PG main DB at `0019`; existing alert/registry tests own randomized schemas at `0018`/`0019` respectively |

Migration/image adaptations compile an in-memory AST, never modify originals, and
record literal replacement counts and original source hashes. A missing expected
literal blocks the adapter. This is necessary for shipped verifiers tied to earlier
schema/image versions, not a weakened assertion or backwards-compatibility API.

Report tests receive `REPORT_TEST_DSN` and `REPORT_TEST_REDIS_URL` pointing only to
their verifier-owned services. Fixture tests receive `ALERT_TEST_DSN` and
`PLUGIN_TEST_DSN` for the acceptance-owned PostgreSQL server. Inherited environment
and `.env` service/path values cannot select shared targets. Fresh random credentials
travel through private environment/config, not argv or published evidence. Pytest
XML is bounded, parsed for counts, then removed. Any skip/failure/error or zero tests
prevents acceptance success, even if pytest exits 0. Test schemas intentionally retain
their existing migration-specific tests; application verifier DBs use `0019`.

## Evidence Inventory

| Requested Case | Available Evidence Path | Limit |
| --- | --- | --- |
| low/ramp/burst/overload | Generated pure configured-fluid counterpart | Physical rows blocked; existing learning workloads are not silently reused as a new reserved-test campaign |
| multiple bottlenecks | Three-link configured-fluid chain | Physical blocked; multipath traffic is not multiple independent bottlenecks |
| link failure | Acceptance negative harness, real Mininet link down/up | Proposal rejection/readback and recovered probes, not routing convergence superiority |
| stale | Controller SIGSTOP for 8s | Real stale controller topology guard, not a forged old telemetry timestamp |
| disconnect | Controller terminated and restarted | Not Redis/WebSocket outage or network partition certification |
| restart | Execution worker SIGKILL/lost result; operator actual lab restart | Exact command/proof recovery, no re-execution |
| unsafe | Existing expired-publication, competing-policy and uncertainty rejection | Real lab guard, NOT DRL+safety certification |
| override | All six existing expiry/STOP/capture/labrestart/revocation cases | Isolated manual lab only |
| rollback | Existing partial mutation/death/deadline/late cancellation tests | Readback plus real traffic; uncertainty remains fail-closed |
| traffic classes | DSCP10 shape, DSCP12 police, unclassified and restored traffic | Configured fluid multi-flow counterpart does not model DSCP priority |
| larger topology | Generated 33-node/32-link configured-fluid chain | **Measured larger topology blocked** |
| reports | Real bytes/API/worker from existing report verifier | Source rows are fixtures, not new measured network telemetry |
| alerts | New detector/consumer/unit and disposable DB tests | **Measured sustained lab detection/recovery blocked**, separate `alerts_fixture` row |
| registry | New registry unit/DB races | Metadata-only, not package execution |
| DRL alone | Read-only historical heldout JSON plus expected SHA256 | Integrity reference only, no inference/test rerun or new superiority claim |
| DRL+safety | Blocked | Compatible providers/calibrated bounds absent |
| repeated heldout | Blocked | No separately predeclared repeat acceptance protocol admitted; no training/tuning/testing |
| physical power control | Blocked | No physical measurement/driver installed |

Every row has state `passed`/`failed`/`blocked`, evidence kind
`measured`/`modeled`/`unit`/`historical`, version, input/fixture SHA256, evidence
references, comparator scope and nullable metrics with units/count/raw reference.
`unit` includes explicitly fixture-backed transaction tests; it never means measured
traffic. No unavailable RTT/PDR/goodput is replaced with zero, and port counter rate
is not mislabeled as application goodput. Raw modeled traces conserve offered bytes
as delivered + dropped + queued + in-flight independently at every batch/flow.
Model gate success is arithmetic validation, not network-fidelity validation.

## Cleanup And Recovery

Each attempt creates an exclusive mode-0700 `step14-<random>` directory. Files are
exclusive mode-0600 and fsynced; no prior output is overwritten. `manifest.json`,
`summary.json`, modeled artifacts and a hash-chained `event-*.json` ledger provide
durable read-only recovery via `--status`, including interrupted/running stages.
Status recovery never replays mutations. A later authorized run is a fresh attempt
with a new directory and baseline, not a blind continuation of an unknown live lab.

Before Docker creation, a stage records an exact randomized name. Every container
also receives owner+stage labels. Cleanup requires ALL of: full ID absent from the
pre-stage snapshot, registered exact name matching the approved verifier prefix,
matching owner and stage labels, and a fresh exact-ID inspection. Only those IDs
receive `docker rm -f -v`. No broad `rm`, prune, Compose down, user process kill,
shared database reset, or prefix-only container cleanup exists. Unknown IDs survive
and block later stages. Baseline container name/image/state/approved labels are
checked again after cleanup; unrelated service data is never modified.

Child failures continue to later stages only after verified cleanup and another
unchanged-source/service/baseline check. Timeout-killed child verifiers may not reach
their own `finally`; the parent removes only proven owned containers/anonymous
volumes and the exact known credential/XML files. Bind evidence remains; root-owned
lab journals are deliberately not recursively removed. A host crash/SIGKILL of the
parent cannot execute cleanup; inspect the durable ownership records, preserve
unknown resources and obtain operator review instead of broad cleanup.

Raw process stdout/stderr is bounded and discarded. `process-log.json` retains only
exit/timeout/byte-count facts. Published result fields are sanitized; controller
stack logs, SQL exceptions, tokens, passwords and DSNs are not exported. Docker
inspection excludes `Config.Env` and arbitrary labels.
