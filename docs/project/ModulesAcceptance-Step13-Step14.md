# Steps 13-14: Modules and Acceptance Outcome

## Status

Step13 reports and measured alerts are implemented and verified; plugins are an
explicit metadata-only registry with uninstall, not executable extensions. Energy
is a configured estimate only, not physical power control. Step14 is PARTIAL:
22 cases passed,0 failed after fixes/retests,9 physical/policy cases remain blocked.
Do not turn an incomplete acceptance matrix into an overall green release claim.

## Delivered Modules

- Real CSV/PDF rendering, bounded frozen service-owned source reads, verified
  artifact bytes/hash/size, durable rendering leases/outbox, current-owner download
  and paginated history. UI checks downloaded bytes and clearly reports omissions.
- Measured utilization/RTT/probe-loss/queue threshold incidents, durable hysteresis/
  minimum sample-span state, tenant/resource/run dedup, watermark/replay protection,
  immutable lifecycle history, outbox, ack/resolve and source-correlated recovery.
- Current binding authority and observation freshness rechecked after lock waits;
  legacy keys are scope-isolated and suppressed generation receipts persist so old
  replay cannot resurrect resolved incidents.
- Metadata-only plugin states and declaration validation, conflict detection,
  authorized soft-uninstall/audit and identical reinstall. No fake crypto or sandbox.
- Standalone bounded energy estimate CLI with explicit wattage assumptions,
  connectivity validation and negative savings preserved. Output model_only=true,
  physical_control=false, guaranteed_savings=false. No power-saving actuation claim.

## Live Acceptance

Final aggregate:
`/tmp/opencode/step14-7a3aa518d6da241690b38153bcd1716d/aggregate-final-retest.json`
SHA256:`8289430824f59f2ffc457d76fb6188f5a5711859acdd78aa45604c1e622786bb`.
Eight capable stages passed. Counts distinguish measured, modeled, fixtures and
historical hash checks; not all22 passes are physical network experiments.

- Telemetry:2,178 unique source/persisted/WebSocket observations matched, zero
  duplicates, zero backlog at drain,9nodes/11edges.
- Execution:real reroute/multipath/DSCP shaping/policing/restoration and deadline
  compensation passed. Approximately18.80Mbps baseline TCP,37.80Mbps multipath,
  4.76Mbps shaped/4.87Mbps policed versus17.71Mbps restored UDP.
- Faults:link-down, stale controller and controller disconnect reject/restore checks,
  worker/lab restart, unsafe dispatch, partial rollback and uncertainty handling.
- Overrides:six expiry/STOP/revocation/capture/restart cases restored owned flows to
  zero and retained exact cancellation identity. Backend restoration about6-9seconds.
- Reports:actual PDF/CSV parsing/download/hash/tamper/tenant checks and worker/outbox
  transactions passed; report source records are explicit fixtures.
- Measured alerts:26 actual counter observations; breach span11.024s, recovery
  span12.031s, workload-stop to resolving observation12.934s. Same incident/history/
  audit IDs, duplicate replay invariance and tenant denial passed.

## Failures Preserved and Fixed

Initial campaign had four failed cases across three stages; original artifacts
remain linked in supersessions. Emulation verifier bypassed new event-bus handler
composition and produced backlog rather than proven data loss; correct bounded
per-series event processing resolved it without enlarging the40second drain limit.
Runtime cancellation incorrectly rejected a failed receipt with verified rollback,
causing endless uncertainty; accepting verified compensated failed/cancelled
receipts fixed it, with a regression that failed before the change. STOP-capture
verifier scheduling was corrected using controlled suspension of its OWN worker
and real capture/STOP ordering; no DB time/status or traffic changes.
Full details: `backend/scripts/acceptance/VALIDATION.md`.

## Blocked Acceptance Cases

Measured low/ramp/burst/overload/multiple-bottleneck matrix and larger topology
were not implemented/run as this new campaign; their modeled counterparts are not
physical validation. DRL+safety, independently repeated heldout acceptance and
physical power control also remain blocked. Historical ADR014 hash verification
is not a new model run or new superiority evidence. No training/test retuning.

## Gates and Deployment

Final default backend:2,028 passed,89 opt-in skips. Focused acceptance/recovery100
passed; scoped lint/diff checks passed. Frontend487 tests,41 browser tests without
retry,typecheck/lint/build/performance passed. Total JS410.09KiB vs unchanged410.16
limit: headroom is narrow. Full backend lint version debt is not newly certified.

Migrations0017/0018/0019 and backend dependencies must be installed in the intended
deployment; tests migrated disposable scopes only. Do not activate the AI virtualenv
for backend commands. After review, from backend:

```bash
env -u VIRTUAL_ENV -u CONDA_PREFIX poetry install
env -u VIRTUAL_ENV -u CONDA_PREFIX poetry run alembic -c alembic/alembic.ini upgrade head
env -u VIRTUAL_ENV -u CONDA_PREFIX poetry run python -m scripts.run_report_worker
env -u VIRTUAL_ENV -u CONDA_PREFIX PYTHONPATH=. poetry run python scripts/run_alert_worker.py
```

Run workers as separate services/terminals. Provision protected REPORTS_STORAGE_PATH
before rendering; API and worker share this storage under the backend UID. Safe
artifact retention/orphan cleanup remain deployment responsibilities (Step15).
Current measured adapter/binding prerequisites still apply to measured alerts.

All campaign-owned resources cleaned up. Existing stopped lab was NOT started,
removed or reconfigured; exact full inspect identity/hash verified unchanged.
User database services and unrelated data remain untouched. No commits created.
