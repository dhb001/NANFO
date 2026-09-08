# Isolated Campus SDN Lab

Step 3 and the Step 4 **producer only**, implementing
[`ADR-009`](../docs/adr/ADR-009-isolated-sdn-emulation-observation.md).
This is actual Mininet host namespaces, kernel Open vSwitch, Ryu OpenFlow 1.3,
LLDP discovery, ICMP probes and Linux traffic control. No synthetic counters,
application executor, AI action, production connection or database client exists
in this package. Backend binding, ingestion and persistence are implemented in
`backend/` and live-verified in
[`Emulation-Backend-Live-Validation.md`](../docs/project/Emulation-Backend-Live-Validation.md).

## Connect the Application

Start the normal database services and backend API first. With an administrator
account, run the binder from `backend/` (credentials are prompted, never printed):

```bash
mkdir -m 700 /tmp/nanfo-emulation-binding
PYTHONPATH=..:. poetry run python scripts/bind_emulation.py \
  --output /tmp/nanfo-emulation-binding/binding.json \
  --snapshot-path ../emulation/output/snapshot.json
```

Keep this binding outside the producer output mount. It records actual returned
inventory IDs; reusing the binder reuses matching inventory. Start the lab with
`python3 emulation/control.py start` from the repository root, then restart the
backend (from `backend/`) using the normal database settings plus:

```bash
PYTHONPATH=..:. EXECUTION_MODE=emulation TELEMETRY_RUNTIME_ADAPTER_MODE=emulation \
  EMULATION_BINDING_PATH=/tmp/nanfo-emulation-binding/binding.json \
  EMULATION_SNAPSHOT_PATH=../emulation/output/snapshot.json \
  poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

In the frontend select the `nanfo-emulation` organization, `Emulation` workspace,
and `campus-small-v1` network. Telemetry shows measured emulation and supports
time-range/aggregation controls. Refresh topology REST data after discovery/link
changes; no new live link-delta contract is implemented. Run
`python3 emulation/control.py traffic` to produce an independently checked workload.
Changing modes does not enable intent execution or the simulation evaluator.

## Run

Requirements: Linux Docker Engine with Compose, rootful container privileges,
kernel OVS/veth/network namespaces/HTB/netem support, and Internet access **at image
build time only**. Neither Mininet nor OVS is installed on the host. Run from the
repository root. If Docker access needs sudo, prefix the control command with
`sudo`; no host networking commands are required.

```bash
python3 -m unittest discover -s emulation/tests -v
python3 -m ruff check emulation
python3 emulation/control.py build
python3 emulation/control.py verify
```

`verify` is one-shot: it starts the topology, waits for the real controller and
discovery, runs pingAll, captures ICMP/LLDP, runs an independent eight-second
iperf3 TCP client/server workload, checks queue backlog and OpenFlow against
`ovs-ofctl`, writes artifacts, and cleans up. It returns nonzero on failed checks.
It refuses to compete with an active service. A file lock also prevents concurrent
one-shot/service writers to the same output directory.

```bash
python3 emulation/control.py start
python3 emulation/control.py status
python3 emulation/control.py smoke
python3 emulation/control.py traffic
python3 emulation/control.py reset
python3 emulation/control.py stop
```

`start` waits for container health. `smoke` runs the full live gate in the existing
lab; `traffic` runs only the iperf3/counter/queue/probe gate. `reset` disposes of the
container and creates a fresh lab with a new `run_id`; it does not delete evidence.
`stop` sends SIGTERM with a 20-second container shutdown bound. Commands accept
only enumerated actions, never shell fragments, interface names, arbitrary mounts
or credentials. The in-container runner also supports `--verify --output /output`.

## Isolation

- Compose uses `network_mode: none`: no Docker bridge, host network, published
  port, physical interface, host PID namespace, Docker socket or application network.
- The **only bind mount** is `emulation/output` to `/output`. It must already exist
  and may not be a symlink. Never place credentials, binding files, unrelated files
  or host symlinks in this lab-writable directory.
- Ryu is a separate process listening on container loopback `127.0.0.1:6653`.
  Controller-to-runner state is `/run/nanfo/controller.json`, not a host mount.
  Local operator requests use a root-only Unix socket, not an HTTP API.
- Privilege is needed for this disposable namespace/OVS lab. A privileged
  container is **not a security boundary against malicious code or kernel bugs**;
  run trusted code only, preferably on a disposable development VM. No module
  loading or physical-interface attachment is attempted. Docker remains the final
  cleanup boundary for partial startup and forced termination.
- Mininet's default `fixLimits` is disabled because it attempts global sysctl
  writes. Compose bounds the lab to 2 CPUs, 768 MiB RAM and 256 processes.
- Signal cleanup stops only this Mininet instance and its child processes/OVS
  daemons. There is no host `mn -c`, broad `pkill`, host OVS command or host reset.

## Topology

The pure-stdlib `emulation.topology.manifest()` is the shared trusted source for
the operator-side binder. `python3 -m emulation.topology` prints its JSON.
It returns `topology_id`, `switches`, `hosts`, `links`, and
`port_capacities_mbps` keyed by `16-digit-dpid:port`.

| Switch | DPID | Role |
| --- | --- | --- |
| core | 0000000000000001 | core |
| dist1 | 0000000000000002 | distribution |
| dist2 | 0000000000000003 | distribution |
| access1 | 0000000000000004 | access |
| access2 | 0000000000000005 | access |

| Endpoint A | Endpoint B | Mbps | Per-direction delay |
| --- | --- | --- | --- |
| core:1 | dist1:1 | 100 | 2 ms |
| core:2 | dist2:1 | 100 | 2 ms |
| dist1:2 | dist2:2 | 50 | 3 ms |
| dist1:3 | access1:1 | 20 | 5 ms |
| dist2:3 | access1:2 | 20 | 5 ms |
| dist1:4 | access2:1 | 20 | 5 ms |
| dist2:4 | access2:2 | 20 | 5 ms |
| access1:3 | h1:0 | 100 | 1 ms |
| access1:4 | h2:0 | 100 | 1 ms |
| access2:3 | h3:0 | 100 | 1 ms |
| access2:4 | h4:0 | 100 | 1 ms |

All links specify `max_queue_size=100` packets using HTB and leaf netem. Host `hN`
has IP `10.77.0.N/24` and MAC `02:00:00:00:00:0N`. Static neighbor entries avoid
ARP flooding. Ryu installs deterministic shortest-path unicast rules only over
bidirectionally **observed** LLDP links, with sorted tie-breaking. There is no
`OFPP_FLOOD` or `NORMAL` fallback; unknown/multicast data is dropped. Idle/hard
flow expiry and topology-change invalidation prevent indefinite stale paths.
This baseline does not claim hitless topology-change convergence.

LLDP is processed by Ryu's real topology discovery service using PacketIn events,
including redundant links not used by a given unicast path. Configured host names
are exported only after a matching IPv4/MAC packet arrives at its actual expected
host-facing ingress. Transit packets do not create host attachments. Hard flow
expiry ensures periodic rediscovery; host observations expire after 60 seconds.

## Snapshot Contract

Only `output/snapshot.json` is the backend handoff. It contains **exactly**:

```text
version=1, topology_id="campus-small-v1", run_id=UUID, sequence>=0,
observed_at=UTC ISO, switches, links, hosts, queues, probes
switch: dpid, name, observed_at, ports, flows
port: port_no, rx_bytes, tx_bytes, rx_packets, tx_packets,
      rx_dropped, tx_dropped, duration_sec
