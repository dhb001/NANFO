# Digital Twin Scenario Validation Runbook

## Purpose
Define deterministic operator response for simulation-before-deployment validation handoff events that seed `/ws/digital-twin` scene state updates.

## Scope
- Source flow: `POST /api/v1/simulations/start` -> `simulation.started` event -> `/ws/digital-twin` scene delta fanout.
- Policy alignment: ADR-008 simulation-before-deployment gate.
- This runbook is operational guidance only; it does not redefine API/event contracts.

## Handoff Validation Response

### Playbook: digital_twin_scenario_validation_handoff
Apply when a scenario validation handoff is queued or deferred.

1. Confirm handoff payload fields:
   - `simulation_id`
   - `scenario_id`
   - `network_id`
   - `risk_gate`
   - `validation.pipeline_stage`
   - `validation.required_checks`
2. Verify `risk_gate=required` and `validation.policy_reference=ADR-008` for high-impact path safety.
3. Confirm digital twin scene consumers receive an incremental `scene_object` delta over `/ws/digital-twin` with `object_type=simulation_state`.
4. If `queue_status=deferred`, treat as fail-open queue degradation and trigger stream-recovery triage while preserving operator visibility.

### Playbook: digital_twin_scenario_validation_completion
Apply when `simulation.completed` events are emitted by downstream simulation execution.

1. Confirm scene delta carries:
   - `state=completed`
   - `status=completed`
   - `risk_gate` outcome value
2. Verify scenario identifiers (`simulation_id`, `scenario_id`) match the original handoff.
3. Record completion provenance in operational notes before any production execution decision.

## Notes
- Keep all remediation and logging vendor-neutral.
- Do not bypass simulation-before-deployment policy gates during queue incidents.
