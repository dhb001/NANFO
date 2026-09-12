"""Opt-in live ADR-009 audit against configured infrastructure, never test doubles.

From backend/: PYTHONPATH=..:. poetry run python scripts/verify_emulation.py --live
Only a randomized audit actor/scope is created. Its actor is disabled at exit;
evidence rows are retained. Existing credentials, rows and consumer groups are not
reset. Dedicated tail-only groups dispatch owned events to the real handlers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import secrets
import socket
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn
from fastapi import HTTPException
from websockets.asyncio.client import connect


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_measurements(snapshot, previous, binding, samples) -> None:
    """Independently compare derived values with the actual validated source batch."""
    switches = {switch.dpid: switch for switch in snapshot.switches}
    old_switches = {switch.dpid: switch for switch in previous.switches} if (
        previous is not None and previous.run_id == snapshot.run_id
    ) else {}
    queues = {(queue.dpid, queue.port_no): queue for queue in snapshot.queues}
    probes = {(str(binding.hosts[probe.src_host]), probe.dst_host): probe for probe in snapshot.probes}
    for sample in samples:
        metric, tags = sample["metric"], sample["tags"]
        check(tags["run_id"] == str(snapshot.run_id) and tags["sequence"] == snapshot.sequence,
              "Sample provenance does not match source snapshot")
        check(tags["synthetic"] is False and tags["quality"] == "measured"
              and tags["execution_mode"] == "emulation" and tags["freshness"] == "fresh",
              "Source measurement provenance invalid")
        if metric.startswith("port_"):
            switch = switches[tags["dpid"]]
            port = next(port for port in switch.ports if port.port_no == tags["port_no"])
            expected = getattr(port, metric.removeprefix("port_"))
            observed_at = switch.observed_at
        elif metric.startswith("flow_"):
            switch = switches[tags["dpid"]]
            expected = getattr(switch.flows[tags["flow_index"]], metric.removeprefix("flow_"))
            observed_at = switch.observed_at
        elif metric.startswith("queue_"):
            queue = queues[(tags["dpid"], tags["port_no"])]
            expected = getattr(queue, metric.removeprefix("queue_"))
            observed_at = queue.observed_at
        elif metric in {"throughput_mbps", "link_utilization_percent"}:
            switch, old = switches[tags["dpid"]], old_switches[tags["dpid"]]
            port = next(port for port in switch.ports if port.port_no == tags["port_no"])
            old_port = next(port for port in old.ports if port.port_no == tags["port_no"])
            interval = port.duration_sec - old_port.duration_sec
            check(interval > 0 and port.duration_sec > old_port.duration_sec,
                  "Rate fabricated on first/reset/nonpositive interval")
            expected = max(port.rx_bytes - old_port.rx_bytes, port.tx_bytes - old_port.tx_bytes) * 8 / interval / 1e6
            if metric == "link_utilization_percent":
                expected = expected / binding.port_capacities_mbps[f"{switch.dpid}:{port.port_no}"] * 100
            observed_at = switch.observed_at
        elif metric in {"packet_loss_percent", "latency_ms"}:
            probe = probes[(sample["device_id"], tags["peer_host"])]
            expected = (probe.sent - probe.received) / probe.sent * 100 if metric == "packet_loss_percent" else probe.rtt_avg_ms
            observed_at = probe.observed_at
        else:
            raise ValueError("Unexpected measured metric family")
        check(expected is not None and math.isclose(sample["value"], expected, rel_tol=1e-12),
              "Measurement value does not match independent source calculation")
        check(datetime.fromisoformat(sample["observed_at"]) == observed_at,
              "Measurement source timestamp lost")
        if "dpid" in tags:
            check(sample["device_id"] == str(binding.switches[tags["dpid"]]),
                  "Source DPID mapped to wrong inventory UUID")


async def command(*args: str, timeout: float = 110) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    check(process.returncode == 0, "External command failed (output withheld)")
    return stdout.decode()


async def drain_owned_batch(redis, group, errors):
    """Wait for completed delivery, using the verifier's original 40-second bound."""
    for _ in range(200):
        check(not errors, "Real backend consumer failed")
        groups = await redis.xinfo_groups("stream:telemetry")
        if any(row["name"] == group and row.get("lag") == 0 and row["pending"] == 0 for row in groups):
            return
        await asyncio.sleep(0.2)
    raise ValueError("Owned telemetry batch failed to drain within 40 seconds")


