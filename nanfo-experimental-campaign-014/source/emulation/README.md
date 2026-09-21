# Isolated Campus SDN Lab

For the explicit opt-in ADR-011 measured reset/step environment, fixed AI client
transport, baseline smoke and real OSPF mode, see [EXPERIMENT.md](EXPERIMENT.md).
ADR-013 adds matched Linux/FRR learned routing and stationary V3 scenarios; see
[MATCHED-VALIDATION.md](MATCHED-VALIDATION.md) for the historical V3 validation.
ADR-014 supersedes fixed receiver cutoff with bounded verified drain, spec **V4**:
[DRAIN-V4-VALIDATION.md](DRAIN-V4-VALIDATION.md) records the preserved v4 release.
ADR-015 expands matched/OSPF stationary profiles under explicit spec **V5**:
[REFINEMENT-V5.md](REFINEMENT-V5.md) is the current operator/schema handoff.
Historical v4 image/source identity is in [ADR015-V4-PRESERVATION.md](ADR015-V4-PRESERVATION.md).

Measured observation and bounded manual lab controls, implementing
[`ADR-009`](../docs/adr/ADR-009-isolated-sdn-emulation-observation.md).
This is actual Mininet host namespaces, kernel Open vSwitch, Ryu OpenFlow 1.3,
LLDP discovery, ICMP probes and Linux traffic control. No synthetic counters,
autonomous AI action, production connection or database client exists
in this package. ADR-010 adds a lab-only command executor; backend approval,
authorization, binding, ingestion and persistence are implemented in
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
- Bind mounts are `emulation/output` to `/output`, `emulation/commands` read-only
  to `/commands`, and `emulation/results` writable to `/results`. All must already
  exist and may not be symlinks. Never place credentials, binding files, unrelated
  files or host symlinks in these directories.
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

`output/snapshot.json` remains the observation handoff. It contains **exactly**:

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

## Manual Controls (ADR-010)

`actions.py` owns container-local OVS OpenFlow 1.3 and Linux HTB mechanics;
`mailbox.py` owns bounded validation, serialization, durable journal and recovery.
The backend must never call Docker or switch CLI. The command mount is an
operator-provisioned trust boundary, not an authentication substitute: only the
authorized execution worker should have write permission. Provision filesystem
permissions/ACLs for that worker outside the lab; mount results read-only in it.
No backend or database credentials enter the lab. Controls default **off**.

To start the service with controls, set `EMULATION_CONTROL_ENABLED=true` and
`EMULATION_BINDING_DIGEST` to the lowercase SHA256 of the backend's validated
binding serialized as sorted compact JSON, then run `python3 emulation/control.py
start`. This digest is an operator assertion, not a binding file or a credential.
The worker must use the current `output/snapshot.json` run UUID. Configure its
absolute `EMULATION_COMMANDS_PATH` and `EMULATION_RESULTS_PATH` to the two
dedicated directories, separate from telemetry and the trusted binding.

### Exact Wire Contract

Command `<execution_id>.json`, maximum 8192 bytes, exact top-level fields:

```text
version: 1
execution_id: canonical lowercase UUID
run_id: canonical lowercase UUID, current lab run
binding_digest: lowercase SHA256, operator-provisioned
plan_hash: lowercase SHA256 of sorted compact JSON of the seven-field plan
fence: integer 1..2^63-1 (booleans rejected)
deadline: UTC ISO timestamp, immutable; new execute at most 300 seconds ahead
dispatch_expires_at: UTC ISO timestamp, immutable, no later than deadline
operation: execute | cancel
plan: {operation, source_host, destination_host, paths, weights, rate_mbps, dscp}
```

All seven plan fields are mandatory, including nulls. No shell, interface,
filename, VLAN, wireless, fault injection, unknown field or nonfinite numeric
value is accepted. JSON duplicate keys, symlinks, hardlinks and nonregular files
are rejected. Result `<execution_id>.json` contains exactly:

```text
version, execution_id, run_id, binding_digest, plan_hash, fence,
status: completed | failed | cancelled | uncertain,
verification: object, rollback: object|null, failure_reason: string|null,
completed_at: UTC
```

Only terminal results are published with file fsync, atomic replacement and
directory fsync. Completion includes `verification.readback_verified=true`,
`readback_sha256`, and actual bidirectional ICMP `probe` counts. Verified
compensation includes `rollback.verified=true` and `readback_sha256`. Raw before
and after readbacks live in `results/.journal.json`, **not** tmpfs. A malformed
envelope with no trustworthy identity is logged and cannot receive a fabricated
result identity. A valid envelope with an unsupported plan receives `failed`.

### Capabilities And Bounds

