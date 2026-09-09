"""Real, non-learning FRR OSPF baseline for ADR-011, never an SPF simulation.

Trusted isolated container only: ``python -m emulation.ospf --verify``.
No OVS, Ryu, static router routes, policy routing or background route pinning.
The manifest graph/shaping is shared with SDN, but Linux L3 forwarding, /30
addressing, OSPF control traffic and competing background paths are NOT an
apples-to-apples forwarding comparison. ``policy`` is included in live evidence.

Integration: OSPFNetwork (alias OSPFEnv), start()->self, close(), net/get(name),
hostAddresses[name]->IPv4, hosts[name]->{ipv4,cidr,gateway,interface},
pathInterfaces(0|1)->[{node,interface,port_no,capacity_mbps}], counters()/queues()
return per-router-interface rows; routePath(src,dst) walks actual kernel routes.
All process/measurement methods are synchronous; the experiment owner supplies
serialization, workload windows and exclusive transport/mailbox ownership.
"""

import argparse
import fcntl
import json
import math
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from emulation.measurements import parsePing, parseQueue, utcNow
from emulation.runner import requireContainer, stopProcess
from emulation.topology import HOSTS, LINKS, SWITCHES, TOPOLOGY_ID

ROUTERS = tuple(row["name"] for row in SWITCHES)
ROUTER_IDS = {name: f"10.255.0.{i}" for i, name in enumerate(ROUTERS, 1)}
PATHS = (("access1", "dist1", "access2"), ("access1", "dist2", "access2"))
POLICY = {
    "protocol": "FRRouting OSPFv2 (IP protocol 89)",
    "area": "0.0.0.0",
    "maximum_paths": 1,
    "cost": "100 * ceil(100 / capacity_mbps) + one_based_manifest_link_index",
    "tie_break": "Explicit link-index cost perturbation; dist1 preferred on this graph",
    "background": "h2->h4 follows actual OSPF/kernel routes, never fixture-pinned",
    "comparison_limitations": [
        "Linux L3 forwarding rather than OVS OpenFlow L2 forwarding",
        "Per-link 10.78.k.0/30 addressing rather than the SDN shared 10.77.0.0/24",
        "Single next hop, explicit perturbed bandwidth costs, no ECMP load sharing",
        "OSPF control packets share shaped links and interface counters",
        "Background placement can differ from the SDN fixture; not apples-to-apples",
    ],
}


def linkPlan():
    """Pure deterministic addressing/cost plan, in unchanged manifest link order."""
    return [
        {
            **link,
            "index": index,
            "subnet": f"10.78.{index}.0/30",
            "cost": 100 * math.ceil(100 / link["capacity_mbps"]) + index,
            "endpoints": [
                {
                    "node": node,
                    "port_no": port,
                    "interface": f"{node}-eth{port}",
                    "ipv4": f"10.78.{index}.{side}",
                    "cidr": f"10.78.{index}.{side}/30",
                    "peer": link["b" if side == 1 else "a"][0],
                }
                for side, (node, port) in enumerate((link["a"], link["b"]), 1)
            ],
        }
        for index, link in enumerate(LINKS, 1)
    ]


def routerConfig(name):
    if name not in ROUTERS:
        raise ValueError("Unknown campus router")
    lines = [f"hostname {name}", "log stdout", "!"]
    active = []
    for link in linkPlan():
        for endpoint in link["endpoints"]:
            if endpoint["node"] != name:
                continue
            interface = endpoint["interface"]
            lines.extend([
                f"interface {interface}",
                f" bandwidth {link['capacity_mbps'] * 1000}",
                " ip ospf area 0.0.0.0",
                f" ip ospf cost {link['cost']}",
            ])
            if endpoint["peer"] in ROUTERS:
                active.append(interface)
                lines.extend([
                    " ip ospf network point-to-point",
                    " ip ospf hello-interval 1",
                    " ip ospf dead-interval 4",
                ])
            lines.append("!")
    lines.extend([
        "router ospf", f" ospf router-id {ROUTER_IDS[name]}",
        " auto-cost reference-bandwidth 100", " maximum-paths 1",
        " passive-interface default",
        *(f" no passive-interface {interface}" for interface in active),
        "!", "",
    ])
    return "\n".join(lines)


