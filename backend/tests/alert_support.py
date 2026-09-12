"""Deterministic measured-typed fixtures, NOT live capture evidence."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.alert.detector import MeasuredObservation

START = datetime(2026, 9, 12, tzinfo=UTC)
ORG, WORKSPACE, NETWORK, DEVICE, RUN, ACTOR = [uuid.UUID(int=i) for i in range(1, 7)]


def observation(seconds=0, value=85, metric="link_utilization_percent", **overrides):
    unit, method = {
        "link_utilization_percent": ("%", "openflow_port_counter_delta"),
        "latency_ms": ("ms", "ping_rtt"),
        "packet_loss_percent": ("%", "ping_probe"),
        "queue_backlog_packets": ("packets", "linux_qdisc_backlog"),
    }[metric]
    tags = {"synthetic": False, "execution_mode": "emulation", "quality": "measured",
            "freshness": "fresh", "run_id": str(RUN), "topology_id": "campus-small-v1",
            "measurement_method": method}
    if metric in {"link_utilization_percent", "queue_backlog_packets"}:
        tags.update(port_no=1, dpid="0000000000000001", rate_quality="measured",
                    interval_seconds=5, capacity_mbps=100)
    else:
        tags.update(peer_host="h2", latency_semantics="RTT", loss_semantics="probe", interval_seconds=5)
    data = dict(event_id=uuid.uuid5(RUN, f"{seconds}:{metric}"), correlation_id=RUN,
        network_id=NETWORK, workspace_id=WORKSPACE, device_id=DEVICE, metric=metric,
        value=value, unit=unit, source="emulation", observed_at=START + timedelta(seconds=seconds), tags=tags)
    data.update(overrides)
    return MeasuredObservation.model_validate(data)


def event_for(sample):
    data = sample.model_dump(mode="json")
    event_id, correlation_id = data.pop("event_id"), data.pop("correlation_id")
    return {"event_id": event_id, "correlation_id": correlation_id,
            "event_type": "telemetry.metric.ingested", "source": "telemetry",
            "timestamp": data["observed_at"], "payload": data}
