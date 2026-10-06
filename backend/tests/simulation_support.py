"""Small deterministic non-actuating fluid scenarios."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.simulation.evaluator import (
    advance,
    canonical_config,
    digest,
    initial_checkpoint,
    output,
)
from app.modules.simulation.models import Simulation
from app.modules.simulation.schemas import ScenarioConfig


def scenario(**overrides):
    value = {
        "version": 1,
        "seed": 7,
        "tick_ms": 100,
        "duration_ticks": 10,
        "links": [
            {
                "link_id": "ab",
                "source": "a",
                "target": "b",
                "capacity_mbps": 1.0,
                "buffer_bytes": 25000.0,
                "delay_ms": 0.0,
                "initial_queue_bytes": 0.0,
            }
        ],
        "flows": [
            {
                "flow_id": "f",
                "source": "a",
                "target": "b",
                "path": ["ab"],
                "demand_mbps": [2.0],
            }
        ],
        "action_binding": None,
        "limits": {
            "max_loss_pct": 100.0,
            "max_latency_ms": 10000.0,
            "min_throughput_mbps": 0.1,
        },
    }
    return ScenarioConfig.model_validate({**value, **overrides})


# Default server policy floors (ADR-028 C18). ``scenario()`` passes its own
# max_loss_pct=100 limit with 45% loss, exactly what the floors exist to reject.
POLICY_LIMITS = {"max_loss_pct": 1.0, "max_latency_ms": 1000.0, "min_throughput_mbps": 0.1}


def policy_scenario(**overrides):
    """An under-capacity flow that passes the default execution policy floors."""
    return scenario(**{
        "flows": [{"flow_id": "f", "source": "a", "target": "b", "path": ["ab"], "demand_mbps": [0.5]}],
        "limits": POLICY_LIMITS,
        **overrides,
    })


def completed(config):
    checkpoint = initial_checkpoint(config)
    while checkpoint["state"]["tick"] < config.duration_ticks:
        checkpoint = advance(config, checkpoint, ticks=32)
    return checkpoint, output(config, checkpoint)


def record(config=None, *, complete=False, **kwargs):
    config = config or scenario()
    now = datetime.now(UTC)
    checkpoint, result = (
        completed(config) if complete else (initial_checkpoint(config), {})
    )
    return Simulation(
        **{
            "simulation_id": uuid.uuid4(),
            "parent_simulation_id": None,
            "network_id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "scenario_id": uuid.uuid4(),
            "scenario_name": "Test",
            "state": "completed" if complete else "queued",
            "status": "completed" if complete else "queued",
            "risk_gate": result.get("risk_gate", "required"),
            "validation": {"policy_reference": "ADR-017"},
            "run_output": result,
            "model_versions": {},
            "audit_provenance": {"correlation_id": str(uuid.uuid4())},
            "queue_status": "outbox_pending",
            "requested_by_user_id": str(uuid.uuid4()),
            "requested_at": now,
            "created_at": now,
            "updated_at": now,
            "scenario_config": canonical_config(config),
            "checkpoint": checkpoint,
            "input_sha256": digest(canonical_config(config)),
            "revision": 1,
            "completed_at": now if complete else None,
            "evidence_expires_at": now + timedelta(minutes=5) if complete else None,
            **kwargs,
        }
    )
