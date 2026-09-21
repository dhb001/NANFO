"""Simulation-owned versioned lifecycle and execution evidence validation."""

import copy
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from app.modules.simulation.evaluator import (
    MODEL_VERSION,
    canonical_config,
    digest,
    initial_checkpoint,
    output,
    validate_checkpoint,
)
from app.modules.simulation.models import Simulation, SimulationOutbox
from app.modules.simulation.schemas import ScenarioConfig
from app.modules.telemetry.references import evidence_item, install_owner_guard, page_position, reference_page


def simulation_telemetry_references(row):
    if row.simulation_id is None:
        row.simulation_id = uuid.uuid4()
    return evidence_item(identity=f"simulation:{row.simulation_id}", network_id=row.network_id,
        fields={name: getattr(row, name) for name in (
            "scenario_config", "audit_provenance", "validation", "run_output", "checkpoint")})


install_owner_guard(Simulation, owner="simulation", extractor=simulation_telemetry_references,
    fields=("scenario_config", "audit_provenance", "validation", "run_output", "checkpoint", "workspace_id", "network_id"))


async def telemetry_reference_page(db, *, workspace_id, after=None, limit=100):
    """Internal owner history contract includes legacy and branched simulations."""
    from sqlalchemy import select

    stage, last = page_position(after, stages=2, limit=limit)
    if stage:
        query = select(SimulationOutbox).where(SimulationOutbox.workspace_id == workspace_id)
        if last:
            query = query.where(SimulationOutbox.event_id > last)
        rows = list((await db.scalars(query.order_by(SimulationOutbox.event_id).limit(limit + 1))).all())

        def extract(row):
            import json

            payload = row.envelope["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            return evidence_item(identity=f"simulation-outbox:{row.event_id}", network_id=payload.get("network_id"),
                                 fields={"payload": payload})

        return reference_page(rows, extractor=extract, key=lambda row: row.event_id,
                              limit=limit, stage=stage, stages=2)
    query = select(Simulation).where(Simulation.workspace_id == workspace_id)
    if last:
        query = query.where(Simulation.simulation_id > last)
    rows = list((await db.scalars(query.order_by(Simulation.simulation_id).limit(limit + 1))).all())
    return reference_page(rows, extractor=simulation_telemetry_references,
                          key=lambda row: row.simulation_id, limit=limit, stage=stage, stages=2)


def configured(record) -> bool:
    return isinstance(getattr(record, "scenario_config", None), dict)


def verified_output(record) -> dict | None:
    if not configured(record):
        return None
    try:
        config = ScenarioConfig.model_validate(record.scenario_config)
        if record.input_sha256 != digest(canonical_config(config)):
            return None
        result = output(config, record.checkpoint)
        if result != record.run_output or result["model_version"] != MODEL_VERSION:
            return None
        return result
    except (ValueError, TypeError, KeyError):
        return None


def current_network_state_hash(*, binding, snapshot) -> str:
    """Same canonical actual snapshot for evidence creation and predeploy checking.

    Exclude only observed_at; keep run identity and all measured values, including
    counters and their timing. Sort object arrays, never ordered path arrays.
    """
    value = snapshot.model_dump(mode="json")
    value.pop("observed_at", None)
    for key, items in value.items():
        if isinstance(items, list) and all(isinstance(item, dict) for item in items):
            value[key] = sorted(items, key=lambda item: digest(item))
    return digest(
        {"version": 1, "binding": binding.model_dump(mode="json"), "snapshot": value}
    )


async def create_modeled(
    service,
    *,
    network,
    config: ScenarioConfig,
    scenario_name,
    actor_id,
    correlation_id,
    parent=None,
):
    now, simulation_id = datetime.now(UTC), uuid.uuid4()
    inputs = canonical_config(config)
    checkpoint = initial_checkpoint(config)
    copied = False
    if (
        parent is not None
        and configured(parent)
        and parent.scenario_config == inputs
        and parent.input_sha256 != digest(inputs)
    ):
        raise HTTPException(409, detail="Parent input hash invalid.")
    if (
        parent is not None
        and configured(parent)
        and parent.input_sha256 == digest(inputs)
    ):
        try:
            validate_checkpoint(config, parent.checkpoint)
        except ValueError as exc:
            raise HTTPException(409, detail="Parent checkpoint invalid.") from exc
        checkpoint, copied = copy.deepcopy(parent.checkpoint), True
    record = Simulation(
        simulation_id=simulation_id,
        parent_simulation_id=parent.simulation_id if parent else None,
        network_id=network.network_id,
        workspace_id=network.workspace_id,
        scenario_id=uuid.uuid5(network.network_id, scenario_name),
        scenario_name=scenario_name,
        state="draft" if parent else "queued",
        status="draft" if parent else "queued",
        risk_gate="required",
        scenario_config=inputs,
        input_sha256=digest(inputs),
        checkpoint=checkpoint,
        completed_at=parent.completed_at if copied else None,
        evidence_expires_at=parent.evidence_expires_at if copied else None,
        revision=1,
        validation={
            "pipeline_stage": "branch_draft" if parent else "handoff_queued",
            "status": "pending",
            "required_checks": ["simulation_before_deployment"],
            "policy_reference": "ADR-017",
            "queued_at": now.isoformat(),
            "requested_by_user_id": actor_id,
            "evaluator_status": "configured_model",
            "source": "operator_configured_model",
            "physical_safety_authorized": False,
        },
        run_output={},
        model_versions={"evaluator": MODEL_VERSION},
        audit_provenance={
            "correlation_id": correlation_id,
            "requested_by_user_id": actor_id,
            "checkpoint_copied": copied,
            "input_override_restarted": parent is not None and not copied,
            "action_binding": inputs["action_binding"],
        },
        queue_status="outbox_pending",
        requested_by_user_id=actor_id,
        requested_at=now,
        created_at=now,
        updated_at=now,
    )
    service._repo.add_modeled(record)
    payload = service._repo.enqueue(
        record,
        "simulation.branch_created" if parent else "simulation.started",
        correlation_id,
    )
    await service._db.commit()
    return (
        payload
        if parent
        else {
            "handoff": payload,
            "queue_status": "outbox_pending",
            "stream_entry_id": None,
            "warning": None,
        }
    )