| Operation | Actual implementation and bounds |
| --- | --- |
| reroute | One full simple manifest path, 1..5 switches, explicit ingress/MAC/IPv4 matches, reverse full path |
| multipath | Two distinct internally disjoint paths, SELECT groups in each source access switch, weight 1..65535; empty weights mean equal |
| shape | 1..20 Mbps per direction; flower IPv4 source/destination selector, optional DSCP; sibling HTB class `5:100` and owned netem `20:` under existing `5:` root |
| police | 1..20 Mbps per direction; OF1.3 kbps/drop capability discovery, 100 ms burst, ingress meter followed by baseline table 1 |
| restore | Exact source/destination/DSCP match to active owned policy; remove only its flows/groups/meters/filter/class/leaf and verify original state |

DSCP is an exact classifier in **both** directions, not a remarking action.
Unmarked reverse traffic is baseline traffic when a DSCP classifier is explicit.
Shaping preserves Mininet class `5:1`, netem `10:` and their options; it refuses
unexpected hierarchy/filter state. It adds a separate leaf with the manifest's
1 ms host-link delay and 100 packet bound. Queue telemetry deliberately omits an
interface with multiple leaves rather than misreporting a summed/double backlog.

Policies use cookie `0x4e414e4600000001`, priority 30000 in table 0, and group/meter
ID 19001. Ryu baseline cookie 1 lives in table 1 and never deletes policy cookies.
PacketOut re-enters table 0; it cannot directly bypass a newly installed policy.
Controller reconnect deletes only its stale baseline rules to rediscover hosts.
`ovs-ofctl` modifications wait for their same-connection OpenFlow barrier/error
response; independent dumps verify matches/actions/groups/buckets/meters. Linux
commands require successful exit and independent class/filter/qdisc readback.

This bounded driver permits **one active policy per lab**, not policy stacking.
Restore before installing another. The whole-lab hold-down is 3 seconds (therefore
also protects each selector); action history enforces at most 30 actions/minute.
Emergency compensation is exempt. The journal retains at most 32 executions and
is bounded to 1 MiB, with no automatic deletion of identities/evidence. At capacity,
stop and reconcile/dispose the lab before archiving mailbox directories and
provisioning empty ones. Never remove a live journal to bypass a block.

### Recovery And Cancellation

An OS file lock serializes mutation and remains held through compensation and
publication. Before the first mutation the complete generated resource set,
before-image, identities and deadline are durable. Every mutation boundary checks
the current command for cancellation/identity/fence change and the deadline.
The deadline prevents new execution, not mandatory compensation: already started
CLI calls finish or time out (4 seconds each), then rollback can exceed the deadline.
No instantaneous packet-history rollback is claimed.

Duplicate execution identities cannot change plan/run/binding/deadline. A higher
fence may reconcile the same command; a lower fence cannot authorize changes.
Lost-result recovery reads actual active policy state and republishes recorded
terminal evidence, without resetting live counters. A restarted executor never
continues a partial apply: it compensates from the durable journal. Worker death
alone does not imply cancellation; the lab can finish and the replacement worker
must reconcile that result. A late cancellation of an active completed action
performs actual compensation and publishes `cancelled` only after verified removal.

A failed/cancelled restore reinstates its own before-image (the previously active
policy), after clearing any partial owned resources. Late cancellation of a
completed restore also reinstates that policy if no later policy exists; otherwise
it is uncertain and blocks rather than clobbering newer state. Controller restarts
preserve owned state. A fresh container changes run UUID and never accepts old
commands as authorization to reapply a policy. Ambiguous readback or failed rollback
persists a block across restarts. Only explicit operator reconciliation/disposal,
not another remote payload, can resolve a blocked journal.

### Live Control Gate

```bash
python3 -m unittest discover -s emulation/tests -v
python3 -m ruff check emulation
python3 emulation/control.py build
python3 emulation/control.py verify-actions
python3 emulation/control.py verify
```

`verify-actions` refuses an active lab and disables polling of the shared command
mailbox. It creates its own durable `results/verify-<run_id>/` subdirectories and
drives the same validated executor locally. Fault hooks exist only in this local
test harness, never in the command contract. Evidence is
`output/actions-verification.json`, plus complete isolated journals/results.
The gate checks TCP full-path counters and return matching, multi-stream TCP and
both SELECT buckets, classified/unclassified UDP rates, HTB and meter counters,
restore throughput, lost-result/duplicate/restart, real Ryu restart, partial
operation failures, deadline/cancel boundaries and actual executor process death.
It also leaves an intentionally blocked **verification-only** journal after a
rollback fault, independently removes its owned resources, and disposes the lab.

Pinned Bullseye tools have two tested readback quirks: `tc -j class` emits text,
and iperf3 UDP receiver `end.bytes` is zero despite traffic. The gate parses actual
HTB class text and sums actual UDP receiver interval bytes/durations. It never
substitutes sender throughput or a fabricated success for receiver measurements.

