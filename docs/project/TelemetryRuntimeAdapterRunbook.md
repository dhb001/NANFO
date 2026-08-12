# Telemetry Runtime Adapter Runbook

## Purpose
Define deterministic operator response playbooks for runtime adapter SLO threshold alerts emitted from telemetry health internals.

## Scope
- Source alerts: `alert.generated` and `alert.resolved` events emitted for runtime adapter SLO state transitions.
- Signal origin: telemetry health rollup severity and anomaly reason flags.
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
4. If anomaly reason persists across repeated health checks, escalate with payload samples and correlation IDs.

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
3. Validate at least one stable post-recovery health read (no immediate re-activation).
4. Close or downgrade incident with final correlation evidence.

## Notes
- Keep remediation actions vendor-neutral in core operations records.
- Do not change API/event/schema contracts while executing this runbook.