async def transition_modeled(service, *, record, state, correlation_id):
    try:
        config = ScenarioConfig.model_validate(record.scenario_config)
        if record.input_sha256 != digest(canonical_config(config)):
            raise ValueError("Input changed")
        validate_checkpoint(config, record.checkpoint)
    except ValueError as exc:
        raise HTTPException(409, detail="Simulation input/checkpoint invalid.") from exc
    if state == "queued" and record.state not in {"draft", "paused", "queued"}:
        raise HTTPException(409, detail="Simulation is not resumable.")
    if state == "paused" and record.state not in {"queued", "running", "paused"}:
        raise HTTPException(409, detail="Simulation is not pausable.")
    # Invalidate any in-progress batch. Its CAS cannot overwrite this pause/resume.
    record.state = record.status = state
    record.risk_gate = "required"
    record.lease_token = record.lease_expires_at = None
    record.revision += 1
    record.validation = {**record.validation, "status": state, "pipeline_stage": state}
    record.queue_status = "outbox_pending"
    payload = service._repo.enqueue(
        record,
        "simulation.started" if state == "queued" else "simulation.paused",
        correlation_id,
    )
    await service._db.commit()
    return (
        payload
        if state == "paused"
        else {
            "handoff": payload,
            "queue_status": "outbox_pending",
            "stream_entry_id": None,
            "warning": None,
        }
    )


async def validate_execution_reference(
    service,
    *,
    simulation_id,
    workspace_id,
    network_id,
    intent_id,
    actor_id,
    plan_sha256,
    network_state_sha256,
    lock=False,
):
    record = await (service._repo.lock(simulation_id) if lock else service._repo.get_by_id(simulation_id))
    if record is None:
        raise HTTPException(409, detail="Simulation evidence unavailable.")
    await service._assert_simulation_workspace_access(
        simulation=record,
        requested_workspace_id=workspace_id,
        actor_user_id=actor_id,
        claim_org_id=None,
        require_write=True,
    )
    # Recheck the owning network's current active state, not just cached scope IDs.
    await service._network_svc.assert_network_workspace_access(
        network_id=record.network_id,
        requested_workspace_id=workspace_id,
        actor_user_id=actor_id,
        require_write=True,
    )
    result = verified_output(record)
    now = datetime.now(UTC)
    binding = (
        record.scenario_config.get("action_binding") if configured(record) else None
    )
    if (
        record.network_id != network_id
        or record.state != "completed"
        or record.status != "completed"
        or record.risk_gate != "passed"
        or result is None
        or result["risk_gate"] != "passed"
        or record.completed_at is None
        or record.completed_at > now
        or record.evidence_expires_at is None
        or record.evidence_expires_at <= now
        or (now - record.completed_at).total_seconds() > 300
        or binding
        != {
            "intent_id": str(intent_id),
            "plan_sha256": plan_sha256,
            "network_state_sha256": network_state_sha256,
        }
    ):
        raise HTTPException(
            409,
            detail={
                "code": "SIMULATION_EVIDENCE_REJECTED",
                "message": "Completed, fresh, passing modeled evidence bound to the exact intent, plan and current state is required.",
            },
        )
    return {
        "simulation_id": str(record.simulation_id),
        "intent_id": str(intent_id),
        "workspace_id": str(record.workspace_id),
        "network_id": str(record.network_id),
        "plan_sha256": plan_sha256,
        "network_state_sha256": network_state_sha256,
        "input_sha256": record.input_sha256,
        "checkpoint_sha256": result["checkpoint_sha256"],
        "output_sha256": result["output_sha256"],
        "completed_at": record.completed_at.isoformat(),
        "evidence_expires_at": record.evidence_expires_at.isoformat(),
        "source": "operator_configured_model",
        "validation_scope": "configured_model_admission_only",
        "physical_safety_authorized": False,
    }