async def verify_topology_writers(binding, edges) -> dict:
    """Real Neo4j regression in the dedicated scope; restore its observed graph."""
    from app.db.neo4j import get_neo4j_driver
    from app.modules.network.synthetic_topology import PlannedEdge
    from app.modules.network.topology import TopologyQueryService

    service = TopologyQueryService(get_neo4j_driver())
    scope = {"network_id": str(binding.network_id), "workspace_id": str(binding.workspace_id)}
    original = [PlannedEdge(e["source_id"], e["target_id"], "connected_to", e["metadata"]) for e in edges.values()]
    edge = original[0]
    parallel = [PlannedEdge(edge.source_id, edge.target_id, "connected_to", {
        "synthetic": False, "edge_key": f"audit-parallel-{port}",
        "source_port": 100 + port, "target_port": 100 + port,
    }) for port in (1, 2)]
    generators = (f"audit-synthetic-{binding.owner_id}", f"audit-other-{binding.owner_id}")

    def synthetic(generator, count=2):
        return [PlannedEdge(edge.source_id, edge.target_id, "connected_to", {
            "synthetic": True, "generator": generator, "source_port": port, "target_port": port,
        }) for port in range(1, count + 1)]

    async def counts(observed, planned):
        graph, _ = await service.get_graph(binding.network_id, binding.workspace_id, limit=100)
        actual = [e.metadata for e in graph.edges]
        check(sum(m.get("synthetic") is False for m in actual) == observed, "Observed edges overwritten/pruned")
        check(sum(m.get("synthetic") is True for m in actual) == planned, "Synthetic owner/parallel identity lost")
        check(all(m.get("observation_owner") == binding.owner_id for m in actual if m.get("synthetic") is False),
              "Observed ownership overwritten")

    try:
        for observed_first in (True, False):
            await service.replace_observed_device_edges(**scope, owner_id=binding.owner_id, edges=[])
            for generator in generators:
                await service.prune_synthetic_device_edges(**scope, generator=generator)
            if observed_first:
                await service.replace_observed_device_edges(**scope, owner_id=binding.owner_id, edges=parallel)
            for generator in generators:
                await service.merge_device_edges(**scope, edges=synthetic(generator))
                await service.merge_device_edges(**scope, edges=synthetic(generator))
            if not observed_first:
                await service.replace_observed_device_edges(**scope, owner_id=binding.owner_id, edges=parallel)
            await counts(2, 4)
            await service.replace_synthetic_device_edges(**scope, generator=generators[0], edges=synthetic(generators[0], 1))
            await counts(2, 3)
            await service.replace_observed_device_edges(**scope, owner_id=binding.owner_id, edges=parallel[:1])
            await counts(1, 3)
            await service.prune_synthetic_device_edges(**scope, generator=generators[0])
            await counts(1, 2)
        return {"both_write_orders": True, "parallel_edges": True, "independent_owners": True,
                "replacements_and_pruning": True}
    finally:
        for generator in generators:
            await service.prune_synthetic_device_edges(**scope, generator=generator)
        await service.replace_observed_device_edges(**scope, owner_id=binding.owner_id, edges=original)


