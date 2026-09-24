"""Simulation-owned versioned lifecycle and execution evidence validation."""

import asyncio
import copy
import uuid
from collections import OrderedDict
from datetime import UTC, datetime

from fastapi import HTTPException

from app.core.config import get_settings
from app.modules.simulation.evaluator import (
    MODEL_VERSION,
    canonical_config,
    digest,
    initial_checkpoint,
    output,
    validate_checkpoint,
)
from app.modules.simulation.models import Simulation, SimulationOutbox
from app.modules.simulation.repository import event_payload, normalize_correlation
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


def _verify_values(scenario_config, input_sha256, checkpoint, run_output) -> dict | None:
    """Pure whole-checkpoint re-verification (CPU bound; never call on the event loop)."""
    try:
        config = ScenarioConfig.model_validate(scenario_config)
        if input_sha256 != digest(canonical_config(config)):
            return None
        result = output(config, checkpoint)
        if result != run_output or result["model_version"] != MODEL_VERSION:
            return None
        return result
    except (ValueError, TypeError, KeyError):
        return None


def verified_output(record) -> dict | None:
    """Synchronous verification for worker threads and tests; request paths use the async form."""
    if not configured(record):
        return None
    return _verify_values(record.scenario_config, record.input_sha256, record.checkpoint, record.run_output)


# ADR-028: per-process cache of verified outputs keyed by the persisted revision and
# stored digests. A revision's committed content is immutable (every lifecycle and
# batch CAS increments it), so a hit never skips verification of new content.
VERIFIED_OUTPUT_CACHE_SIZE = 64
_VERIFIED_OUTPUTS: OrderedDict[tuple, dict | None] = OrderedDict()


def _verification_key(record) -> tuple:
    checkpoint = record.checkpoint if isinstance(record.checkpoint, dict) else {}
    run_output = record.run_output if isinstance(record.run_output, dict) else {}
    return (str(record.simulation_id), getattr(record, "revision", None), record.input_sha256,
            checkpoint.get("checkpoint_sha256"), run_output.get("output_sha256"))


async def verified_output_async(record) -> dict | None:
    """Verify off the event loop (``asyncio.to_thread``); cached per (simulation, revision).

    The returned mapping is shared by cache hits and must be treated as read-only.
    """
    if not configured(record):
        return None
    key = _verification_key(record)
    if key in _VERIFIED_OUTPUTS:
        _VERIFIED_OUTPUTS.move_to_end(key)
        return _VERIFIED_OUTPUTS[key]
    result = await asyncio.to_thread(_verify_values, record.scenario_config, record.input_sha256,
                                     record.checkpoint, record.run_output)
    _VERIFIED_OUTPUTS[key] = result
    while len(_VERIFIED_OUTPUTS) > VERIFIED_OUTPUT_CACHE_SIZE:
        _VERIFIED_OUTPUTS.popitem(last=False)
    return result


NETWORK_STATE_HASH_VERSION = 2
# Measurements, counters and sampling metadata. They change every observation and
# must not invalidate evidence bound to an unchanged topology/configuration.
_VOLATILE_SNAPSHOT_FIELDS = frozenset({"observed_at", "sequence", "queues", "probes"})
_VOLATILE_SWITCH_FIELDS = frozenset({"observed_at", "ports", "flows"})


def _stable_switch(item):
    if not isinstance(item, dict):
        return item
    stable = {key: value for key, value in item.items() if key not in _VOLATILE_SWITCH_FIELDS}
    ports = item.get("ports")
    if isinstance(ports, list):
        # Port identity is topology; rx/tx counters and durations are measurements.
        stable["ports"] = sorted(port["port_no"] for port in ports if isinstance(port, dict) and "port_no" in port)
    return stable


def stable_network_projection(snapshot_value: dict) -> dict:
    """Stable topology/configuration projection of an actual lab observation.

    Keeps version, topology and run identity, switch identities and port sets,
    links and hosts. Drops every timestamp, sequence, port/flow counter, queue
    backlog and probe measurement (reactive controller flow entries included).
    Top-level object arrays are sorted by canonical digest; paths are not reordered.
    """
    value = {key: item for key, item in snapshot_value.items() if key not in _VOLATILE_SNAPSHOT_FIELDS}
    if isinstance(value.get("switches"), list):
        value["switches"] = [_stable_switch(item) for item in value["switches"]]
    for key, items in list(value.items()):
        if isinstance(items, list) and all(isinstance(item, dict) for item in items):
            value[key] = sorted(items, key=digest)
    return value


