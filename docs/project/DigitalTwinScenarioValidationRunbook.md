# Digital Twin Scenario Validation Runbook

## Purpose
Define deterministic operator response for simulation-before-deployment validation handoff events that seed `/ws/digital-twin` scene state updates.

## Scope
- Source flow: `POST /api/v1/simulations/start` -> `simulation.started` event -> `/ws/digital-twin` scene delta fanout.
- Policy alignment: ADR-008 simulation-before-deployment gate.
- Phase 2 operator workflows: session import mapping visibility, explicit per-device persistence via existing network device PATCH API, and configure handoff prefill into `/ops/intent`.
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

### Playbook: digital_twin_mapping_persistence
Apply when operators import a model/sidecar mapping and need to retain `spatial_ref_id` assignments beyond the current browser session.

1. Treat imported mapping as session-local until an explicit persist action is completed per node.
2. In Inspector, verify selected node shows `session import` and `not persisted` badges before persisting.
3. Use **Persist Mapping to Device** and confirm the request is `PATCH /api/v1/networks/{network_id}/devices/{device_id}` with `spatial_ref_id` in the request body.
4. Confirm success feedback and then verify topology-backed state reflects `persisted` on subsequent graph reload/query refresh.
5. If persist fails, keep the mapping as session-local, capture error details, and avoid manual out-of-band DB edits.

### Playbook: digital_twin_intent_handoff_prefill
Apply when initiating remediation from a selected congested node in Digital Twin.

1. Use **Configure in Intent Workflow** from the selected node card.
2. Verify navigation target remains `/ops/intent` and includes prefill context query fields (`source`, `action`, `scope`, `constraints`, `context_summary`).
3. On Intent page load, verify form values are prefilled once and query parameters are removed from URL after consumption.
4. Confirm operator validates intent before execution to preserve simulation-before-deployment governance.

### Congestion Policy Notes (Phase 2)
- Policy version shown in UI is `v2.0.0`.
- Rule priority is deterministic: `packet_loss` > `latency` > `link_utilization` > `cpu_utilization`.
- Missing or non-matching congestion metrics must remain `neutral`; do not treat neutral as implicit healthy/validated state.

## Notes
- Keep all remediation and logging vendor-neutral.
- Do not bypass simulation-before-deployment policy gates during queue incidents.