This gate does not certify backend authorization, DB/outbox/Redis recovery or HTTP
acceptance; those belong to the separate backend worker agent's live tests.

### Recorded Live Evidence (2026-09-09)

Final control run: `dc0aebc4-f383-48cd-8103-f086ec95aaea`, `passed=true`.
Report: `output/actions-verification.json`. Private root-owned durable journal:
`results/verify-dc0aebc4-f383-48cd-8103-f086ec95aaea/results/.journal.json`.
These verification directories are mode 0700; the public sanitized report is
readable separately. They are not the service mailbox journal.

| Measurement | Actual result |
| --- | --- |
| Baseline / final restored TCP | 18.804846 / 18.808340 Mbps |
| Full five-switch reroute TCP | 18.699231 Mbps; forward and reverse rules counted packets on every switch |
| TCP after actual Ryu process restart | 18.699283 Mbps |
| Two-path SELECT, 12 TCP streams | 37.805327 Mbps |
| SELECT source buckets | 3752 / 3944 packets |
| SELECT return buckets | 3427 / 3530 packets |
| 5 Mbps shaping, classified / unclassified UDP | 4.759490 / 17.706906 Mbps |
| Shaping restored UDP | 17.708648 Mbps |
| HTB owned class | 2,625,882 bytes; 2117 packets; 5385 drops under overload |
| 5 Mbps policing, classified / unclassified UDP | 4.870231 / 17.712656 Mbps |
| Policing restored UDP | 17.708574 Mbps |
| Ingress meter | 7503 input packets; 5437 drop-band packets |
| Failed restore reinstated TCP | 18.701194 Mbps |

Verified compensation passed for partial reroute, SELECT, shaping, policing and
restore failures; mid-action cancellation; deadline expiry; and an executor child
exiting at a real post-mutation crash boundary. Lost result/recreated executor,
duplicate counters/flow-age continuity, actual controller restart, concurrent
executor exclusion, late action cancellation and late restore cancellation passed.
The final injected rollback acknowledgment failure produced `uncertain`, blocked a
new shape command, and remained blocked in the 20-record private journal. Local
harness cleanup independently verified removal before container disposal.

Build (including pull) passed; all 30 container unit tests passed. Host tests:
26 passed, 4 skipped because Ryu/Mininet are container-only. Ruff and diff whitespace
checks passed. ADR-009 regression run `48a4045f-f3a8-47de-89e3-527f256a900f` passed:
12/12 ping replies, 5 switches, 14 directed links, 4 hosts, 18 queues, 5952-byte PCAP.

Wire proof fields match finalized backend `lab.py`: `readback_sha256` (not
`readback_hash`), `readback_verified`, successful `probe` counts with manifest host
names, and rollback `verified`/`readback_sha256`. There are no wire field changes.
Conservative limits remain: one active policy; internally disjoint SELECT paths;
1..20 Mbps QoS; 32 journal identities; no remote force-unblock. Full runner/container
power-loss recovery and every syscall crash boundary are not live-certified; the
fresh-run no-reapply guard has a unit regression. No backend authorization or
end-to-end worker/HTTP/DB verification is claimed by these lab-only tests.

### No-Mutation Proof And Completion Scope

Safe first-seen cancellation and pre-mutation rejection (including an already
active policy or expired deadline) are durably terminal, so their execution UUID
cannot execute later. Under the serialization lock the lab independently reads
actual state: it verifies the journaled active policy, or verifies absence of all
reserved flow/group/meter/class/qdisc/filter IDs when no policy is active.
Successful reconciliation returns `status=failed|cancelled`, `rollback=null`, and:

```json
{"readback_verified":true,"readback_sha256":"<actual-readback-sha256>",
 "no_mutation_verified":true,"mutated":false,"deadline_expired":false}
```

The actual readback is persisted in the record's `after` before acknowledgment.
`deadline_expired` is evaluated against the immutable UTC deadline; expiration
never authorizes application, but does not prevent read-only cancellation proof.
No probe or rollback is invented for this result. The worker should accept this
distinct no-mutation proof for releasing this rejected job's exclusion, not treat
it as successful execution or as permission to remove an existing active policy.
Readback failure becomes `uncertain` and blocks; stale run/binding, conflicting
identities, or already blocked state cannot receive this proof.

Recovery compares each journal record's run **and binding** before any driver
mutation. On either mismatch it performs global reserved-ID absence readback only;
remaining resources block reconciliation rather than deleting or reinstalling them.

