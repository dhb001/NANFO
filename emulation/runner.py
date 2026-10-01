"""Container-only Mininet lifecycle and measured ADR-009 snapshot producer."""

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from pathlib import Path

from emulation.measurements import atomicJson, parsePing, parseQueue, readJson, utcNow
from emulation.topology import HOSTS, LINKS, SWITCHES, TOPOLOGY_ID, expectedLinks

STATE = Path("/run/nanfo")
SOCKET = str(STATE / "control.sock")
# ADR-028 C23 successor capability profile (linux/capability.h bit numbers).
CAPABILITIES = {"CAP_NET_BIND_SERVICE": 10, "CAP_NET_ADMIN": 12, "CAP_NET_RAW": 13, "CAP_SYS_ADMIN": 21}
SUCCESSOR_CAPABILITIES = ("CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_SYS_ADMIN")
# FRR's ospfd narrows itself to a compiled capability set that includes NET_BIND_SERVICE.
FRR_CAPABILITIES = (*SUCCESSOR_CAPABILITIES, "CAP_NET_BIND_SERVICE")


def runCommand(args, timeout=10):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout).stdout


def stopProcess(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def capabilityStatus(text):
    """Parse /proc/self/status capability sets and the no-new-privileges flag."""
    fields = dict(line.split(":", 1) for line in text.splitlines() if ":" in line)
    try:
        return {
            "bounding": int(fields["CapBnd"].strip(), 16),
            "effective": int(fields["CapEff"].strip(), 16),
            "no_new_privs": fields.get("NoNewPrivs", "").strip() == "1",
        }
    except (KeyError, ValueError) as error:
        raise RuntimeError("Capability status unavailable") from error


def requireSuccessorProfile(frr=False, status=None):
    """Refuse privileged or over-capable containers; the successor never runs privileged."""
    if os.environ.get("NANFO_LAB_FROZEN", "") not in ("", "0"):
        raise RuntimeError("NANFO_LAB_FROZEN applies only to the recorded frozen image")
    if status is None:
        status = Path("/proc/self/status").read_text()
    profile = capabilityStatus(status)
    names = FRR_CAPABILITIES if frr else SUCCESSOR_CAPABILITIES
    allowed = sum(1 << CAPABILITIES[name] for name in names)
    if profile["bounding"] & ~allowed:
        raise RuntimeError(
            "C23: successor lab refuses privileged/extra capabilities; use cap_drop ALL and "
            + ", ".join(name[4:] for name in names)
        )
    if profile["effective"] & allowed != allowed:
        raise RuntimeError("C23: successor lab requires " + ", ".join(name[4:] for name in names))
    if not profile["no_new_privs"]:
        raise RuntimeError("C23: successor lab requires security_opt no-new-privileges:true")
    return profile


def requireContainer(frr=False):
    if os.environ.get("NANFO_ISOLATED_LAB") != "1" or not Path("/.dockerenv").exists():
        raise RuntimeError("Runner is container-only; use emulation/control.py")
    if os.geteuid() != 0:
        raise RuntimeError("The disposable container requires root namespace privileges")
    requireSuccessorProfile(frr)
    # Refuse accidental Docker --network host/bridge overrides before creating links.
    interfaces = {p.name for p in Path("/sys/class/net").iterdir()}
    if interfaces != {"lo"}:
        raise RuntimeError("Lab requires network_mode: none and only loopback at startup")


class Lab:
    def __init__(self, output):
        self.output = output
        self.net = None
        self.controller = None
        self.processes = []
        self.runId = str(uuid.uuid4())
        self.sequence = 0
        self.stopping = False
        self.probes = []
        self.lastProbe = 0
        self.outputLock = None
        self.lastQueueRaw = {}
        self.mailbox = None

    def start(self):
        from mininet.link import TCLink
        from mininet.net import Mininet
        from mininet.node import OVSSwitch, RemoteController

        # Mininet.__init__ calls Mininet.init directly, bypassing subclass overrides.
        # Skip its global sysctl writes; root was checked by requireContainer and
        # Compose owns our process limits. This pinned upstream flag is regression-tested.
        Mininet.inited = True

        STATE.mkdir(exist_ok=True)
        self.output.mkdir(exist_ok=True)
        self.outputLock = os.open(
            str(self.output / ".producer.lock"), os.O_CREAT | os.O_RDWR, 0o600
        )
        try:
            fcntl.flock(self.outputLock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another lab already owns this output directory") from error
        runCommand(
            [
                "/usr/share/openvswitch/scripts/ovs-ctl",
                "--system-id=random",
                "--no-ovs-vswitchd",
                "start",
            ]
        )
        # Kernel module loading is intentionally not attempted. The host kernel
        # must already support OVS; userspace dummy networking would fake the lab.
        runCommand(["ovs-vswitchd", "--pidfile", "--detach"])
        # os-ken 4 has no manager CLI; this fixed launcher is the old ryu-manager argv.
        self.controller = subprocess.Popen(
            [sys.executable, "-m", "emulation.controller_main"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 30
        while True:
            self.checkController()
            try:
                with socket.create_connection(("127.0.0.1", 6653), timeout=0.5):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Controller listener readiness exceeded 30 seconds"
                    ) from None
                time.sleep(0.2)
        self.net = Mininet(
            controller=None,
            switch=OVSSwitch,
            link=TCLink,
            build=False,
            autoSetMacs=False,
            autoStaticArp=False,
        )
        self.net.addController("controller", controller=RemoteController, ip="127.0.0.1", port=6653)
        for switch in SWITCHES:
            self.net.addSwitch(
                switch["name"], dpid=switch["dpid"], protocols="OpenFlow13", failMode="secure"
            )
        for host in HOSTS:
            self.net.addHost(host["name"], ip=host["ipv4"] + "/24", mac=host["mac"])
        for link in LINKS:
            a, ap = link["a"]
            b, bp = link["b"]
            self.net.addLink(
                a,
                b,
                port1=ap,
                port2=bp,
                bw=link["capacity_mbps"],
                delay=f"{link['delay_ms']}ms",
                max_queue_size=link["max_queue_size"],
                use_htb=True,
            )
        self.net.build()
        self.net.start()
        for host in HOSTS:
            node = self.net[host["name"]]
            for peer in HOSTS:
                if peer != host:
                    process = node.popen(
                        [
                            "ip",
                            "neigh",
                            "replace",
                            peer["ipv4"],
                            "lladdr",
                            peer["mac"],
                            "nud",
                            "permanent",
                            "dev",
                            host["name"] + "-eth0",
                        ]
                    )
                    if process.wait(timeout=3) != 0:
                        raise RuntimeError("Static neighbor setup failed")
        deadline = time.monotonic() + 45
        while not self.ready(self.controllerState(), hosts=False):
            self.checkController()
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "OpenFlow stats / 14 directed LLDP links not ready within 45 seconds"
                )
            time.sleep(0.3)
        self.probe()
        deadline = time.monotonic() + 10
        while not self.ready(self.controllerState()):
            if time.monotonic() >= deadline:
                raise RuntimeError("Four real host PacketIn attachments not discovered")
            time.sleep(0.2)
        self.snapshot()
        if os.environ.get("EMULATION_CONTROL_ENABLED", "false").lower() == "true":
            from emulation.actions import Actions
            from emulation.mailbox import Mailbox

            self.mailbox = Mailbox(
                Actions(self), self.runId, os.environ.get("EMULATION_BINDING_DIGEST", "")
            )
            fcntl.flock(self.mailbox.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                self.mailbox.recover(self.mailbox.load())
            finally:
                fcntl.flock(self.mailbox.lock, fcntl.LOCK_UN)

    def checkController(self):
        if self.controller is not None and self.controller.poll() is not None:
            raise RuntimeError(
                "Controller exited; diagnostic log is container-internal /run/nanfo/controller.log"
            )
        if self.stopping:
            raise RuntimeError("Lab stopping")

    def controllerState(self):
        try:
            state = readJson(STATE / "controller.json")
            from datetime import datetime, timezone

            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(state["observed_at"].replace("Z", "+00:00"))
            ).total_seconds()
            if not 0 <= age <= 6:
                raise ValueError("Controller state stale")
            return state
        except (OSError, ValueError, KeyError):
            return {"switches": [], "links": [], "hosts": []}

    @staticmethod
    def ready(state, hosts=True):
        observed = {
            (link["src_dpid"], link["src_port"], link["dst_dpid"], link["dst_port"])
            for link in state["links"]
        }
        return (
            len(state["switches"]) == 5
            and observed == expectedLinks()
            and (not hosts or len(state["hosts"]) == 4)
        )

    def probe(self):
        pending = []
        for index, source in enumerate(HOSTS):
            target = HOSTS[(index + 1) % len(HOSTS)]
            process = self.net[source["name"]].popen(
                ["ping", "-n", "-c", "2", "-i", "0.2", "-W", "1", target["ipv4"]],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env={**os.environ, "LC_ALL": "C"},
            )
            self.processes.append(process)
            pending.append((source, target, process, time.monotonic()))
        probes = []
        for source, target, process, started in pending:
            try:
                text = process.communicate(timeout=4)[0].decode("utf-8", errors="replace")
                measurement = parsePing(
                    text, source["name"], target["name"], time.monotonic() - started, utcNow()
                )
                if measurement:
                    probes.append(measurement)
            except subprocess.TimeoutExpired:
                stopProcess(process)
            self.processes.remove(process)
        self.probes = probes
        self.lastProbe = time.monotonic()
        return probes

    def queues(self):
        measurements = []
        self.lastQueueRaw = {}
        for switch in SWITCHES:
            node = self.net[switch["name"]]
            for port, interface in sorted(node.intfs.items()):
                if port <= 0:
                    continue
                try:
                    text = runCommand(
                        ["tc", "-s", "-j", "qdisc", "show", "dev", interface.name], timeout=2
                    )
                    queue = parseQueue(text)
                    if queue is not None:
                        self.lastQueueRaw[(switch["dpid"], port)] = json.loads(text)
                        measurements.append(
                            {
                                "dpid": switch["dpid"],
                                "port_no": port,
                                "observed_at": utcNow(),
                                **queue,
                            }
                        )
                except (subprocess.SubprocessError, OSError):
                    continue
        return measurements

    def snapshot(self, queues=None):
        self.checkController()
        state = self.controllerState()
        value = {
            "version": 1,
            "topology_id": TOPOLOGY_ID,
            "run_id": self.runId,
            "sequence": self.sequence,
            "observed_at": utcNow(),
            "switches": state["switches"],
            "links": state["links"],
            "hosts": state["hosts"],
            "queues": self.queues() if queues is None else queues,
            "probes": self.probes if time.monotonic() - self.lastProbe <= 10 else [],
        }
        atomicJson(self.output / "snapshot.json", value)
        self.sequence += 1
        return value

    def traffic(self):
        """Independent iperf3 processes, with actual OVS CLI and leaf-qdisc checks."""
        before = self.snapshot()
        atomicJson(self.output / "before.json", before)
        counterBefore = runCommand(["ovs-ofctl", "-O", "OpenFlow13", "dump-ports", "access1", "1"])
        server = self.net["h3"].popen(
            ["iperf3", "-s", "-1", "-J"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        self.processes.append(server)
        client = None
        peak = None
        peakRaw = None
        samples = 0
        try:
            time.sleep(0.3)
            client = self.net["h1"].popen(
                ["iperf3", "-c", "10.77.0.3", "-t", "8", "-J"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.processes.append(client)
            deadline = time.monotonic() + 15
            lastSnapshot = 0
            while client.poll() is None:
                self.checkController()
                if time.monotonic() > deadline:
                    raise RuntimeError("iperf3 exceeded bounded duration")
                queues = self.queues()
                samples += len(queues)
                for queue in queues:
                    if peak is None or queue["backlog_bytes"] > peak["backlog_bytes"]:
                        peak = queue
                        peakRaw = self.lastQueueRaw[(queue["dpid"], queue["port_no"])]
                if time.monotonic() - lastSnapshot >= 1:
                    self.snapshot(queues)
                    lastSnapshot = time.monotonic()
                time.sleep(0.1)
            clientText, _ = client.communicate(timeout=2)
            serverText, _ = server.communicate(timeout=3)
            if client.returncode or server.returncode:
                raise RuntimeError("iperf3 client/server failed")
            clientResult, serverResult = json.loads(clientText), json.loads(serverText)
            # Strip hostname/kernel/version and process metadata from shared artifacts.
            fields = ("bytes", "bits_per_second", "seconds", "retransmits")
            summaries = {}
            for name, result in (("client", clientResult), ("server", serverResult)):
                summaries[name] = {
                    kind: {k: v for k, v in result["end"][kind].items() if k in fields}
                    for kind in ("sum_sent", "sum_received")
                }
            self.probe()
            time.sleep(2)
            after = self.snapshot()
            atomicJson(self.output / "after.json", after)
            counterAfter = runCommand(
                ["ovs-ofctl", "-O", "OpenFlow13", "dump-ports", "access1", "1"]
            )

            def portBytes(snapshot):
                return next(
                    p["tx_bytes"]
                    for s in snapshot["switches"]
                    if s["name"] == "access1"
                    for p in s["ports"]
                    if p["port_no"] == 1
                )

            delta = portBytes(after) - portBytes(before)
            import re

            cliBefore = int(re.search(r"tx pkts=\d+, bytes=(\d+)", counterBefore).group(1))
            cliAfter = int(re.search(r"tx pkts=\d+, bytes=(\d+)", counterAfter).group(1))
            result = {
                "run_id": self.runId,
                "observed_at": utcNow(),
                "iperf3": summaries,
                "openflow_tx_bytes_delta": delta,
                "ovs_cli_tx_bytes_delta": cliAfter - cliBefore,
                "queue_samples": samples,
                "peak_queue": peak,
                "probes": self.probes,
            }
            delivered = summaries["server"]["sum_received"]["bytes"]
            result["passed"] = (
                delivered > 1000000
                and delta >= delivered
                and cliAfter - cliBefore >= delivered
                and abs(delta - (cliAfter - cliBefore)) < max(65536, delta * 0.05)
                and peak is not None
                and peak["backlog_bytes"] > 0
                and len(self.probes) == 4
                and all(p["sent"] == p["received"] for p in self.probes)
            )
            atomicJson(
                self.output / "queue-peak.json",
                {
                    "run_id": self.runId,
                    "measurement": peak,
                    "tc_qdiscs": peakRaw,
                    "selection": "single leaf netem, excluding parent HTB backlog",
                },
            )
            atomicJson(self.output / "traffic.json", result)
            return result
        finally:
            for process in (client, server):
                stopProcess(process)
                if process in self.processes:
                    self.processes.remove(process)

    def verify(self):
        capture = subprocess.Popen(
            [
                "tcpdump",
                "-U",
                "-n",
                "-i",
                "access1-eth1",
                "-c",
                "80",
                "-w",
                str(self.output / "probes.pcap"),
                "icmp or ether proto 0x88cc",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.processes.append(capture)
        try:
            time.sleep(0.3)
            loss = self.net.pingAll(timeout="1")
            probes = self.probe()
            time.sleep(2)
            snapshot = self.snapshot()
            traffic = self.traffic()
            if capture.poll() is None:
                capture.send_signal(signal.SIGINT)
                capture.wait(timeout=3)
            pcapBytes = (self.output / "probes.pcap").stat().st_size
            result = {
                "run_id": self.runId,
                "observed_at": utcNow(),
                "ping_all_loss_percent": loss,
                "switches": len(snapshot["switches"]),
                "directed_lldp_links": len(snapshot["links"]),
                "discovered_hosts": len(snapshot["hosts"]),
                "queues": len(snapshot["queues"]),
                "probe_count": len(probes),
                "pcap_bytes": pcapBytes,
                "passed": loss == 0
                and self.ready(snapshot)
                and len(probes) == 4
                and all(p["sent"] == p["received"] for p in probes)
                and pcapBytes > 24
                and traffic["passed"],
            }
            atomicJson(self.output / "verification.json", result)
            return result
        finally:
            stopProcess(capture)
            self.processes.remove(capture)

    def close(self):
        if self.mailbox is not None:
            self.mailbox.close()
        for process in self.processes:
            stopProcess(process)
        if self.net is not None:
            self.net.stop()  # Only this instance's switches, links and host namespaces.
        stopProcess(self.controller)
        for daemon in ("ovs-vswitchd", "ovsdb-server"):
            with suppress(subprocess.SubprocessError, OSError):
                runCommand(["ovs-appctl", "-t", daemon, "exit"], timeout=3)
        Path(SOCKET).unlink(missing_ok=True)
        if self.outputLock is not None:
            os.close(self.outputLock)


def dispatch(lab, command):
    if command == "status":
        return {"passed": lab.ready(lab.controllerState()), "run_id": lab.runId, "sequence": lab.sequence}
    if command == "smoke":
        return lab.verify()
    if command == "traffic":
        return lab.traffic()
    if command == "paths":
        from emulation.probe_paths import CaptureInterrupted, capturePaths

        try:
            return capturePaths(lab)
        except CaptureInterrupted:
            return {
                "passed": False,
                "status": "partial",
                "error": "Probe capture interrupted by controls; no new path artifact",
            }
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
            return {"passed": False, "error": "Probe capture unavailable"}
    return {"passed": False, "error": "Unknown command"}


def answer(lab, connection):
    """One control request -> one bounded envelope; a failed request never closes the lab.

    Lab-fatal conditions (controller exit, stop) still end the service loop through the
    polling path and lab.stopping; a request error is reported only to its own caller.
    """
    try:
        connection.settimeout(2)
        command = connection.recv(32).decode("ascii").strip()
        return dispatch(lab, command)
    except Exception as error:
        detail = " ".join(str(error).split())[:160]
        print(f"Control request failed: {type(error).__name__}: {detail}", file=sys.stderr, flush=True)
        return {"passed": False, "error": f"{type(error).__name__}: {detail}"}


def request(command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3 if command == "status" else 90)
        client.connect(SOCKET)
        client.sendall(command.encode("ascii") + b"\n")
        response = bytearray()
        while len(response) <= 65536:
            part = client.recv(4096)
            if not part:
                break
            response.extend(part)
        result = json.loads(response)
        print(json.dumps(result, indent=2))
        return 0 if result.get("passed", False) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/output"))
    parser.add_argument(
        "--verify", action="store_true", help="One-shot live gate; exits and cleans its lab"
    )
    parser.add_argument("--request", choices=("status", "smoke", "traffic", "paths"))
    parser.add_argument("--experiment", action="store_true", help="Exclusive opt-in ADR-011 server")
    parser.add_argument("--mode", choices=("sdn", "matched", "ospf"), default="sdn")
    parser.add_argument(
        "--verify-actions", action="store_true", help="One-shot local real control/fault gate"
    )
    args = parser.parse_args()
    if args.request:
        return request(args.request)
    if args.experiment and (
        args.verify
        or args.verify_actions
        or os.environ.get("EMULATION_CONTROL_ENABLED", "false").lower() != "false"
    ):
        parser.error("Experiment mode cannot coexist with verification or manual mailbox control")
    if args.experiment and (
        Path("/results/.journal.json").exists() or Path("/results/.journal.json").is_symlink()
    ):
        parser.error("Manual journal exists; never remove a live journal to enable experiments")
    if not args.experiment and args.mode != "sdn":
        parser.error("OSPF requires explicit --experiment")
    requireContainer(frr=args.experiment and args.mode in ("matched", "ospf"))
    if args.output.resolve() != Path("/output"):
        parser.error("Container output must be the dedicated /output mount")
    if args.experiment and args.mode in ("matched", "ospf"):
        from emulation.experiment import OspfLab

        lab = OspfLab(args.output)
    else:
        lab = Lab(args.output)

    def stop(signum, frame):
        lab.stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        lab.start()
        if args.experiment:
            from emulation.experiment import Experiment

            Experiment(lab, args.mode).serve()
            return 0
        if args.verify_actions:
            from emulation.verify_actions import verifyActions

            result = verifyActions(lab)
            print(json.dumps(result))
            return 0 if result["passed"] else 1
        if args.verify:
            result = lab.verify()
            print(json.dumps(result))
            return 0 if result["passed"] else 1
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(SOCKET)
            os.chmod(SOCKET, 0o600)
            server.listen(2)
            server.settimeout(1)
            while not lab.stopping:
                if lab.mailbox is not None:
                    lab.mailbox.poll()
                if time.monotonic() - lab.lastProbe >= 5:
                    lab.probe()
                lab.snapshot()
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                with connection:
                    result = answer(lab, connection)
                    with suppress(OSError):
                        connection.sendall(json.dumps(result).encode("ascii"))
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Lab failed: {error}", file=sys.stderr)
        return 1
    finally:
        lab.close()


if __name__ == "__main__":
    sys.exit(main())
