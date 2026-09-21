# Step13 Live Measured Alerts

Latest attempt after blocker fixes: `--live --slot-released` returned
`parent_campaign_lab_slot_busy` before resource creation. Parent owns the current
run; no lock bypass or live measurement claim. The explicit preservation option
`--preserve-stopped-container` accepts only a full64-character ID and verifies the
stopped container's exact ID/image/state remains unchanged. It never starts, stops,
removes, renames or mounts that container. Approved parent invocation after release:

```sh
PYTHONPATH=.:.. /home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python -m scripts.verify_measured_alerts --live --slot-released --timeout-seconds 480 --preserve-stopped-container 1db3c959ff4f712da1d9f5674c120c900f7d5392d2236f6f3d41f68f3620ac55
```

**Prepared, not live-run.** The parent acceptance campaign currently owns the lab
slot. Do not launch until the parent explicitly releases it. This verifier does
not modify the campaign or bypass its lock. No measured acceptance is claimed by
preparation tests.

## Parent Commands

Run from `backend` using the backend interpreter, not an activated AI environment:

```sh
PYTHONPATH=.:.. /home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python -m scripts.verify_measured_alerts --plan
```

Only **after** parent slot release:

```sh
PYTHONPATH=.:.. /home/DHB/.cache/pypoetry/virtualenvs/nanfo-backend-9hkWDLkY-py3.14/bin/python -m scripts.verify_measured_alerts --live --slot-released --timeout-seconds 480 --image sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c
```

The immutable image must already be installed. No pull, build or retag is done.
Other machines should substitute their backend Python path. Required imports are
checked before service creation, including actual report dependencies `reportlab`
and `pypdf` needed by the migration0019 application composition.

`--output-parent` defaults to existing `/tmp/opencode`; a new private
`measured-alerts-*` child is always created. `--timeout-seconds` accepts 240..900.
`--plan` is read-only and requires no Docker. `--live` also requires
`--slot-released`; it then takes a nonblocking exclusive flock on the exact campaign
inode `/tmp/opencode/nanfo-step14-lab.lock`. Busy means exit2 without creating
infrastructure. The lock file is never unlinked. A parent invoking this as a child
must **release its own lock first** and remain idle until the child exits; there is
no inherited-lock bypass. Campaign source fingerprinting must admit this new source
on a new attempt rather than silently modifying an active frozen campaign.

## Measured Stage

- Create only UUID-named, labeled disposable PostgreSQL16, Redis7, Neo4j5.25 and
  the pinned privileged `--network none` campus lab; migrate only disposable DB
  through0019. No production/shared database, stream, graph, image alias or lab
  state is changed.
- Start the actual application with its real shared event handlers in a separate
  Bubblewrap process. Its runtime telemetry adapter is explicitly empty `stub`,
  never seeded. Bind a real active operator and inventory through authenticated
  public APIs. A second Admin belongs only to a second organization/workspace.
- Start the separate actual Alert outbox worker and a two-second collector child.
  All backend children run under the backend Python with read-only root/source,
  private PID/user namespaces and no Docker socket. Only the collector's evidence
  subdirectory is writable. Its actual snapshot write-denial is checked.
- The collector calls the shipped `_build_emulation_adapter`, validates current
  Network binding owner, and uses real `TelemetryCollectorRunner.ingest_once` ->
  Redis -> `handle_telemetry_event` -> persisted Alert detector. No fake clock,
  supplied metric values, fixture import or ORM alert/metric insertion exists.
- Predeclare `access1`, DPID0000000000000004, port1, capacity20Mb/s. Only this
  utilization series is published, avoiding unrelated probe alerts. The adapter
  still validates the entire real source snapshot; every derived sample is checked
  independently by `verify_emulation.verify_measurements`.
- Verifier-only fixed Docker exec enters h1/h3 namespaces in its **owned** lab.
  Foreground iperf3 sends22Mb/s UDP for30s over the configured20Mb/s path, while
  the independent collector continues polling. No shell/user command interpolation,
  API Docker access, control mailbox or synthetic measurement is used.
- After iperf exits, collect18s of actual recovery. Require exactly one incident
  with exactly2 immutable history transitions: measured generation and measured
  recovery for the same tenant/network/device/port/run. Both must span10s with
  >=3 original observations and gaps<=10s. Breach>=85%, recovery<70%; defaults
  cannot be retuned to obtain acceptance. Recovery must follow real workload stop.
- Cross-check every persisted value, timestamp, tag and observation ID against
  the independently verified source batches. Replay original event envelopes
  twice in reverse timestamp order; require unchanged history/count/incident.
  This is duplicate/out-of-order **delivery of real original observations**, not
  fabricated UUIDs, measurement values or timestamps.
- Verify owner list/history, outsider empty list and403 detail/history/ack/resolve.
  Require outbox delivered and the2 actual audit IDs identical to history IDs.

## Evidence And Cleanup

Stdout returns only status and result path. Exit0 requires all assertions and owned
cleanup; exit2 is blocked/failed, never a partial green. `plan.json`, `result.json`,
`alerts.json`, `history.json`, `telemetry.json`, `iperf.json`, and private collector
batch files retain credential-free actual evidence. `collector/snapshot-<sha>.json`
contains the **original producer bytes** used by the adapter, with byte count/hash
references in each batch. `runtime-proof.json` records the collector boundary.

Secrets live only in isolated child environment and a0600 Redis configuration that
is removed during cleanup. Passwords/tokens/DSNs and raw server exceptions are not
included in evidence. Binding contains inventory/actor IDs, not credentials.
SIGINT/SIGTERM cancels into owned cleanup; UUID names plus ownership labels prevent
removing borrowed containers. A hard SIGKILL cannot guarantee cleanup: parent must
use `owned-*.json` plus the matching label to inspect/remove only this attempt's
resources. Reserve at least150s beyond the run timeout for cleanup before launching
another lab stage. No actual run was performed during implementation.

Preparation tests (no lab):

```sh
poetry run pytest tests/unit/test_verify_measured_alerts.py tests/unit/test_verify_emulation.py -q --no-cov
poetry run ruff check scripts/verify_measured_alerts.py tests/unit/test_verify_measured_alerts.py
```

Preparation verification:26 targeted tests passed; full backend2,022 passed with77
opt-in skips; scoped Ruff and whitespace checks passed. `--plan` was executed and
reported `prepared_not_run`, `live_capture=false`. No live command, Docker operation
or workload was launched by this implementation turn. Live startup/throughput and
recovery remain unverified until the parent grants the slot and invokes the command.