Ordinary completed commands explicitly include
`verification.config_readback_and_reachability=true` and
`verification.traffic_effects_verified=false`. Their proof is configuration plus
actual ICMP reachability, **not** per-execution rate or bucket-distribution
certification. The separate `verify-actions` harness exercises real iperf/UDP,
path/group/meter/class counters and restore effects. This scope label is an
intentional limitation, not simulated traffic-effect evidence. Flower readback
requires one concrete filter with the exact source, destination, DSCP/mask and
class ID together, not values found anywhere in concatenated JSON.

Review-fix live run `43f135d1-2ec7-4444-84bd-6d42d5160f4e` passed on 2026-09-09.
It additionally verified persisted old-run/binding restore absence against the
clean real lab, second-action no-mutation rejection followed by successful restore,
and expired first-seen cancellation with replay exclusion. Structural flower
readback uses the actual pinned tc JSON integer `ip_tos` and `ip_tos_mask` fields.
Measured TCP reroute 18.693459 Mbps, SELECT 37.810101 Mbps, shaped UDP 4.759151 Mbps,
policed UDP 4.869493 Mbps, final restored TCP 18.805190 Mbps. All prior failure,
cancel/deadline, controller/executor recovery and uncertainty checks passed again.
Current tests: 35 container tests passed; 31 host tests passed and 4 container-only
skips; Ruff/build/whitespace checks passed. Compose `ps -a` was empty after the gate;
lab lifecycle was released to the backend verifier without another startup.

### Final Lifecycle Review

Completed restores persist `restored_by` on their original policy in the same
journal commit. Cancelling that inactive policy returns `cancelled` with
`verification.already_restored=true` and the no-mutation proof above, after reading
the **current** active policy. It never deletes shared resource IDs belonging to
a successor. Matching terminal obsolete-run recovery records replay their recorded
proof before stale-run rejection; a new stale identity remains rejected.

Polling counts UUID JSON separately from `.<uuid>.lock` and `.<uuid>.tmp` metadata.
There are 32 execution slots, plus 32 bounded rejection-only tombstone slots so
capacity refusals retain terminal no-mutation proof and cannot execute on replay.
No automatic pruning occurs. Polling accepts at most 64 command files, 128 metadata
files and 8 other entries; excess pauses processing without mutations or runner
teardown. Exhausting all tombstone capacity requires operator reconciliation.

Live review run `ecab492c-ade1-4d42-b347-52f7c1d81714` passed, including
A/restore-B/C/cancel-A/restore-C and old-run recovery followed by mailbox polling.
Reroute TCP 18.695097 Mbps, SELECT 37.810931 Mbps, shaped UDP 4.758154 Mbps, policed
UDP 4.870686 Mbps, restored TCP 18.804997 Mbps. Build: 38/38 container tests;
host: 34 passed, 4 runtime-only skips. The 33-command/33-lock/33-temp capacity test
passed without runner teardown. Evidence remains `output/actions-verification.json`.

### Dispatch Authorization Amendment

The updated ADR-010 selects required command `dispatch_expires_at`, not an
authority file. It is UTC, no later than `deadline`, excluded from plan hashes,
and included in immutable duplicate identity. Result fields remain unchanged.
New execution requires `now < dispatch_expires_at <= now + 5 seconds` and a live
action deadline. Both are checked again after blocking discovery/readback, directly
before recording the new prepared operation. Expired publication is durably rejected
with no-mutation proof only after real reconciliation. Missing metadata is an invalid
envelope, never authorization. The local verifier sets expiry immediately before
first publication, after its intentional hold-down/probe waits; it never refreshes
an already published identity.

Acceptance is the single-writer durable prepare boundary. Once prepared, continuation
uses the original action deadline; replay, reconciliation, cancellation and compensation
do not require renewed dispatch authorization. The journal records `dispatch_checked_at`.
This is not an atomic wall-clock transaction: arbitrary scheduler pauses between the
final time check and filesystem fsync cannot be excluded. No exact-time or independent
clock-skew guarantee is claimed. Host/container must share UTC as specified by ADR-010.

Live run `581f2cf9-efac-46c4-96f3-9b9f1cb31152` passed. A command delayed until after
its dispatch expiry before atomic publication returned `failed`, `mutated=false`,
`no_mutation_verified=true`, with actual readback SHA256
`c1cc6fa4828f535271f9a41bcadc0511066a004a7ddf0c4354490dea6e6c86b9`;
global owned-resource absence was independently checked before and after. Reroute
18.692154 Mbps, SELECT 37.803880 Mbps, shaping 4.759332 Mbps, policing 4.869215 Mbps,
restored TCP 18.807451 Mbps. All existing live fault/recovery checks passed.
Container tests: 41 passed; host: 37 passed/4 runtime skips. Backend
`tests/unit/test_intent_lab.py`: 46 passed, including the formerly skipped sender/
receiver envelope test. No backend files were edited.