flow: table_id, priority, cookie, packet_count, byte_count, duration_sec
link: src_dpid, src_port, dst_dpid, dst_port
host: name, mac, ipv4, dpid, port_no
queue: dpid, port_no, observed_at, backlog_bytes, backlog_packets
probe: src_host, dst_host, observed_at, sent, received,
       rtt_avg_ms (float or null), interval_seconds
```

No contract adjustment from ADR-009 is required. Switch timestamps are actual
completion times of a correlated port/flow reply round, not export-clock values.
Multipart replies are accumulated by switch, request XID and kind. Both complete
replies are required; incomplete rounds expire after 5 seconds, complete samples
after 6 seconds. Unsupported all-ones port counters are omitted. At most 128 ports
and 256 flows per switch are retained. The campus bounds discovery to 5 switches,
14 directed switch links, 4 hosts, 18 switch-side queues and 4 periodic probes.

Ryu polls each second. The runner normally publishes approximately each second,
with two-packet probes every five seconds. Ping summaries provide actual sent,
received and mean RTT; measured monotonic elapsed time is the probe interval.
RTT is not one-way latency and probe loss is not application delivery ratio.
Unavailable or malformed measurements are omitted, never replaced with zero.
Zero backlog is exported only when explicitly reported by `tc`.

Queue parsing selects exactly one leaf `netem` from `tc -s -j qdisc`, using
`backlog` bytes and `qlen` packets. Parent HTB backlog represents the same packets
and is deliberately **not added**. Queue lengths are not percentages; kernel
segmentation/offload can make bytes-per-queued-packet exceed Ethernet MTU.

JSON reads/writes are bounded to 1 MiB. Publication uses a same-directory temporary
file, file fsync, atomic replacement and directory fsync. One snapshot is replaced,
not appended; `sequence` advances in-process and `run_id` changes on restart.
This is not a durable event outbox or an exactly-once transport. The backend must
still enforce freshness, tenant binding, counter reset rules and trusted capacity.
Keep its binding outside this directory, never writable by the lab.

## Artifacts

| File in `emulation/output/` | Meaning |
| --- | --- |
| snapshot.json | Latest exact ADR-009 handoff |
| before.json, after.json | Exact snapshots bracketing the independent workload |
| traffic.json | Sanitized iperf3 summaries, controller/CLI byte deltas, queue peak and probes |
| queue-peak.json | Actual raw tc JSON for the selected peak and its leaf measurement |
| probes.pcap | Up to 80 ICMP/LLDP frames from the isolated access1 uplink |
| verification.json | Live pass/fail, run UUID, reachability/discovery/capture counts |
| .producer.lock | OS advisory single-writer lock, released on process exit |

Evidence files are fixed-size/count bounded and overwritten on their next command.
Reset preserves evidence: **compare run UUIDs**, since an old verification report
does not certify a new running instance. No hostnames/kernel descriptions from
iperf3 are exported; PCAP contains only generated lab addresses/payloads.
Ryu logs rotate internally at 256 KiB with one backup. Docker logs rotate at 2 MiB
with two files. Do not use `snapshot.json` after stopping as fresh telemetry.

## Validation And Limits

Validated live on 2026-09-08 with Linux Docker 29.7.2:

- Docker build and all 16 image tests passed. Host stdlib tests: 12 passed, 4
  runtime-specific tests intentionally skipped because Ryu/Mininet belong only in the image.
- One-shot verify and service smoke: pingAll 12/12 replies, 0% loss; 5 actual
  switches, 14 directed LLDP links, 4 actual host attachments and 18 leaf queues.
- Independent service workload delivered 19,271,432 TCP bytes at 18.96 Mbps over
  the configured 20 Mbps path. Ryu and independent OVS CLI both measured exactly
  20,021,324 transmitted port bytes. Peak netem backlog: 295,230 bytes / 99 packets.
- PCAP independently decoded real ICMP requests and replies. Four measured
  two-packet probe pairs had 8/8 replies.
- Start/status/smoke/traffic/reset/stop succeeded. Reset changed run UUID; stop
  left no Compose lab container. Docker inspect confirmed `none` networking, no
  port bindings, no host PID mode and exactly the dedicated output bind mount.
- The cooperating backend's strict `EmulationSnapshot` model accepted the live
  snapshot without schema changes.
- Final one-shot run `9cc9932a-9cff-4829-9190-22eb0c734d2d` also passed after
  the Mininet global-sysctl regression fix: 19,219,304 delivered bytes at 18.96 Mbps;
  controller/CLI deltas 19,920,309 / 19,920,239 bytes (70-byte polling offset);
  peak backlog 298,258 bytes / 100 packets. The 5,952-byte PCAP independently
  decoded LLDP frames as well as ICMP. `queue-peak.json` records matching HTB and
  netem backlogs and proves only the netem value was selected, not doubled.

The base image is digest-pinned Python 3.9.23, with Ryu 4.34, eventlet 0.30.2,
setuptools 57.5.0 and pinned Python transitives. Mininet is 2.3.0-1 and OVS is
2.15.0+ds1-2+deb11u5. The retired Bullseye security index was expired and referenced
404 archives; the build uses signed HTTPS Bullseye main, which still provides
the pinned OVS package. Signature/TLS verification is not disabled. These are
**legacy/EOL dependencies, not a production security baseline**. The runtime has
no external networking. Other OS dependencies come from that signed distribution;
the build is version-controlled, not claimed bit-for-bit hermetic.

Upstream Mininet may print `sch_htb: quantum ... is big` warnings at these link
rates; actual shaping and leaf qdisc measurements are checked by the live gate.
CPU scheduling, offload and virtualized kernel timing affect results. Connectivity
and throughput checks do not certify physical-network fidelity or failover SLAs.

For diagnostics, use `docker compose -f emulation/compose.yaml logs --no-color`
and inspect `/run/nanfo/controller.log` inside a still-running lab. Do not work
around kernel/runtime failures by attaching host interfaces or enabling host
networking. A failed readiness/live gate remains a blocker, not fabricated success.
