# ADR-009: Isolated SDN Emulation and Measured Observation

- Status: Accepted for user-requested completion-plan Steps 3 and 4
- Date: 2026-09-08

## Decision

Run Mininet/Open vSwitch/Ryu in an isolated Linux container, never in the web
application process. No host network mode, physical interface attachment, host
root filesystem mount, or backend/database credentials are allowed in the lab.
Container privilege is restricted to this disposable network lab. Ryu uses
OpenFlow 1.3 with loop-free baseline forwarding; no AI or production executor is
enabled. The initial topology has a core, two distribution switches, two access
switches and four hosts with redundant paths and explicitly assigned ports.

The controller exports actual OpenFlow replies/discovery. The Mininet runner adds
actual Linux queue backlog and host ping measurements. It atomically replaces a
bounded versioned JSON snapshot in a dedicated output directory. Backend reads
only that file using asynchronous bounded I/O, validates timestamps/identities/
limits, derives rates from counters, and publishes existing telemetry events.

## Snapshot Version 1

Top-level fields: `version=1`, `topology_id="campus-small-v1"`, `run_id` UUID,
`sequence` nonnegative integer, `observed_at` UTC ISO time, `switches`, `links`,
`hosts`, `queues`, `probes`. Unknown fields are rejected at the boundary.

- switches: `{dpid:16-digit lowercase hex, name:string, observed_at:UTC,
  ports:[{port_no:int, rx_bytes:int, tx_bytes:int, rx_packets:int, tx_packets:int,
  rx_dropped:int, tx_dropped:int, duration_sec:float}],
  flows:[{table_id:int, priority:int, cookie:int, packet_count:int, byte_count:int,
  duration_sec:float}]}`. Only real controller replies are exported; unavailable
  switch replies are omitted. Port capacity is trusted topology configuration,
  not a speed inferred from counters.
- links: `{src_dpid, src_port, dst_dpid, dst_port}` observed LLDP switch links.
- hosts: `{name, mac, ipv4, dpid, port_no}` observed host attachments.
- queues: `{dpid, port_no, observed_at, backlog_bytes, backlog_packets}` from
  Linux `tc -s -j qdisc`; unavailable parsing produces no measurement, not zero.
- probes: `{src_host, dst_host, observed_at, sent, received, rtt_avg_ms:null|float,
  interval_seconds:float}` from actual ping observations. RTT is not one-way delay;
  probe loss is not application packet delivery ratio.

## Trusted Binding and Ownership

An operator-side command uses existing authenticated org/network/device APIs and
records returned device UUIDs in a separate binding file, not writable by the lab.
Binding version 1: `{version:1, topology_id, network_id, workspace_id, actor_user_id,
switches:{dpid:device_uuid}, hosts:{host_name:device_uuid},
port_capacities_mbps:{"dpid:port":positive_number}}`.
The snapshot cannot choose application tenant/device UUIDs. Network-owned service
checks the binding against current active inventory/membership and applies observed
links. Snapshot replacements remove only links owned by this emulation binding,
never unrelated/synthetic/physical links. No cross-module table queries are added.
Composition may call documented Network-owned service contracts, then Telemetry
ingestion; protocol/CLI knowledge stays inside `emulation/`.

Metric tags include `synthetic=false`, `execution_mode=emulation`, `run_id`,
`sequence`, `topology_id`, `measurement_method`, `quality`, and when applicable
`port_no`, `dpid`, `interval_seconds`, `capacity_mbps`, `peer_host`.
First counter samples/reset/nonpositive intervals produce no rate. Backlog counts
are measurements, not queue occupancy percentages. Probe loss and port drops use
distinct metric names. Freshness, future skew and bounded file/sample counts are
validated. Optional stable event IDs derived from run/sequence/sample identity
prevent duplicate rows on snapshot retry without changing the event envelope.

## Historical Queries

Extend existing history/device endpoints with optional UTC `start_time` inclusive
and `end_time` exclusive. History may request `aggregation=avg|min|max|sum` and
`bucket_seconds` (1..86400); aggregation requires a metric and bounded time range
(maximum seven days). Default remains paginated raw records. Aggregation is per
device/metric/unit/source/port/peer/run so separate ports, probe targets and
experiment runs are not silently averaged together. `flow_*` aggregation is
rejected with a validation error: snapshot v1 has no durable flow match identity.
Flow counters remain accessible through paginated raw history.
Response data for aggregation is `{items:[{device_id,metric,unit,source,port_no,
peer_host,run_id,bucket_start,value,sample_count}],total,page,page_size}` in the
canonical envelope. `port_no`, `peer_host` and `run_id` are nullable strings
extracted from the corresponding metric tags; missing dimensions form separate
null groups. Ordering includes all grouping dimensions for stable pagination.
No new endpoint or websocket channel is created. Existing access checks apply.

## Limits and Verification

One configured lab/collector process initially. Stable IDs and timestamps do not
constitute durable exactly-once delivery; crash recovery/outbox remains Step 6.
Step 5 control actions and Step 11 evaluator remain unavailable. Unit tests are
not evidence of emulation connectivity. Closure requires actual startup, controller
attachment, host reachability, workload-driven measurements and independent
counter/probe checks; any environmental inability must be reported as a blocker.