def current_network_state_hash(*, binding, snapshot) -> str:
    """Single owner of the execution-evidence network state digest (version 2).

    Evidence creation (validate returns it), acceptance and pre-dispatch checks all
    hash the current actual ``prepare_plan`` binding/snapshot through this helper.
    """
    return digest({
        "version": NETWORK_STATE_HASH_VERSION,
        "binding": binding.model_dump(mode="json"),
        "topology": stable_network_projection(snapshot.model_dump(mode="json")),
    })


def policy_floors(settings=None) -> dict[str, float]:
    """Server policy floors on execution evidence limits (ADR-028 C18).

    Read with defaults until the platform settings declare them.
    """
    settings = settings or get_settings()
    return {
        "max_loss_pct": float(getattr(settings, "SIMULATION_POLICY_MAX_LOSS_PCT", 1.0)),
        "max_latency_ms": float(getattr(settings, "SIMULATION_POLICY_MAX_LATENCY_MS", 1000.0)),
        "min_throughput_mbps": float(getattr(settings, "SIMULATION_POLICY_MIN_THROUGHPUT_MBPS", 0.0)),
    }


def limits_respect_policy(limits, floors: dict[str, float]) -> bool:
    """Operator limits may be stricter, never weaker, than the server floors."""
    try:
        return (float(limits["max_loss_pct"]) <= floors["max_loss_pct"]
                and float(limits["max_latency_ms"]) <= floors["max_latency_ms"]
                and float(limits["min_throughput_mbps"]) >= floors["min_throughput_mbps"])
    except (KeyError, TypeError, ValueError):
        return False


def max_active_per_workspace(settings=None) -> int:
    settings = settings or get_settings()
    return int(getattr(settings, "SIMULATION_MAX_ACTIVE_PER_WORKSPACE", 8))


async def enforce_active_quota(service, workspace_id) -> None:
    """429 before a run becomes queued; the count is serialized per workspace."""
    limit = max_active_per_workspace()
    if await service._repo.active_count(workspace_id) >= limit:
        raise HTTPException(429, detail={"code": "SIMULATION_QUOTA_EXCEEDED",
            "message": f"Workspace already has {limit} queued or running simulations; retry after one finishes."},
            headers={"Retry-After": "30"})


def _validate_stored(scenario_config, input_sha256, checkpoint) -> None:
    config = ScenarioConfig.model_validate(scenario_config)
    if input_sha256 != digest(canonical_config(config)):
        raise ValueError("Input changed")
    validate_checkpoint(config, checkpoint)


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
    correlation, correlation_meta = normalize_correlation(correlation_id)
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
            await asyncio.to_thread(validate_checkpoint, config, parent.checkpoint)
        except ValueError as exc:
            raise HTTPException(409, detail="Parent checkpoint invalid.") from exc
        checkpoint, copied = copy.deepcopy(parent.checkpoint), True
    if parent is None:
        await enforce_active_quota(service, network.workspace_id)
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
            "correlation_id": correlation,
            **correlation_meta,
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
        await asyncio.to_thread(_validate_stored, record.scenario_config, record.input_sha256, record.checkpoint)
    except ValueError as exc:
        raise HTTPException(409, detail="Simulation input/checkpoint invalid.") from exc
    if state == "queued" and record.state not in {"draft", "paused", "queued"}:
        raise HTTPException(409, detail="Simulation is not resumable.")
    if state == "paused" and record.state not in {"queued", "running", "paused"}:
        raise HTTPException(409, detail="Simulation is not pausable.")
    if record.state == state:
        # ADR-028: same-state requests are idempotent no-ops: no revision bump, no
        # lease revocation, no commit and no duplicate lifecycle event.
        correlation, correlation_meta = normalize_correlation(correlation_id)
        payload = event_payload(record, correlation, request_id=correlation_meta.get("request_id"))
        return payload if state == "paused" else {
            "handoff": payload,
            "queue_status": record.queue_status,
            "stream_entry_id": record.stream_entry_id,
            "warning": record.warning,
        }
    if state == "queued":
        await enforce_active_quota(service, record.workspace_id)
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
    floors = policy_floors()
    if configured(record) and not limits_respect_policy(record.scenario_config.get("limits"), floors):
        raise HTTPException(
            409,
            detail={
                "code": "SIMULATION_POLICY_VIOLATION",
                "message": (
                    "Simulation limits are weaker than the server policy floors "
                    f"(max_loss_pct<={floors['max_loss_pct']:g}, max_latency_ms<={floors['max_latency_ms']:g}, "
                    f"min_throughput_mbps>={floors['min_throughput_mbps']:g})."
                ),
            },
        )
    # Security-critical: always a full re-verification (never the read cache), off-loop.
    result = (await asyncio.to_thread(_verify_values, record.scenario_config, record.input_sha256,
                                      record.checkpoint, record.run_output)
              if configured(record) else None)
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
        "policy_floors": floors,
    }