async def verify(directory: Path, artifact: dict) -> None:
    # Set operational mode before lazy engine creation; never print SQL bind
    # parameters, URLs, auth frames, or exception text from infrastructure clients.
    from app.core.config import get_settings
    from app.core.logging import configure_logging

    settings = get_settings()
    settings.APP_ENV = "verification"
    settings.LOG_LEVEL = "CRITICAL"
    settings.EXECUTION_MODE = "emulation"
    settings.TELEMETRY_RUNTIME_ADAPTER_MODE = "stub"
    configure_logging("CRITICAL")
    logging.disable(logging.CRITICAL)

    from emulation.topology import manifest

    from app.core.security import hash_password
    from app.db.neo4j import close_neo4j, init_neo4j
    from app.db.postgres import AsyncSessionLocal, get_engine
    from app.db.redis import close_redis, get_redis_client, init_redis
    from app.events.consumers.audit_consumer import AUDIT_HANDLERS
    from app.events.consumers.telemetry_consumer import handle_telemetry_event
    from app.events.consumers.topology_consumer import handle_topology_event
    from app.events.consumers.ws_push_consumer import WS_PUSH_HANDLERS
    from app.events.bus import process_entry
    from app.main import _build_emulation_adapter, _merge_handlers, app
    from app.modules.identity.repository import UserRepository
    from app.modules.telemetry.emulation import read_bounded_file
    from app.modules.telemetry.service import (
        TelemetryCollectorRunner,
        TelemetryIngestionService,
    )
    from scripts.bind_emulation import bind_emulation, save_binding

    root = Path(__file__).resolve().parents[2]
    control = root / "emulation" / "control.py"
    snapshot_path = root / "emulation" / "output" / "snapshot.json"
    docker = ["docker", "compose", "--project-directory", str(root / "emulation"),
              "-f", str(root / "emulation" / "compose.yaml")]
    artifact["stage"] = "preflight"
    processes = await asyncio.create_subprocess_exec(
        "pgrep", "-f", "uvicorn|gunicorn", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await processes.communicate()
    check(processes.returncode in (0, 1), "Cannot inspect backend processes")
    check(not stdout.strip(), "Active backend detected; stop it explicitly before this audit")
    check(not (await command(*docker, "ps", "-q", "--status", "running")).strip(),
          "Lab already running; verifier only starts/stops its own lab")
    check(not (await command(*docker, "ps", "-aq")).strip(),
          "Existing stopped lab container detected; preserve it and abort")

    actor_id = None
    binding = None
    owned_lab = False
    server = None
    server_task = None
    tasks = []
    groups = []
    errors = []
    pending = defaultdict(int)
    suffix = uuid.uuid4().hex
    email, password = f"audit-{suffix}@example.com", secrets.token_urlsafe(36)
    known_networks = set()
    scoped_events = defaultdict(int)
    group = f"emulation-audit-{suffix}"
    try:
        await init_redis()
        await init_neo4j()
        redis = get_redis_client()
        # A socket connected to Redis and blocked on XREADGROUP is evidence of
        # another collector even if it is not a local uvicorn process.
        clients = await redis.client_list()
        check(not any(c.get("cmd") in {"xreadgroup", "xread"} for c in clients),
              "Active Redis stream reader detected; refusing concurrent audit")
        async with AsyncSessionLocal() as db:
            repository = UserRepository(db)
            user = await repository.create(email, hash_password(password), f"Emulation audit {suffix}")
            actor_id = user.user_id
            await repository.assign_role(actor_id, "Admin")
            await db.commit()
        artifact["actor_user_id"] = str(actor_id)

        handlers = _merge_handlers(AUDIT_HANDLERS, WS_PUSH_HANDLERS,
            {"network.device.added": handle_topology_event,
             "telemetry.metric.ingested": handle_telemetry_event})
        consumer_slots = asyncio.Semaphore(8)
        series_locks = defaultdict(asyncio.Lock)

        async def consume(stream):
            while True:
                messages = await redis.xreadgroup(group, group, {stream: ">"}, count=100, block=500)
                for _, entries in messages:
                    async def dispatch(entry_id, fields):
                        try:
                            payload = json.loads(fields.get("payload", "{}"))
                            ours = str(payload.get("actor_id", "")) == str(actor_id) or (
                                payload.get("network_id") in known_networks)
                            if ours:
                                event_type = fields["event_type"]
                                if event_type == "network.network.created":
                                    known_networks.add(payload["network_id"])
                                pending[stream] += 1
                                tags = payload.get("tags", {})
                                series = (payload.get("device_id"), payload.get("metric"), tags.get("port_no"),
                                          tags.get("peer_host"), tags.get("flow_index"))
                                # Serialize each observed series, while unrelated
                                # metrics share a bounded connection-pool budget.
                                async with series_locks[series], consumer_slots:
                                    await process_entry(redis, stream, group, entry_id, fields, handlers)
                                scoped_events[event_type] += 1
                        except Exception as exc:  # noqa: BLE001 - sanitized live audit failure
                            errors.append(type(exc).__name__)
                        finally:
                            pending[stream] = max(0, pending[stream] - 1)
                            # ACK only our temporary group; shared group untouched.
                            await redis.xack(stream, group, entry_id)
                    await asyncio.gather(*(dispatch(entry_id, fields) for entry_id, fields in entries))

        for stream in ("stream:auth", "stream:org", "stream:network", "stream:telemetry"):
            await redis.xgroup_create(stream, group, id="$", mkstream=True)
            groups.append(stream)
            tasks.append(asyncio.create_task(consume(stream)))

        # Normal startup includes global backfills/shared-group readers. This audit
        # owns connection/consumer lifecycle above, not those global side effects.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.setblocking(False)
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_config=None,
                                               access_log=False, log_level="critical"))
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        for _ in range(100):
            if server.started:
                break
            check(not server_task.done(), "Isolated backend failed to start")
            await asyncio.sleep(0.05)
        check(server.started, "Isolated backend startup timed out")
        artifact["transport"] = "loopback HTTP and actual WebSocket; real DB/Redis/Neo4j"
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=30) as client:
            artifact["stage"] = "authenticated_bootstrap"
            binding = await bind_emulation(client, email=email, password=password, manifest=manifest(),
                org_slug=f"audit-{suffix}", workspace_name="Emulation audit", network_name="campus-small-v1")
            known_networks.add(str(binding.network_id))
            save_binding(binding, directory / "binding.json", snapshot_path)
            artifact.update(network_id=str(binding.network_id), workspace_id=str(binding.workspace_id),
                            binding_path=str(directory / "binding.json"))

            async def request(method, path, **kwargs):
                response = await client.request(method, path, **kwargs)
                check(response.status_code < 400, f"API {path} returned HTTP {response.status_code}")
                envelope = response.json()
                check(envelope.get("success") is True, "API returned unsuccessful envelope")
                return envelope

            tokens = (await request("POST", "/api/v1/auth/login", json={"email": email, "password": password}))["data"]
            token = tokens["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
            inventory = (await request("GET", f"/api/v1/networks/{binding.network_id}/devices",
                                      params={"page_size": 100}))["data"]
            device_ids = {str(v) for v in [*binding.switches.values(), *binding.hosts.values()]}
            check(inventory["total"] == 9 and {d["device_id"] for d in inventory["items"]} == device_ids,
                  "Returned inventory does not match stable binding")

            async def graph():
                nodes, edges, cursor = {}, {}, None
                for _ in range(10):
                    params = {"network_id": str(binding.network_id), "limit": 2}
                    if cursor:
                        params["cursor"] = cursor
                    envelope = await request("GET", "/api/v1/topology/graph", params=params)
                    for node in envelope["data"]["nodes"]:
                        nodes[node["device_id"]] = node
                    for edge in envelope["data"]["edges"]:
                        edges[(edge["source_id"], edge["target_id"], edge["metadata"].get("edge_key"))] = edge
                    cursor = envelope["meta"].get("next_cursor")
                    if not cursor:
                        return nodes, edges
                raise ValueError("Topology pagination exceeded bound")

            for _ in range(100):
                nodes, _ = await graph()
                if len(nodes) == 9:
                    break
                check(not errors, "Backend consumer failed projecting inventory")
                await asyncio.sleep(0.2)
            check(len(nodes) == 9, "Inventory projection did not reach nine nodes")
            artifact["stage"] = "lab_start"
            owned_lab = True
            await command(sys.executable, str(control), "start")
            settings.EMULATION_BINDING_PATH = str(directory / "binding.json")
            settings.EMULATION_SNAPSHOT_PATH = str(snapshot_path)
            adapter = await _build_emulation_adapter(settings, redis)
            runner = TelemetryCollectorRunner(TelemetryIngestionService(redis))
            expected_samples = {}
            poll_sequences = set()
            frames = []
            baseline = None
            checked_snapshot = None

            async def poll(*, leave_unacknowledged=False):
                nonlocal baseline, checked_snapshot
                samples = await adapter.poll()
                # Audit the adapter's retained validated input, not a second file
                # read that could race the producer's atomic replacement.
                snapshot = adapter._pending or adapter._previous
                if snapshot != checked_snapshot:
                    baseline, checked_snapshot = checked_snapshot, snapshot
                verify_measurements(snapshot, baseline, binding, samples)
                for index, sample in enumerate(samples):
                    prior = expected_samples.get(sample["event_id"])
                    check(prior is None or prior == sample, "Stable sample ID changed payload")
                    expected_samples[sample["event_id"]] = sample
                    poll_sequences.add((sample["tags"]["run_id"], sample["tags"]["sequence"]))
                    if not leave_unacknowledged or index < len(samples) // 2:
                        await runner.ingest_once(sample, str(uuid.uuid4()), event_id=sample["event_id"])
                if not leave_unacknowledged:
                    await adapter.acknowledge_batch(samples)
                return samples

            async def receive(ws):
                async for text in ws:
                    frame = json.loads(text)
                    if frame.get("event") == "telemetry.metric.ingested":
                        frames.append(frame)

            async with AsyncExitStack() as stack:
                ws = await stack.enter_async_context(connect(
                    f"ws://127.0.0.1:{port}/ws/telemetry?token={token}", max_queue=4096))
                await ws.send(json.dumps({"action": "subscribe", "channel": "telemetry",
                                         "filters": {"network_id": str(binding.network_id)}}))
                check(json.loads(await asyncio.wait_for(ws.recv(), 10))["event"] == "subscribed",
                      "WebSocket subscription rejected")
                receiver = asyncio.create_task(receive(ws))
                tasks.append(receiver)
                first = await poll(leave_unacknowledged=True)
                check(first and not any(s["metric"] == "throughput_mbps" for s in first),
                      "First counter sample fabricated a rate")
                pending_sequence = adapter._pending.sequence
                for _ in range(40):
                    await asyncio.sleep(0.2)
                    advanced = await adapter.reader.read()
                    if advanced.sequence > pending_sequence:
                        break
                check(advanced.sequence > pending_sequence, "Producer did not advance during unacknowledged batch")
                retry = await poll()
                check(retry == first, "Pending batch lost suffix when producer advanced")
                artifact["partial_publish_pending_retry"] = {
                    "prefix_published": len(first) // 2, "full_batch_replayed": len(retry),
                    "producer_advanced": True,
                    "method": "real prefix publication, withheld acknowledgement, full retry; no Redis outage injected",
                }
                artifact["stage"] = "workload_polling"
                traffic = asyncio.create_task(command(sys.executable, str(control), "traffic", timeout=60))
                tasks.append(traffic)
                deadline = time.monotonic() + 65
                while not traffic.done():
                    check(time.monotonic() < deadline, "Workload polling exceeded bound")
                    await asyncio.sleep(0.6)
                    await poll()
                await traffic
                await asyncio.sleep(2)
                last = await poll()
                workload = json.loads(await asyncio.to_thread(read_bounded_file,
                    root / "emulation" / "output" / "traffic.json", 1048576))
                check(workload["passed"] is True, "Producer independent workload verification failed")
                check(workload["run_id"] == last[0]["tags"]["run_id"], "Workload run mismatch")
                # Explicit retry of the exact last adapter batch through real ingestion.
                for sample in last:
                    await runner.ingest_once(sample, str(uuid.uuid4()), event_id=sample["event_id"])
                await drain_owned_batch(redis, group, errors)

                artifact["stage"] = "persistence_and_queries"
                async def history(**params):
                    return (await request("GET", "/api/v1/telemetry/history", params={
                        "network_id": str(binding.network_id), "page_size": 200, **params}))["data"]

                # Successful stream ACK follows committed persistence. After the
                # bounded drain, compare once rather than adding a second wait.
                current = await history(page_size=1)
                artifact["persistence_diagnostic"] = {
                    "expected_samples": len(expected_samples), "persisted_samples": current["total"],
                    "stream_entries": await redis.xlen("stream:telemetry"),
                    "groups": await redis.xinfo_groups("stream:telemetry"),
                    "consumer_events": dict(scoped_events), "consumer_error_types": list(errors),
                }
                check(await redis.xlen("stream:dead_letter") == 0, "Owned consumer dead-lettered an event")
                check(current["total"] == len(expected_samples), "Persistence missing or duplicate samples")
                rows = []
                for page in range(1, math.ceil(current["total"] / 200) + 1):
                    rows.extend((await history(page=page))["items"])
                check(len({r["event_id"] for r in rows}) == len(expected_samples), "Duplicate persisted event IDs")
                observation_keys = [(
                    r["device_id"], r["metric"], r["observed_at"],
                    r["tags"].get("port_no"), r["tags"].get("flow_index"),
                    r["tags"].get("peer_host"), r["tags"].get("duration_sec"),
                    r["tags"].get("duration_start_sec"), r["tags"].get("interval_start"),
                ) for r in rows]
                check(len(set(observation_keys)) == len(rows), "Cached observations duplicated across snapshots")
                for row in rows:
                    expected = expected_samples[row["event_id"]]
                    for key in ("device_id", "network_id", "workspace_id", "metric", "value", "unit", "source", "tags"):
                        check(row[key] == expected[key], f"Persistence mismatch: {key}")
                    check(row["device_id"] in device_ids and row["tags"]["synthetic"] is False,
                          "Fabricated or unbound telemetry")

                maxima = {metric: max((r["value"] for r in rows if r["metric"] == metric), default=None)
                          for metric in ("throughput_mbps", "link_utilization_percent", "latency_ms",
                                         "packet_loss_percent", "queue_backlog_bytes", "queue_backlog_packets",
                                          "port_tx_bytes", "flow_byte_count")}
                artifact["maxima"] = maxima
                for metric in ("throughput_mbps", "link_utilization_percent", "latency_ms", "queue_backlog_bytes",
                               "queue_backlog_packets", "port_tx_bytes", "flow_byte_count"):
                    check(maxima[metric] is not None and maxima[metric] > 0, f"No nonzero workload measurement: {metric}")
                check(maxima["packet_loss_percent"] is not None, "Probe loss measurements absent")
                check(all(r["tags"].get("latency_semantics") == "RTT" for r in rows if r["metric"] == "latency_ms"),
                      "RTT semantics lost")
                check(all(r["tags"].get("loss_semantics") == "probe" for r in rows if r["metric"] == "packet_loss_percent"),
                      "Probe loss mislabeled as PDR")

                nodes, edges = await graph()
                check(set(nodes) == device_ids and len(edges) == 11, "Expected nine nodes and eleven observed edges")
                check(all(e["metadata"].get("observation_owner") == binding.owner_id
                          and e["metadata"].get("synthetic") is False for e in edges.values()),
                      "Observed edge provenance mismatch")
                artifact["topology_writer_isolation"] = await verify_topology_writers(binding, edges)
                times = [datetime.fromisoformat(r["observed_at"]) for r in rows]
                start, end = min(times), max(times) + timedelta(microseconds=1)
                bounds = {"start_time": start.isoformat(), "end_time": end.isoformat()}
                aggregates = {}
                for aggregation in ("avg", "min", "max", "sum"):
                    result = await history(metric="throughput_mbps", aggregation=aggregation,
                                           bucket_seconds=60, **bounds)
                    independent = defaultdict(list)
                    for row in rows:
                        if row["metric"] == "throughput_mbps":
                            bucket = int(datetime.fromisoformat(row["observed_at"]).timestamp()) // 60 * 60
                            independent[(row["device_id"], row["metric"], row["unit"], row["source"],
                                         str(row["tags"]["port_no"]), row["tags"].get("peer_host"),
                                         row["tags"].get("run_id"), bucket)].append(row["value"])
                    check(result["total"] == len(independent) == len(result["items"]), "Aggregation dimension/count mismatch")
                    for item in result["items"]:
                        key = (item["device_id"], item["metric"], item["unit"], item["source"],
                               item["port_no"], item["peer_host"], item["run_id"],
                               int(datetime.fromisoformat(item["bucket_start"]).timestamp()))
                        values = independent[key]
                        expected = {"avg": sum(values) / len(values), "min": min(values),
                                    "max": max(values), "sum": sum(values)}[aggregation]
                        check(item["sample_count"] == len(values) and math.isclose(item["value"], expected, rel_tol=1e-9),
                              "Aggregation result mismatch")
                    aggregates[aggregation] = result["total"]
                exclusive = await history(end_time=start.isoformat())
                check(exclusive["total"] == 0, "History end-time not exclusive")
                inclusive = await history(**bounds, page_size=1)
                check(inclusive["total"] == len(rows), "History start-time not inclusive")
                device = str(binding.switches["0000000000000004"])
                device_history = (await request("GET", f"/api/v1/telemetry/device/{device}",
                    params={"metric": "throughput_mbps", **bounds}))["data"]
                check(device_history["total"] > 0 and all(r["device_id"] == device for r in device_history["items"]),
                      "Device history scope mismatch")
                for _ in range(50):
                    if len(frames) >= len(rows):
                        break
                    await asyncio.sleep(0.1)
                check(len(frames) == len(rows), "WebSocket missing or duplicate metric delivery")
                for frame in frames:
                    metric = frame["data"]["metric"]
                    expected = expected_samples[metric["event_id"]]
                    check(all(metric[key] == expected[key] for key in (
                        "device_id", "network_id", "workspace_id", "metric", "value", "unit", "source", "tags")),
                        "WebSocket payload differs from source measurement")
                check(len({frame["data"]["metric"]["event_id"] for frame in frames}) == len(rows),
                      "Duplicate WebSocket event identity")
                artifact.update(nodes=len(nodes), observed_edges=len(edges), unique_rows=len(rows),
                    polled_snapshots=len(poll_sequences), retried_samples=len(last),
                    websocket_frames=len(frames), maxima=maxima, aggregation_groups=aggregates,
                    first_rates_unavailable=True, duplicate_rows=0, stable_mapping=True,
                    exact_ingestion_payload_match=True, source_calculations_verified=True,
                    cached_observations_deduplicated=True, rate_clock="openflow_port_duration",
                    websocket_payloads_verified=True, history_bounds_verified=True,
                    workload={"passed": workload["passed"],
                        "openflow_tx_bytes_delta": workload["openflow_tx_bytes_delta"],
                        "ovs_cli_tx_bytes_delta": workload["ovs_cli_tx_bytes_delta"],
                        "delivered_bytes": workload["iperf3"]["server"]["sum_received"]["bytes"]})
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)

            await request("POST", "/api/v1/auth/logout")
            client.headers.pop("Authorization", None)
            async with AsyncSessionLocal() as db:
                actor = await UserRepository(db).get_by_id(actor_id)
                actor.is_active = False
                await db.commit()
            artifact["actor_disabled"] = True
            try:
                await adapter.poll()
            except HTTPException as exc:
                check(exc.status_code == 404, "Revocation failed for an unrelated reason")
                artifact["revoked_actor_poll_denied"] = True
            else:
                raise ValueError("Disabled actor still authorized to poll")
            check(not errors, "Backend consumer errors occurred")
            artifact["consumer_events"] = dict(scoped_events)
            artifact["status"] = "passed"
            artifact["stage"] = "complete"
    finally:
        # Attempt every cleanup even when infrastructure errors break an earlier
        # cleanup step. Never kill an existing user backend or stop a borrowed lab.
        cleanup_errors = []

        async def cleanup(action):
            try:
                await asyncio.wait_for(action(), 45)
            except Exception as exc:  # noqa: BLE001 - continue remaining owned cleanup
                cleanup_errors.append(type(exc).__name__)

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if server is not None:
            server.should_exit = True
        if server_task is not None:
            await cleanup(lambda: asyncio.wait_for(server_task, 15))

        async def disable_actor():
            async with AsyncSessionLocal() as db:
                actor = await UserRepository(db).get_by_id(actor_id)
                if actor is not None:
                    actor.is_active = False
                    await db.commit()
                    artifact["actor_disabled"] = True

        if actor_id is not None:
            await cleanup(disable_actor)
        if groups:
            redis = get_redis_client()
            for stream in groups:
                await cleanup(lambda stream=stream: redis.xgroup_destroy(stream, group))
        await cleanup(close_redis)
        await cleanup(close_neo4j)
        await cleanup(get_engine().dispose)
        if owned_lab:
            async def stop_lab():
                await command(sys.executable, str(control), "stop", timeout=40)
                artifact["owned_lab_stopped"] = True
            await cleanup(stop_lab)
        if cleanup_errors:
            artifact["cleanup_errors"] = cleanup_errors
            artifact["status"] = "blocked"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly authorize dedicated audit writes and lab lifecycle")
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; no infrastructure changes made")
    if not 120 <= args.timeout_seconds <= 600:
        parser.error("timeout must be 120..600 seconds")
    parent = Path("/tmp/opencode")
    if not parent.is_dir() or parent.is_symlink():
        parser.error("/tmp/opencode must already exist as a real operator directory")
    directory = Path(tempfile.mkdtemp(prefix="emulation-audit-", dir=parent))
    artifact = {"status": "blocked", "started_at": datetime.now(UTC).isoformat(),
        "scope": "dedicated ephemeral audit actor; evidence rows retained, actor disabled",
        "limitations": ["Normal shared consumer-group recovery/backfill lifecycle not exercised",
                        "Zero measured probe loss is valid; no artificial loss is injected",
                        "No control actions, evaluator, durable outbox or exactly-once certification"]}
    try:
        async with asyncio.timeout(args.timeout_seconds):
            await verify(directory, artifact)
    except Exception as exc:  # noqa: BLE001 - never expose upstream credentials in errors
        artifact["status"] = "blocked"
        artifact["error_type"] = type(exc).__name__
        # Only our explicit assertions are safe; upstream exception strings can
        # contain DSNs, SQL parameters or WebSocket token URLs.
        if isinstance(exc, ValueError) and exc.__traceback__:
            tb = exc.__traceback__
            while tb.tb_next:
                tb = tb.tb_next
            if tb.tb_frame.f_code.co_name == "check":
                artifact["blocker"] = str(exc)
    artifact["finished_at"] = datetime.now(UTC).isoformat()
    path = directory / "result.json"
    path.write_text(json.dumps(artifact, indent=2) + "\n")
    os.chmod(path, 0o600)
    print(json.dumps({"status": artifact["status"], "stage": artifact.get("stage"), "artifact": str(path)}))
    if artifact["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
