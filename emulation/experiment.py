"""Opt-in, single-owner ADR-011 measured environment; no learning dependencies."""

import json
import math
import os
import select
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path

from emulation.actions import HOST_MAP, NAMES, PORTS, Actions
from emulation.experiment_client import REQUEST_LIMIT, RESPONSE_LIMIT, SOCKET, decode
from emulation.measurements import atomicJson, parsePing, parseQueue, utcNow
from emulation.runner import stopProcess
from emulation.workloads import SCENARIOS, schedule

ROUTES = (("access1", "dist1", "access2"), ("access1", "dist2", "access2"))
FIXTURE_COOKIE = "0x4e414e4600000007"
FIELDS = {"version", "command", "episode_id", "step_index", "seed", "scenario", "action",
          "mode", "window_seconds", "episode_steps"}


def validate(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("Exact ADR-011 request fields required")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported version")
    if value["command"] not in ("reset", "step", "close") or value["mode"] not in ("sdn", "ospf"):
        raise ValueError("Invalid command or mode")
    window = value["window_seconds"]
    if type(window) not in (int, float) or not math.isfinite(window) or not 2 <= window <= 10:
        raise ValueError("window_seconds must be finite in 2..10")
    if type(value["episode_steps"]) is not int or not 2 <= value["episode_steps"] <= 64:
        raise ValueError("episode_steps must be an integer in 2..64")
    if value["seed"] is not None and (type(value["seed"]) is not int or
                                     not 0 <= value["seed"] <= 2147483647):
        raise ValueError("Invalid seed")
    if value["scenario"] is not None and value["scenario"] not in SCENARIOS:
        raise ValueError("Invalid scenario")
    if value["episode_id"] is not None and (not isinstance(value["episode_id"], str) or
            str(uuid.UUID(value["episode_id"])) != value["episode_id"]):
        raise ValueError("episode_id must be a canonical UUID")
    if value["step_index"] is not None and (type(value["step_index"]) is not int or
                                           not 0 <= value["step_index"] <= 64):
        raise ValueError("Invalid step_index")
    if value["action"] is not None and (type(value["action"]) is not int or value["action"] not in (0, 1)):
        raise ValueError("Invalid action")
    if value["command"] == "reset":
        if any(value[k] is not None for k in ("episode_id", "step_index", "action")):
            raise ValueError("reset requires null identity, index and action")
        if value["seed"] is None or value["scenario"] is None:
            raise ValueError("reset requires seed and scenario")
    elif value["command"] == "step":
        if any(value[k] is None for k in ("episode_id", "step_index", "action")):
            raise ValueError("step requires identity, index and action")
    elif value["action"] is not None:
        raise ValueError("close requires null action")
    return value


def pathPorts():
    return [[(node, PORTS[node, peer][0]) for node, peer in
             ((route[0], route[1]), (route[1], route[0]),
              (route[1], route[2]), (route[2], route[1]))] for route in ROUTES]


class SdnRouting:
    def __init__(self, lab):
        self.lab = lab
        self.driver = Actions(lab)
        self.prepared = None
        self.action = None
        self.fixturePath = None

    def change(self, action):
        if self.action == action:
            self.driver.verify(self.prepared)
            return {"changed": False, "path": list(ROUTES[action]), "readback": "verified"}
        if self.prepared is not None:
            self.driver.rollback(self.prepared)
            self.prepared = None
        plan = {"operation": "reroute", "source_host": "h1", "destination_host": "h3",
                "paths": [list(ROUTES[action])], "weights": [1], "dscp": None, "rate_mbps": None}
        self.prepared = self.driver.prepare(plan)
        self.driver.apply(self.prepared, self.lab.checkController)
        self.driver.verify(self.prepared)
        self.action = action
        return {"changed": True, "path": list(ROUTES[action]), "readback": "verified",
                "strategy": "break-before-make; baseline forwarding may carry traffic in gap"}

    def fixture(self, path):
        if self.fixturePath == path:
            return
        self.clearFixture()
        route = ROUTES[path]
        for src, dst, nodes in ((HOST_MAP["h2"], HOST_MAP["h4"], route),
                                (HOST_MAP["h4"], HOST_MAP["h2"], tuple(reversed(route)))):
            for index, node in enumerate(nodes):
                ingress = src["port_no"] if index == 0 else PORTS[node, nodes[index - 1]][0]
                egress = dst["port_no"] if index == 2 else PORTS[node, nodes[index + 1]][0]
                flow = (f"cookie={FIXTURE_COOKIE},table=1,priority=25000,in_port={ingress},"
                        f"ip,dl_src={src['mac']},dl_dst={dst['mac']},nw_src={src['ipv4']},"
                        f"nw_dst={dst['ipv4']},actions=output:{egress}")
                self.driver.of("add-flow", node, flow)
                rows = self.driver.of("dump-flows", node, f"cookie={FIXTURE_COOKIE}/-1,table=1")
                if not any(all(token in line.replace(" ", ",").split(",")
                               for token in flow.split(",actions=")[0].split(","))
                           and line.split(" actions=")[-1] == f"output:{egress}"
                           for line in rows.splitlines()):
                    raise RuntimeError("Fixture flow readback failed")
        self.fixturePath = path

    def clearFixture(self):
        for node in NAMES.values():
            self.driver.of("del-flows", node, f"cookie={FIXTURE_COOKIE}/-1,table=1")
            if FIXTURE_COOKIE in self.driver.of("dump-flows", node, "table=1"):
                raise RuntimeError("Fixture cleanup failed")
        self.fixturePath = None

    def close(self):
        try:
            if self.prepared is not None:
                self.driver.rollback(self.prepared)
                self.prepared = None
            self.driver.reconcile()
        finally:
            self.clearFixture()
        self.action = None


def counters(lab):
    result = {}
    for ports in pathPorts():
        for node, port in ports:
            interface = f"{node}-eth{port}"
            # Kernel link counters are local, synchronous and independently timed.
            process = lab.net[node].popen(["ip", "-s", "-j", "link", "show", "dev", interface],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            text, _ = process.communicate(timeout=2)
            if process.returncode:
                raise RuntimeError("Link counter read failed")
            row = json.loads(text)[0]
            stats = row.get("stats64", row.get("stats"))
            result[interface] = {"tx_bytes": stats["tx"]["bytes"],
                                 "rx_bytes": stats["rx"]["bytes"],
                                 "monotonic_seconds": time.monotonic()}
    return result


def utilization(before, after):
    values, windows = [], {}
    for ports in pathPorts():
        rates = []
        for node, port in ports:
            key = f"{node}-eth{port}"
            if key not in before or key not in after:
                continue
            a, b = before[key], after[key]
            duration = b["monotonic_seconds"] - a["monotonic_seconds"]
            delta = b["tx_bytes"] - a["tx_bytes"]
            windows[key] = {"before": a, "after": b, "duration_seconds": duration}
            if duration > 0 and delta >= 0:
                rates.append(delta * 8 / duration / 20e6)
        values.append(max(rates) if len(rates) == 4 else None)
    return values, windows


class Experiment:
    def __init__(self, lab, mode="sdn", routing=None):
        self.lab, self.mode = lab, mode
        self.routing = routing if routing is not None else SdnRouting(lab)
        self.episode = None
        self.index = 0
        self.done = True
        self.closed = False
        self.changedAt = time.monotonic()
        self.lastRequest = time.monotonic()

    def handle(self, request):
        try:
            value = validate(request)
            if self.closed or value["mode"] != self.mode:
                raise ValueError("Server closed or mode mismatch")
            if value["command"] == "reset":
                if not self.done:
                    raise ValueError("Active episode must finish or close before reset")
                self.routing.close()
                self.episode = str(uuid.uuid4())
                self.config = value
                self.phases = schedule(value["seed"], value["scenario"], value["episode_steps"])
                self.index, self.done = 0, False
                self.started = time.monotonic()
                atomicJson(self.lab.output / f"experiment-{self.episode}-schedule.json", self.phases)
                data = self.measure(0)
            else:
                if value["episode_id"] != self.episode or value["step_index"] != self.index + (value["command"] == "step"):
                    raise ValueError("Wrong episode or repeated/out-of-order step")
                if self.episode is not None and any(value[k] != self.config[k] for k in
                                                    ("window_seconds", "episode_steps")):
                    raise ValueError("Episode configuration is frozen")
                if self.episode is not None and any(value[k] is not None and value[k] != self.config[k]
                                                    for k in ("seed", "scenario")):
                    raise ValueError("Episode workload is frozen")
                if value["command"] == "close":
                    self.routing.close()
                    self.closed = True
                    data = {"closed": True, "cleanup_verified": True, "episode_id": self.episode}
                else:
                    if self.done:
                        raise ValueError("Episode already finished")
                    self.index += 1
                    data = self.measure(value["action"])
            return {"version": 1, "ok": True, "error": None, "data": data}
        except (ValueError, TypeError, AttributeError) as error:
            return {"version": 1, "ok": False, "error": str(error)[:200], "data": None}
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            self.lab.stopping = True
            return {"version": 1, "ok": False, "error": str(error)[:200], "data": None}

    def measure(self, action):
        phase = self.phases[self.index]
        window = self.config["window_seconds"]
        observation = {"path_utilization": [None, None], "path_queue_packets": [None, None],
                       "latency_ms": None, "loss_fraction": None, "goodput_mbps": None,
                       "offered_mbps": phase["offered_mbps"], "background_mbps": phase["background_mbps"],
                       "previous_action": action, "seconds_since_change": 0.0}
        evidence = {"phase": phase, "desired_window_seconds": window,
                    "initial_window": self.index == 0, "decision_windows": self.index,
                    "measurement_source": "real namespace UDP, ping, kernel link counters, leaf netem",
                    "transition_traffic_included": True}
        processes = []
        began = time.monotonic()
        error = None

        def spawn(host, args):
            process = self.lab.net[host].popen(args, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "LC_ALL": "C"})
            processes.append(process)
            self.lab.processes.append(process)
            return process

        try:
            self.routing.fixture(phase["background_path"])
            if self.index == 0:
                evidence["initial_route"] = self.routing.change(action)
                self.changedAt = time.monotonic()
            receivers = [spawn(host, ["python", "-m", "emulation.workloads", "receive"])
                         for host in ("h3", "h4")]
            for process in receivers:
                if not select.select([process.stdout], [], [], 2)[0] or decode(process.stdout.readline()) != {"ready": True}:
                    raise RuntimeError("UDP receiver did not become ready")
            before = counters(self.lab)
            loadStart = time.monotonic()
            senders = [spawn(host, ["python", "-m", "emulation.workloads", "send", "--target", target,
                                   "--mbps", str(phase[rate])]) for host, target, rate in
                       (("h1", "10.77.0.3", "offered_mbps"), ("h2", "10.77.0.4", "background_mbps"))]
            ping = spawn("h1", ["ping", "-n", "-i", "0.2", "-W", "1", "10.77.0.3"])
            # Traffic is already running when break-before-make begins.
            time.sleep(0.1)
            controlStart = time.monotonic()
            evidence["route"] = self.routing.change(action)
            if evidence["route"]["changed"]:
                self.changedAt = time.monotonic()
            evidence["control_overhead_seconds"] = time.monotonic() - controlStart
            measuredStart = time.monotonic()
            peaks, samples = [None, None], [0, 0]
            while time.monotonic() - measuredStart < window:
                self.lab.checkController()
                if any(p.poll() is not None for p in receivers + senders):
                    raise RuntimeError("UDP worker exited before window end")
                for path, ports in enumerate(pathPorts()):
                    for node, port in ports:
                        process = self.lab.net[node].popen(["tc", "-s", "-j", "qdisc", "show", "dev", f"{node}-eth{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        text, _ = process.communicate(timeout=2)
                        queue = parseQueue(text)
                        if process.returncode == 0 and queue is not None:
                            samples[path] += 1
                            peaks[path] = max(peaks[path] or 0, queue["backlog_packets"])
                time.sleep(0.08)
            evidence["measured_window_seconds"] = time.monotonic() - measuredStart
            for process in senders:
                process.send_signal(signal.SIGTERM)
            sent = [decode(p.communicate(timeout=2)[0]) for p in senders]
            loadEnd = time.monotonic()
            ping.send_signal(signal.SIGINT)
            pingText = ping.communicate(timeout=2)[0].decode("ascii", errors="replace")
            time.sleep(0.25)  # Drain in-flight packets, included in counter interval, not hidden loss.
            for process in receivers:
                process.send_signal(signal.SIGTERM)
            received = [decode(p.communicate(timeout=2)[0]) for p in receivers]
            after = counters(self.lab)
            rates, raw = utilization(before, after)
            probe = parsePing(pingText, "h1", "h3", loadEnd - loadStart, utcNow())
            evidence.update({"counter_windows": raw, "queue_samples": samples,
                             "udp_sent": sent, "udp_received": received, "ping": probe,
                             "load_interval_seconds": loadEnd - loadStart,
                             "queue_sampling": "peak sampled during post-control load, 80ms plus collection time"})
            if any(s["packets"] <= 0 or not 0 <= r["packets"] <= s["packets"]
                   for s, r in zip(sent, received)):
                raise RuntimeError("Invalid UDP sender/receiver counts")
            observation.update({"path_utilization": rates, "path_queue_packets": peaks,
                                "latency_ms": probe["rtt_avg_ms"] if probe else None,
                                "loss_fraction": 1 - received[0]["packets"] / sent[0]["packets"],
                                "goodput_mbps": received[0]["bytes"] * 8 / (loadEnd - loadStart) / 1e6,
                                "seconds_since_change": time.monotonic() - self.changedAt})
            if probe is None or probe["rtt_avg_ms"] is None or None in rates or None in peaks:
                raise RuntimeError("Incomplete measurement window")
            if evidence["measured_window_seconds"] > window + 2:
                raise RuntimeError("Measurement window exceeded tolerance")
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as failure:
            error = str(failure)[:200]
            self.done = True
        finally:
            for process in processes:
                stopProcess(process)
                self.lab.processes.remove(process)
        self.done = self.done or self.index >= self.config["episode_steps"]
        if self.done:
            try:
                self.routing.close()
                evidence["cleanup_verified"] = True
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
                error = "Routing cleanup uncertain; lab shutting down"
                evidence["cleanup_verified"] = False
                self.lab.stopping = True
        evidence.update({"error": error, "transition_wall_seconds": time.monotonic() - began,
                         "episode_wall_seconds": time.monotonic() - self.started})
        data = {"episode_id": self.episode, "step_index": self.index, "mode": self.mode,
                "seed": self.config["seed"], "scenario": self.config["scenario"],
                "terminated": self.done and error is None, "truncated": error is not None,
                "observation": observation, "evidence": evidence}
        atomicJson(self.lab.output / f"experiment-{self.episode}-{self.index:02}.json", data)
        return data

    def serve(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(SOCKET)
            os.chmod(SOCKET, 0o600)
            server.listen(1)
            server.settimeout(1)
            try:
                while not self.closed and not self.lab.stopping:
                    if time.monotonic() - self.lastRequest > 300:
                        raise RuntimeError("Experiment idle watchdog expired")
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        connection.settimeout(2)
                        try:
                            raw = bytearray()
                            while len(raw) <= REQUEST_LIMIT:
                                part = connection.recv(REQUEST_LIMIT + 1 - len(raw))
                                if not part:
                                    break
                                raw.extend(part)
                            if len(raw) > REQUEST_LIMIT:
                                raise ValueError("Request exceeds 4096 bytes")
                            self.lastRequest = time.monotonic()
                            result = self.handle(decode(raw))
                        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as failure:
                            result = {"version": 1, "ok": False, "error": str(failure)[:200], "data": None}
                        payload = json.dumps(result, allow_nan=False).encode("ascii")
                        if len(payload) > RESPONSE_LIMIT:
                            raise RuntimeError("Response bound exceeded")
                        try:
                            connection.sendall(payload)
                        except OSError:
                            # A lost response cannot safely be replayed. Close the owner.
                            self.closed = True
            finally:
                self.routing.close()
                Path(SOCKET).unlink(missing_ok=True)
