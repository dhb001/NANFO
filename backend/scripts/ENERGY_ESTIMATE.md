# Research Energy Estimate

From `backend`, run `poetry run python scripts/estimate_energy.py < scenario.json`.
One JSON object is read from stdin (maximum 1 MiB); valid estimates go to stdout,
invalid input returns exit 2 and a JSON error on stderr. No services, API routes,
network access, reports integration or physical controls are used.

```json
{
  "duration_hours": 2,
  "nodes": ["a", "b", "c"],
  "links": [
    {"link_id": "ab", "source": "a", "target": "b", "active_watts": 10, "idle_watts": 2},
    {"link_id": "bc", "source": "b", "target": "c", "active_watts": 10, "idle_watts": 2},
    {"link_id": "ac", "source": "a", "target": "c", "active_watts": 10, "idle_watts": 2}
  ],
  "candidate_idle_link_ids": ["ac"]
}
```

All wattages are required operator assumptions for an entire modeled link, not
inferred from inventory or multiplied by guessed port counts. Baseline is all
links active. The candidate uses idle_watts for exactly the listed links. The
example yields 60 Wh baseline, 44 Wh candidate and 16 Wh estimated savings.
Idle above active is allowed and yields negative savings, never clamped to zero.
Negative/nonfinite wattages, missing values, coercible strings/bools, unknown
fields, duplicate IDs, unknown candidates and disconnected alternatives fail.

Bounds: 500 nodes, 2000 links, 0..1,000,000 W per declared state, duration >0 and
<=8784 hours. Graph edges are undirected; every node must remain connected after
all candidate edges are removed together. This is only a necessary model check,
not routing/capacity/redundancy-under-failure validation or actuation approval.

Output includes the validated `assumptions`, watt and Wh totals,
`estimated_savings_wh`, `model_only=true`, `guaranteed_savings=false`,
`physical_control=false`, `controls_status="unsupported"`,
`power_control_acceptance="blocked"`, `evidence_kind="configured_estimate"`,
`connectivity_status="modeled_connected"`, and explicit `limitations`.
No measured consumption, energized-port physics or hardware sleep is claimed.
