"""Pure frozen-v4 service formulas: the single implementation (ADR-028).

Dependency-free on purpose (no emulation, simulation, schemas or database imports), so a
formal-stage caller may import it lazily without loading experimental lab code.
``app.modules.autonomy.experimental.metrics`` re-exports these names as its public API and
``measured_metrics`` builds its result from them; callers validate their raw inputs first.
"""


def flow_service_metrics(sent_packets, received_packets, received_bytes, sender_duration_seconds):
    """One UDP flow: goodput over the actual sender lifetime, loss from packet counts.

    ``udp_loss_pct`` is the verification form, ``loss_fraction`` the frozen-client form; each
    keeps its historical expression so previously computed values stay bit-identical.
    """
    return {
        "goodput_mbps": received_bytes * 8 / sender_duration_seconds / 1e6,
        "udp_loss_pct": 100 * (sent_packets - received_packets) / sent_packets if sent_packets else None,
        "loss_fraction": 1 - received_packets / sent_packets if sent_packets else None,
    }


def probe_service_metrics(sent, received, rtt_avg_ms):
    """Independent ICMP probe stream: probe loss, RTT only when replies arrived, outage."""
    counted = type(sent) is int and type(received) is int and sent > 0
    return {
        "probe_loss_pct": 100 * (sent - received) / sent if counted else None,
        "rtt_ms": rtt_avg_ms if received else None,
        "probe_sent": sent,
        "probe_received": received,
        "service_outage": counted and received == 0,
    }
