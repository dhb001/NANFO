# Telemetry Runtime Adapter Runbook

## Purpose
Define deterministic operator response playbooks for runtime adapter SLO threshold alerts emitted by the collector-side telemetry SLO evaluator (ADR-028 C12; before ADR-028 they came from the telemetry health read).

## Scope
- Source alerts: `alert.generated` and `alert.resolved` events emitted for runtime adapter SLO state transitions.
- Signal origin: since ADR-028 (C12), the collector-side SLO evaluator. After each poll
  cycle of the API's telemetry collector, and in the fleet worker
  (`python -m scripts.run_fleet_collector`), it closes one window when
  `NANFO_TELEMETRY_SLO_INTERVAL_SECONDS` (30) has elapsed. Windows persist in Redis, and
  a short Redis lock stops replicas from double-evaluating. `GET /api/v1/telemetry/health`
  only reads the result (`slo`); it never evaluates or publishes.
- Alerts are platform-scoped: `alert_scope: "platform"`, no workspace or network. Only a
  global Admin using an unscoped token can list them, and they cannot be acknowledged or
  resolved by hand; the evaluator resolves them. `runtime_adapter_slo_snapshot` figures
  are counter deltas for one `evaluation_window` (`start`, `end`, `seconds`,
  `counter_reset`), so an alert resolves once failures stop.
- Settings: `NANFO_TELEMETRY_SLO_ENABLED` (true), `_INTERVAL_SECONDS` (30, 5–3600),
  `_STALE_AFTER_INTERVALS` (3), `_LOCK_SECONDS` (10). `slo.stale=true` in health means no
  evaluation within the stale window; check that a collector is running.
- This runbook is operational guidance only; it does not redefine event/API contracts.

## Runtime Adapter SLO Threshold Response

### Playbook: runtime_adapter_slo_combined_threshold_response
Apply when both transition-frequency pressure and anomaly-reason pressure are elevated.

1. Confirm active alert payload fields:
   - `severity`
   - `severity_reason`
   - `anomaly_reason_flags`
   - `runtime_adapter_slo_snapshot`
2. Validate runtime adapter mode and input path using runtime tags (`adapter_mode`, source-specific tags).
3. Inspect `ingest_failures`, `dropped_samples`, and `invalid_samples` trend against `ingest_attempts`.
4. If pressure remains elevated for at least one full trend window, escalate to on-call and open an incident with correlation context.

### Playbook: runtime_adapter_slo_reason_threshold_response
Apply when anomaly-reason pressure is elevated but transition-frequency pressure is not dominant.

1. Identify dominant anomaly reasons:
   - `ingest_failures_detected`
   - `invalid_sample_ratio_exceeded`
   - `dropped_samples_detected`
2. Validate upstream collector/runtime connectivity and payload quality path.
3. Confirm no malformed payload bursts from current adapter mode configuration.
4. If anomaly reason persists across repeated evaluation windows, escalate with payload samples and correlation IDs.

### Playbook: runtime_adapter_slo_transition_threshold_response
Apply when transition-frequency pressure is elevated (stability churn), including sustained-failure critical states.

1. Check current rollup `severity_reason` (`anomaly_streak_threshold_exceeded` or `runtime_sustained_failure_active`).
2. Verify retry/backoff runtime loop behavior is still active and non-crashing.
3. Confirm alert event cadence respects cooldown behavior and is not flapping.
4. If sustained-failure state is active, declare degraded runtime collection and coordinate mitigation.

### Playbook: runtime_adapter_slo_recovery_validation
Apply on `alert.resolved` transition.

1. Confirm `runtime_adapter_slo_alert_active=false` and `severity=ok` in resolved payload.
2. Verify anomaly reason flags are cleared.
3. Validate at least one stable post-recovery evaluation window (health `slo.status` stays `ok`; no immediate re-activation).
4. Close or downgrade incident with final correlation evidence.

## Notes
- Keep remediation actions vendor-neutral in core operations records.
- Do not change API/event/schema contracts while executing this runbook.