def fullNeighbors(value, name):
    """Validate identities AND interfaces, not just a count of 'Full' strings."""
    expected = {
        (ROUTER_IDS[endpoint["peer"]], endpoint["interface"])
        for link in linkPlan() for endpoint in link["endpoints"]
        if endpoint["node"] == name and endpoint["peer"] in ROUTERS
    }
    if not isinstance(value, dict):
        return False
    observed = set()
    for routerId, rows in value.items():
        if not isinstance(rows, list):
            return False
        for row in rows:
            if not isinstance(row, dict) or not row.get("nbrState", "").startswith("Full"):
                return False
            observed.add((routerId, row.get("ifaceName", "").split(":")[0]))
    return observed == expected


class OSPFNetwork:
    """Own nine Mininet namespaces and ten foreground FRR processes."""

    def __init__(self):
        self.net = None
        self.directory = None
        self.lock = None
        self.processes = []
        self.logs = []
        self.plan = linkPlan()
        self.policy = dict(POLICY)
        self.hosts = {
            endpoint["node"]: {
                key: endpoint[key] for key in ("ipv4", "cidr", "interface")
            } | {"gateway": link["endpoints"][0]["ipv4"]}
            for link in self.plan for endpoint in link["endpoints"]
            if endpoint["node"] not in ROUTERS
        }
        self.hostAddresses = {name: host["ipv4"] for name, host in self.hosts.items()}

    def get(self, name):
        if self.net is None:
            raise RuntimeError("OSPF network is not started")
        return self.net.get(name)

    def command(self, name, args, timeout=5):
        process = self.get(name).popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, err = process.communicate(timeout=timeout)
        except BaseException:
            stopProcess(process)
            raise
        if process.returncode:
            raise RuntimeError(f"{name}: {args[0]} failed: {err.decode(errors='replace')[:1000]}")
        return out.decode(errors="replace")

    def vty(self, name, command):
        if name not in ROUTERS or self.directory is None:
            raise ValueError("Unknown or unstarted OSPF router")
        if command not in ("show ip ospf neighbor json", "show ip route ospf json",
                           "show ip ospf interface json", "show version"):
            raise ValueError("Only fixed read-only FRR evidence commands are allowed")
        text = self.command(name, [
            "vtysh", "--vty_socket", str(self.directory / name), "-c", command,
        ])
        return json.loads(text) if command.endswith(" json") else text

    def checkProcesses(self):
        for name, daemon, process in self.processes:
            if process.poll() is not None:
                log = (self.directory / name / f"{daemon}.log").read_text()[-2000:]
                raise RuntimeError(f"{name}/{daemon} exited: {log}")

    def start(self):
        if self.net is not None:
            raise RuntimeError("OSPF network already started")
        requireContainer()
        if os.environ.get("EMULATION_CONTROL_ENABLED", "false").lower() == "true":
            raise RuntimeError("OSPF cannot run with manual mailbox control")
        from mininet.link import TCLink
        from mininet.net import Mininet
        from mininet.node import Host

        class LinuxRouter(Host):
            """Forwarding is configured below through this node's namespace only."""

        try:
            Path("/run/nanfo").mkdir(exist_ok=True)
            self.lock = os.open("/run/nanfo/ospf.lock", os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.directory = Path(tempfile.mkdtemp(prefix="ospf-", dir="/run/nanfo"))
            self.directory.chmod(0o755)
            # Upstream Mininet.init writes global limits/sysctls even with no OVS.
            Mininet.inited = True
            self.net = Mininet(controller=None, link=TCLink, build=False,
                               autoSetMacs=False, autoStaticArp=False)
            for name in ROUTERS:
                self.net.addHost(name, cls=LinuxRouter, ip=None, inNamespace=True)
            for host in HOSTS:
                self.net.addHost(host["name"], ip=None, mac=host["mac"], inNamespace=True)
            for link in self.plan:
                a, ap = link["a"]
                b, bp = link["b"]
                self.net.addLink(a, b, port1=ap, port2=bp, bw=link["capacity_mbps"],
                                 delay=f"{link['delay_ms']}ms",
                                 max_queue_size=link["max_queue_size"], use_htb=True)
            self.net.build()
            self.net.start()
            for link in self.plan:
                for endpoint in link["endpoints"]:
                    self.command(endpoint["node"], ["ip", "addr", "replace", endpoint["cidr"],
                                                    "dev", endpoint["interface"]])
            for name in (*ROUTERS, *self.hosts):
                self.command(name, ["ip", "link", "set", "lo", "up"])
                settings = ["net.ipv4.conf.all.rp_filter=0", "net.ipv4.conf.default.rp_filter=0"]
                if name in ROUTERS:
                    settings += ["net.ipv4.ip_forward=1", "net.ipv4.conf.all.send_redirects=0",
                                 "net.ipv4.conf.default.send_redirects=0"]
                for interface in self.get(name).intfList():
                    settings += [f"net.ipv4.conf.{interface.name}.rp_filter=0"]
                    if name in ROUTERS:
                        settings += [f"net.ipv4.conf.{interface.name}.send_redirects=0"]
                self.command(name, ["sysctl", "-qw", *settings])
            for name, host in self.hosts.items():
                self.command(name, ["ip", "route", "replace", "default", "via", host["gateway"]])
            user = pwd.getpwnam("frr")
            for name in ROUTERS:
                directory = self.directory / name
                directory.mkdir()
                directory.chmod(0o750)
                os.chown(directory, user.pw_uid, user.pw_gid)
                for daemon in ("zebra", "ospfd"):
                    config = directory / f"{daemon}.conf"
                    config.write_text(routerConfig(name) if daemon == "ospfd" else
                                      f"hostname {name}\nlog stdout\n")
                    log = (directory / f"{daemon}.log").open("w")
                    self.logs.append(log)
                    process = self.get(name).popen([
                        f"/usr/lib/frr/{daemon}", "-f", str(config),
                        "-i", str(directory / f"{daemon}.pid"),
                        "-z", str(directory / "zserv.api"), "--vty_socket", str(directory),
                        "-A", "127.0.0.1", "-P", "0",
                    ], stdout=log, stderr=subprocess.STDOUT)
                    self.processes.append((name, daemon, process))
                    deadline = time.monotonic() + 10
                    while not (directory / f"{daemon}.vty").exists():
                        self.checkProcesses()
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f"{name}/{daemon} VTY startup timed out")
                        time.sleep(0.1)
            self.waitReady()
            print(json.dumps({"mode": "ospf", "policy": self.policy}), file=sys.stderr)
            return self
        except BaseException:
            self.close()
            raise

    def waitReady(self, timeout=45):
        deadline = time.monotonic() + timeout
        while True:
            self.checkProcesses()
            neighbors = {name: self.vty(name, "show ip ospf neighbor json") for name in ROUTERS}
            if all(fullNeighbors(neighbors[name], name) for name in ROUTERS):
                try:
                    for source in self.hosts:
                        for destination in self.hosts:
                            if source != destination:
                                self.routePath(source, destination)
                    return neighbors
                except RuntimeError:
                    pass
            if time.monotonic() >= deadline:
                raise RuntimeError(f"OSPF Full neighbors/kernel routes timed out: {neighbors}")
            time.sleep(0.25)

    def routePath(self, source="h1", destination="h3"):
        """Walk installed route-get next hops; no local SPF, cached or pinned path."""
        if source not in self.hosts or destination not in self.hosts or source == destination:
            raise ValueError("Two distinct manifest hosts required")
        current, path, readback = source, [source], []
        while current != destination:
            rows = json.loads(self.command(current, [
                "ip", "-j", "route", "get", self.hostAddresses[destination],
            ]))
            if len(rows) != 1 or not rows[0].get("dev"):
                raise RuntimeError("Missing or ambiguous kernel next hop")
            route = rows[0]
            matches = [
                (link, endpoint) for link in self.plan for endpoint in link["endpoints"]
                if endpoint["node"] == current and endpoint["interface"] == route["dev"]
            ]
            if len(matches) != 1:
                raise RuntimeError("Kernel route leaves the manifest graph")
            link, endpoint = matches[0]
            peer = next(row for row in link["endpoints"] if row["node"] != current)
            if route.get("gateway", self.hostAddresses[destination]) != peer["ipv4"]:
                raise RuntimeError("Kernel gateway does not match the connected peer")
            readback.append({"node": current, "route": route})
            current = endpoint["peer"]
            if current in path or len(path) >= len(ROUTERS) + 2:
                raise RuntimeError("Kernel forwarding loop")
            path.append(current)
        routerPath = tuple(path[1:-1])
        return {"nodes": path, "action": PATHS.index(routerPath) if routerPath in PATHS else None,
                "kernel_routes": readback}

    def pathInterfaces(self, action):
        """Both directions of the two inter-router links, excluding host access links."""
        if type(action) is not int or action not in (0, 1):
            raise ValueError("Path action must be 0 or 1")
        pairs = [set(pair) for pair in zip(PATHS[action], PATHS[action][1:])]
        return [
            {"node": endpoint["node"], "interface": endpoint["interface"],
             "port_no": endpoint["port_no"], "capacity_mbps": link["capacity_mbps"]}
            for link in self.plan if {link["a"][0], link["b"][0]} in pairs
            for endpoint in link["endpoints"]
        ]

    def counters(self):
        """Actual kernel counters, timestamps per node; includes protocol overhead."""
        result = []
        for name in ROUTERS:
            started = time.monotonic()
            rows = json.loads(self.command(name, ["ip", "-j", "-s", "link", "show"]))
            finished = time.monotonic()
            for row in rows:
                if row["ifname"] == "lo":
                    continue
                stats = row.get("stats64", row.get("stats"))
                result.append({"node": name, "interface": row["ifname"],
                               "started_monotonic": started, "finished_monotonic": finished,
                               "rx_bytes": stats["rx"]["bytes"] if stats else None,
                               "tx_bytes": stats["tx"]["bytes"] if stats else None,
                               "rx_packets": stats["rx"]["packets"] if stats else None,
                               "tx_packets": stats["tx"]["packets"] if stats else None,
                               "raw": row})
        return result

    def queues(self):
        """Actual leaf netem backlog; unavailable remains null, not zero."""
        result = []
        for link in self.plan:
            for endpoint in link["endpoints"]:
                if endpoint["node"] not in ROUTERS:
                    continue
                started = time.monotonic()
                raw = self.command(endpoint["node"], ["tc", "-j", "-s", "qdisc", "show",
                                                       "dev", endpoint["interface"]])
                result.append({"node": endpoint["node"], "interface": endpoint["interface"],
                               "started_monotonic": started,
                               "finished_monotonic": time.monotonic(),
                               "queue": parseQueue(raw), "raw": json.loads(raw)})
        return result

    def verify(self):
        """Full adjacencies, FRR/kernel RIBs, captured IP89 and all-pairs real ICMP."""
        neighbors = self.waitReady()
        capture = self.get("core").popen([
            "tcpdump", "-nn", "-l", "-i", "core-eth1", "-c", "2", "ip proto 89",
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            packets, captureError = capture.communicate(timeout=8)
        finally:
            stopProcess(capture)
        if capture.returncode != 0 or packets.count(b"OSPFv2") < 2:
            raise RuntimeError(f"No actual IP89 OSPF packets: {captureError!r}")
        probes, paths = [], {}
        for source in self.hosts:
            for destination in self.hosts:
                if source == destination:
                    continue
                paths[f"{source}->{destination}"] = self.routePath(source, destination)
                started = time.monotonic()
                text = self.command(source, ["ping", "-n", "-c", "3", "-i", "0.2", "-W", "1",
                                             self.hostAddresses[destination]])
                probe = parsePing(text, source, destination, time.monotonic() - started, utcNow())
                if probe is None or probe["sent"] != 3 or probe["received"] != 3:
                    raise RuntimeError(f"Host reachability failed: {source}->{destination}: {text}")
                probes.append(probe)
        routes = {name: self.vty(name, "show ip route ospf json") for name in ROUTERS}
        if any(not routes[name] for name in ROUTERS):
            raise RuntimeError("FRR has no OSPF routes")
        return {"mode": "ospf", "topology_id": TOPOLOGY_ID, "policy": self.policy,
                "router_count": len(ROUTERS), "host_count": len(self.hosts),
                "link_count": len(self.plan), "full_directed_adjacencies": 14,
                "hosts": self.hosts, "neighbors": neighbors, "frr_routes": routes,
                "frr_version": self.vty("core", "show version"),
                "ospf_packet_count": packets.count(b"OSPFv2"),
                "ospf_packets": packets.decode(errors="replace"),
                "paths": paths, "probes": probes, "ping_sent": sum(p["sent"] for p in probes),
                "ping_received": sum(p["received"] for p in probes),
                "counters": self.counters(), "queues": self.queues()}

    def close(self):
        """Stop only owned processes/namespaces; no mn -c, pkill or OVS cleanup."""
        for _, _, process in reversed(self.processes):
            stopProcess(process)
        self.processes.clear()
        for log in self.logs:
            log.close()
        self.logs.clear()
        try:
            if self.net is not None:
                self.net.stop()
        finally:
            self.net = None
            if self.directory is not None:
                shutil.rmtree(self.directory)
                self.directory = None
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None


OSPFEnv = OSPFNetwork


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", required=True)
    parser.parse_args()
    network = OSPFNetwork()
    try:
        network.start()
        print(json.dumps(network.verify(), allow_nan=False))
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"mode": "ospf", "ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    finally:
        network.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
