"""ADR024 actual native driver/manual-authority campaign in one disconnected container.

--launch owns Docker image/container/host lease; --inside owns namespace fixture;
--child resumes only persisted prepared work. Never creates calibration or trains.
"""

import argparse
import asyncio
import fcntl
import hashlib
import heapq
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from emulation.autonomous_frr import LinuxFRRDriver, RUNTIME  # noqa: E402
from emulation.autonomous_namespace import AttachedFRRNetwork, process_identity  # noqa: E402
from emulation.native_qualification_clock import canonical_observation_clock  # noqa: E402
from emulation.ospf import OSPFNetwork, ROUTERS, linkPlan  # noqa: E402


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    data = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


class Evidence:
    def __init__(self, output, name):
        self.output = Path(output)
        self.stream = (self.output / name).open("x")
        self.lock = threading.Lock()

    def event(self, kind, **values):
        with self.lock:
            self.stream.write(json.dumps(dict(kind=kind, wall_ns=time.time_ns(), monotonic_ns=time.monotonic_ns(),
                pid=os.getpid(), **values), sort_keys=True, allow_nan=False) + "\n")
            self.stream.flush()
            os.fsync(self.stream.fileno())

    def command(self, argv, *, node=None, pass_fds=(), timeout=5):
        start = time.monotonic_ns()
        self.event("command_attempt", argv=argv, node=node, timeout_seconds=timeout)
        try:
            result = subprocess.run(argv, capture_output=True, timeout=timeout, pass_fds=pass_fds)
            self.event("command_result", argv=argv, node=node, returncode=result.returncode,
                       stdout=result.stdout.decode(errors="replace"), stderr=result.stderr.decode(errors="replace"),
                       elapsed_ns=time.monotonic_ns() - start)
            if result.returncode:
                raise RuntimeError("native_command_failed:" + repr(argv))
            return result.stdout.decode()
        except subprocess.TimeoutExpired as exc:
            self.event("command_timeout", argv=argv, node=node, stdout=str(exc.stdout), stderr=str(exc.stderr))
            raise


def native_namespace(binding, output, evidence):
    network = AttachedFRRNetwork(binding, lock_directory=output)
    # Transport keeps its actual namespace/argv/final-callback path. Replace only
    # subprocess.run with a recording wrapper, preserving arguments/results.
    return network


def queue_snapshot(network, evidence, label, *, sealed=True):
    result = []
    for link in network.plan:
        for endpoint in link["endpoints"]:
            node, interface = endpoint["node"], endpoint["interface"]
            raw = json.loads(network.command(node, ["tc", "-j", "-s", "qdisc", "show", "dev", interface]))
            gates = json.loads(network.command(node, ["tc", "-j", "-s", "filter", "show", "dev", interface, "egress"]))
            traffic = [r for r in raw if r.get("kind") != "clsact"]
            if sealed:
                if not traffic or not gates or not any(r.get("kind") == "matchall" for r in gates):
                    raise ValueError("sealed_gate_or_qdisc_missing")
                if any(r.get("kind") not in {"htb", "netem", "clsact"} for r in raw):
                    raise ValueError("unexpected_qdisc_in_sealed_epoch")
                concrete = [r for r in gates if r.get("options", {}).get("actions")]
                if (len(concrete) != 1 or concrete[0].get("protocol") != "all"
                        or concrete[0].get("pref") != 1
                        or any(a.get("kind") != "gact" or a.get("control_action", {}).get("type") != "drop"
                               for a in concrete[0]["options"]["actions"])):
                    raise ValueError("seal_not_unconditional_drop")
                if any(r.get("backlog") != 0 or r.get("qlen") != 0 or r.get("bytes") != 0 or r.get("packets") != 0 for r in traffic):
                    raise ValueError("sealed_nonzero_native_queue_or_departure")
            result.append(dict(node=node, interface=interface, qdiscs=raw, gates=gates))
    capture = dict(label=label, reads=result, finished_wall_ns=time.time_ns(), finished_monotonic_ns=time.monotonic_ns())
    evidence.event("queue_snapshot", capture=capture, canonical_clock=canonical_observation_clock(capture,
        finished_wall_ns=capture["finished_wall_ns"], finished_monotonic_ns=capture["finished_monotonic_ns"]))
    return digest(capture)


class StaticFixture:
    def __init__(self, output, evidence, run):
        self.output, self.evidence, self.run = output, evidence, run
        self.net = None
        self.plan = linkPlan()

    def command(self, node, argv):
        return self.evidence.command(["nsenter", "-t", str(self.net[node].pid), "-n", "--", *argv], node=node)

    def start(self):
        if not Path("/.dockerenv").exists() or os.environ.get("NANFO_ISOLATED_LAB") != "1":
            raise ValueError("isolated_container_required")
        if {p.name for p in Path("/sys/class/net").iterdir()} != {"lo"}:
            raise ValueError("disconnected_container_required")
        from mininet.net import Mininet
        from mininet.node import Host
        Mininet.inited = True
        self.net = Mininet(controller=None, build=False, host=Host)
        for name in (*ROUTERS, "h1", "h2", "h3", "h4"):
            self.net.addHost(name, ip=None, inNamespace=True)
            self.command(name, ["sysctl", "-qw", "net.ipv6.conf.all.disable_ipv6=1", "net.ipv6.conf.default.disable_ipv6=1",
                "net.ipv4.conf.all.rp_filter=0", "net.ipv4.conf.default.rp_filter=0",
                "net.ipv4.conf.all.send_redirects=0", "net.ipv4.conf.default.send_redirects=0",
                "net.ipv4.ip_forward=" + ("1" if name in ROUTERS else "0")])
            self.command(name, ["ip", "link", "set", "lo", "up"])
        for i, link in enumerate(self.plan):
            a, b = link["endpoints"]
            left, right = "nv" + str(i) + "a", "nv" + str(i) + "b"
            self.evidence.command(["ip", "link", "add", left, "type", "veth", "peer", "name", right])
            for temp, endpoint in ((left, a), (right, b)):
                self.evidence.command(["ip", "link", "set", temp, "netns", str(self.net[endpoint["node"]].pid)])
                node, interface = endpoint["node"], endpoint["interface"]
                self.command(node, ["ip", "link", "set", temp, "name", interface])
                # Fresh veth is still DOWN: no packet ever admitted before this seal.
                self.command(node, ["tc", "qdisc", "add", "dev", interface, "clsact"])
                self.command(node, ["tc", "filter", "add", "dev", interface, "egress", "protocol", "all", "pref", "1",
                                    "matchall", "action", "drop"])
                self.command(node, ["tc", "qdisc", "add", "dev", interface, "root", "handle", "5:", "htb", "default", "1"])
                self.command(node, ["tc", "class", "add", "dev", interface, "parent", "5:", "classid", "5:1", "htb",
                    "rate", str(link["capacity_mbps"]) + "mbit", "ceil", str(link["capacity_mbps"]) + "mbit"])
                self.command(node, ["tc", "qdisc", "add", "dev", interface, "parent", "5:1", "handle", "10:",
                    "netem", "delay", str(link["delay_ms"]) + "ms", "limit", "100"])
                self.command(node, ["ethtool", "-K", interface, "gro", "off", "gso", "off", "tso", "off"])
                self.command(node, ["ethtool", "-k", interface])
                self.command(node, ["ip", "addr", "add", endpoint["cidr"], "dev", interface])
                self.command(node, ["tc", "-j", "-s", "filter", "show", "dev", interface, "ingress"])
        identities = {}
        for name in (*ROUTERS, "h1", "h2", "h3", "h4"):
            pid = self.net[name].pid
            ticks, inode = process_identity(pid)
            identities[name] = dict(pid=pid, start_ticks=ticks, netns_inode=inode)
        binding = dict(resource_id=self.run, run_id=self.run, namespaces=identities)
        write(self.output / "namespaces.json", binding)
        for link in self.plan:
            for endpoint in link["endpoints"]:
                self.command(endpoint["node"], ["ip", "-j", "-d", "link", "show", "dev", endpoint["interface"]])
                self.command(endpoint["node"], ["tc", "-j", "-s", "filter", "show", "dev", endpoint["interface"], "egress"])
        for link in self.plan:
            for endpoint in link["endpoints"]:
                self.command(endpoint["node"], ["ip", "link", "set", endpoint["interface"], "up"])
        # Static nominal-cost FIB, explicitly separate from reserved driver policy.
        network = OSPFNetwork()
        for source in (*ROUTERS, *network.hostAddresses):
            for destination, address in network.hostAddresses.items():
                if source == destination:
                    continue
                path = shortest(self.plan, source, destination)
                peer = path[1]
                link = next(item for item in self.plan if {item["a"][0], item["b"][0]} == {source, peer})
                endpoint = next(e for e in link["endpoints"] if e["node"] == source)
                gateway = next(e["ipv4"] for e in link["endpoints"] if e["node"] == peer)
                self.command(source, ["ip", "route", "add", address + "/32", "via", gateway, "dev", endpoint["interface"], "onlink", "proto", "static"])
        return binding

    def close(self):
        if self.net is not None:
            identities = {name: dict(pid=self.net[name].pid, start_ticks=process_identity(self.net[name].pid)[0])
                          for name in (*ROUTERS, "h1", "h2", "h3", "h4")}
            self.net.stop()  # Exact object-owned hosts only; no mn -c/global cleanup.
            self.net = None
            self.evidence.event("namespace_cleanup", processes=identities,
                still_present=[value["pid"] for value in identities.values() if Path("/proc/" + str(value["pid"])).exists()])


def shortest(plan, source, destination):
    pending = [(0, [source])]
    while pending:
        cost, path = heapq.heappop(pending)
        if path[-1] == destination:
            return path
        for link in plan:
            a, b = link["a"][0], link["b"][0]
            if path[-1] not in (a, b):
                continue
            peer = b if path[-1] == a else a
            if peer not in path:
                heapq.heappush(pending, (cost + link["cost"], path + [peer]))
    raise ValueError("disconnected_fixture")


def binding_object(value):
    return SimpleNamespace(resource_id=value["resource_id"], run_id=value["run_id"],
        namespaces={k: SimpleNamespace(**v) for k, v in value["namespaces"].items()})


class Authority:
    def __init__(self, network, evidence, manifest, prepared, *, recovery=False, stop=None, crash=None, lost=False, sealed=True):
        self.network, self.evidence, self.manifest, self.prepared = network, evidence, manifest, prepared
        self.recovery, self.stop, self.crash, self.lost, self.sealed = recovery, stop, crash, lost, sealed
        self.count = 0
        self.context = None
        self.original = network.mutate
        self.original_command = network.command
        self.allowed = [(r["node"], LinuxFRRDriver.command(r, k, "del" if recovery else "add"))
            for r in (list(reversed(prepared["resources"])) if recovery else prepared["resources"])
            for k in (("rules", "routes") if recovery else ("routes", "rules"))]
        self.cursor = 0
        self.owner_pid = os.getpid()
        self.owner_start = process_identity(self.owner_pid)[0]
        network.mutate = self.mutate

    async def checkpoint(self):
        if (self.context is None or not self.network.ownership(self.network.binding.resource_id, self.network.binding.run_id)
                or os.getpid() != self.owner_pid or process_identity(self.owner_pid)[0] != self.owner_start
                or digest(json.loads(Path(self.manifest["protocol_path"]).read_text())) != self.manifest["protocol_digest"]):
            raise ValueError("manual_scope_identity_denied")
        if not self.recovery and (self.stop is not None and self.count >= self.stop):
            self.evidence.event("STOP_denied", acknowledged=self.count, context=self.context)
            raise ValueError("manual_STOP")
        if not self.recovery and time.monotonic_ns() >= self.manifest["expires_monotonic_ns"]:
            self.evidence.event("expiry_denied", context=self.context)
            raise ValueError("manual_expired")
        self.evidence.event("recovery_authority" if self.recovery else "apply_authority", sequence=self.count, context=self.context)

    def mutate(self, node, args, checkpoint, timeout=5):
        value = (node, args)
        if self.recovery:
            while self.cursor < len(self.allowed) and self.allowed[self.cursor] != value:
                self.cursor += 1
        if self.cursor >= len(self.allowed) or self.allowed[self.cursor] != value:
            raise ValueError("manual_command_graph_mismatch")
        self.context = dict(node=node, argv=args, sequence=self.cursor)
        self.evidence.event("may_have_applied", context=self.context)
        result = self.original(node, args, checkpoint, timeout)
        self.count += 1
        self.cursor += 1
        if self.lost and self.crash == self.count:
            if self.sealed:
                queue_snapshot(self.network, self.evidence, "lost-receipt-kernel-prefix")
            os._exit(74)  # Native return exists; operation acknowledgement deliberately absent.
        self.evidence.event("mutation_ack", context=self.context, acknowledged=self.count)
        if self.sealed:
            queue_snapshot(self.network, self.evidence, "after-mutation-" + str(self.count))
        if self.crash == self.count:
            os._exit(73)
        return result

    def close(self):
        self.network.mutate = self.original


def record_subprocesses(evidence):
    import emulation.autonomous_namespace as module
    original = module.subprocess.run
    def run(argv, **kwargs):
        start = time.monotonic_ns()
        # Mutation attempt was fsynced by Authority before final checkpoint. Do not
        # insert logging I/O between that checkpoint and actual subprocess launch.
        if not ("add" in argv or "del" in argv):
            evidence.event("native_attempt", argv=argv, timeout_seconds=kwargs.get("timeout"))
        try:
            result = original(argv, **kwargs)
        except BaseException as exc:
            evidence.event("native_exception", argv=argv, error=type(exc).__name__)
            raise
        evidence.event("native_result", argv=argv, returncode=result.returncode,
            stdout=result.stdout.decode(errors="replace"), stderr=result.stderr.decode(errors="replace"), elapsed_ns=time.monotonic_ns() - start)
        return result
    module.subprocess.run = run
    return original


async def phase(output, case_path, operation, *, stop=None, crash=None, lost=False, sealed=True, expired=False):
    output, case_path = Path(output), Path(case_path)
    manifest = json.loads((output / "manual.json").read_text())
    if expired:
        manifest["expires_monotonic_ns"] = time.monotonic_ns() - 1
    prepared = json.loads((case_path / "prepared.json").read_text())
    if hashlib.sha256((case_path / "prepared.json").read_bytes()).hexdigest() != (case_path / "prepared.sha256").read_text():
        raise ValueError("prepared_digest_changed")
    evidence = Evidence(case_path, operation + "-" + uuid.uuid4().hex + ".jsonl")
    network = native_namespace(binding_object(json.loads((output / "namespaces.json").read_text())), output, evidence)
    original_run = record_subprocesses(evidence)
    authority = Authority(network, evidence, manifest, prepared, recovery=operation == "recover", stop=stop, crash=crash, lost=lost, sealed=sealed)
    driver = LinuxFRRDriver(network, resource_id=network.binding.resource_id, run_id=network.binding.run_id,
        binding_sha256=manifest["protocol_digest"], ownership_check=network.ownership, dispatch_guard=authority.checkpoint)
    try:
        if operation == "apply":
            try:
                await driver.apply(prepared, authority.checkpoint)
            except ValueError as exc:
                if not ((stop is not None and str(exc) == "manual_STOP" and authority.count == stop)
                        or (expired and str(exc) == "manual_expired" and authority.count == 0)):
                    raise
            if stop is not None and authority.count != stop:
                raise ValueError("STOP_prefix_mismatch")
            if stop == 12:
                evidence.event("STOP_after_full_apply", acknowledged=12)
            inventory = driver.read_owned(prepared, complete=not expired and stop in (None, 12))
            expected = [(r["node"], r["table"], kind) for r in prepared["resources"] for kind in ("routes", "rules")][:authority.count]
            for key, values in inventory.items():
                node, table = key.split(":")
                for kind, rows in values.items():
                    if len(rows) != int((node, int(table), kind) in expected):
                        raise ValueError("actual_prefix_inventory_mismatch")
            paths = driver.paths()
            result = dict(status="passed", acknowledged=authority.count, inventory=inventory, paths=paths)
        else:
            result = await driver.compensate(prepared, authority.checkpoint)
            result.update(status="passed", deletes=authority.count)
        write(case_path / (operation + "-result-" + uuid.uuid4().hex + ".json"), result)
        return result
    finally:
        authority.close()
        network.close()
        subprocess.run = original_run
        evidence.stream.close()


async def campaign(output):
    output = Path(output)
    protocol = json.loads((output / "protocol.json").read_text())
    identity = Evidence(output, "identity.jsonl")
    identity.event("runtime_identity", python=sys.version, kernel=platform.uname()._asdict(),
        boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        namespace_links={kind: os.readlink("/proc/self/ns/" + kind) for kind in ("pid", "net", "time", "mnt")},
        proc_status=Path("/proc/self/status").read_text(),
        packages=identity.command(["dpkg-query", "-W", "mininet", "iproute2", "frr", "ethtool", "iputils-ping", "util-linux"]),
        python_packages=identity.command([sys.executable, "-m", "pip", "freeze"]))
    identity.stream.close()
    result = dict(version="nanfo.native-driver-acceptance/v1", claim="native-driver-verified", environment="isolated-emulation",
        status="pending", authority_kind="scoped-manual-driver-campaign", autonomy_qualified=False, safety_calibrated=False,
        physical_rf_qualified=False, trusted_installation=None, safety_certificate=None,
        sealed_queue_theorem="conditional-on-reviewed-native-enforcement", hard_transition_deadline_proved=False,
        receiver_journal_acceptance=False, cases=[], failures=[], unresolved_resources=[])
    active_case = None
    for action in (0, 1):
        fixture_dir = output / ("action" + str(action))
        fixture_dir.mkdir(mode=0o700)
        evidence = Evidence(fixture_dir, "fixture.jsonl")
        fixture = StaticFixture(fixture_dir, evidence, protocol["run_id"] + "-" + str(action))
        network = None
        sealed = True
        try:
            bindings = fixture.start()
            manual = dict(protocol_path=str(output / "protocol.json"), protocol_digest=digest(protocol),
                expires_monotonic_ns=protocol["declared_monotonic_ns"] + protocol["budget_seconds"] * 10**9,
                operator_uid=os.getuid(), operator_pid=os.getpid(), authority_kind="scoped-manual-driver-campaign")
            write(fixture_dir / "manual.json", manual)
            network = native_namespace(binding_object(bindings), fixture_dir, evidence)
            original_run = record_subprocesses(evidence)
            driver = LinuxFRRDriver(network, resource_id=manual.get("resource_id", bindings["resource_id"]), run_id=bindings["run_id"],
                binding_sha256=digest(protocol), ownership_check=network.ownership, dispatch_guard=lambda: None)
            queue_snapshot(network, evidence, "epoch-entry")
            def prepare(name):
                path = fixture_dir / name
                path.mkdir(mode=0o700)
                return path
            # Actual lock contention against the pinned adapter, no synthetic PID reuse.
            try:
                second = AttachedFRRNetwork(binding_object(bindings), lock_directory=fixture_dir)
            except BlockingIOError:
                result["cases"].append(dict(action=action, case="exclusive-lock", status="passed"))
            else:
                second.close()
                raise ValueError("exclusive_lock_not_enforced")
            for kind, count in [("STOP", k) for k in range(13)] + [("expired", 0), ("binding-refusal", 0),
                    ("foreign", 12), ("restart", 3), ("lost-receipt", 3), ("recovery-interrupted", 3), ("normal", 12)]:
                if time.monotonic_ns() >= manual["expires_monotonic_ns"]:
                    raise ValueError("campaign_budget_exhausted")
                case = prepare(kind + "-" + str(count))
                active_case = case
                plan = dict(runtime=RUNTIME, action=action, runtime_binding_sha256=digest(protocol))
                prepared = await driver.prepare(plan)
                if kind == "binding-refusal":
                    changed = dict(prepared, binding_sha256="0" * 64)
                    try:
                        await driver.apply(changed, lambda: None)
                    except ValueError as exc:
                        if str(exc) != "frr_prepared_identity_mismatch":
                            raise
                    else:
                        raise ValueError("binding_refusal_failed")
                    result["cases"].append(dict(action=action, case=case.name, status="passed"))
                    active_case = None
                    continue
                pin = write(case / "prepared.json", prepared)
                (case / "prepared.sha256").write_text(pin)
                with (case / "prepared.sha256").open() as stream:
                    os.fsync(stream.fileno())
                # Release only our adapter; child obtains same lock, processes are joined.
                network.close()
                subprocess.run = original_run
                args = [sys.executable, __file__, "--child", "--output", str(fixture_dir), "--case", str(case), "--operation", "apply"]
                if kind == "STOP":
                    args += ["--stop", str(count)]
                if kind == "expired":
                    args += ["--expired"]
                if kind in {"restart", "lost-receipt"}:
                    args += ["--crash", "3"] + (["--lost"] if kind == "lost-receipt" else [])
                child = subprocess.run(args, capture_output=True, timeout=300)
                write(case / "apply-process.json", dict(returncode=child.returncode, stdout=child.stdout.decode(), stderr=child.stderr.decode()))
                if child.returncode != (74 if kind == "lost-receipt" else 73 if kind == "restart" else 0):
                    raise ValueError("apply_child_failed")
                if kind == "foreign":
                    network = native_namespace(binding_object(bindings), fixture_dir, evidence)
                    original_run = record_subprocesses(evidence)
                    driver.network, driver.ownership_check = network, network.ownership
                    foreign = ["ip", "rule", "add", "priority", "19110", "from", "192.0.2.1/32", "to", "192.0.2.2/32", "table", "19110"]
                    network.command("core", foreign)
                    before = driver.inventory("core", 19110)
                    denied = Authority(network, evidence, manual, prepared, recovery=True)
                    try:
                        try:
                            await driver.compensate(prepared, denied.checkpoint)
                        except ValueError as exc:
                            if str(exc) != "foreign_or_incomplete_frr_resource":
                                raise
                        else:
                            raise ValueError("foreign_not_refused")
                        if denied.count or driver.inventory("core", 19110) != before:
                            raise ValueError("foreign_refusal_mutated")
                        write(case / "foreign-refusal.json", dict(deletes=denied.count, before=before, after=driver.inventory("core", 19110)))
                    finally:
                        denied.close()
                        network.command("core", ["ip", "rule", "del", *foreign[3:]])
                    network.close()
                    subprocess.run = original_run
                if kind == "normal":
                    network = native_namespace(binding_object(bindings), fixture_dir, evidence)
                    original_run = record_subprocesses(evidence)
                    driver.network = network
                    driver.ownership_check = network.ownership
                    driver.read_owned(prepared, complete=True)
                    queue_snapshot(network, evidence, "epoch-exit")
                    evidence.event("sealed_epoch_closed")
                    sealed = False
                    for link in network.plan:
                        for e in link["endpoints"]:
                            network.command(e["node"], ["tc", "filter", "del", "dev", e["interface"], "egress", "pref", "1"])
                    verification = await driver.verify(prepared, plan)
                    write(case / "unsealed-verification.json", verification)
                    network.close()
                    subprocess.run = original_run
                recover_args = [sys.executable, __file__, "--child", "--output", str(fixture_dir), "--case", str(case), "--operation", "recover"]
                if not sealed:
                    recover_args += ["--unsealed"]
                if kind == "recovery-interrupted":
                    interrupted = subprocess.run(recover_args + ["--crash", "3"], capture_output=True, timeout=300)
                    write(case / "recovery-interruption.json", dict(returncode=interrupted.returncode, stderr=interrupted.stderr.decode()))
                    if interrupted.returncode != 73:
                        raise ValueError("recovery_interruption_failed")
                for repetition in range(2):
                    recovered = subprocess.run(recover_args, capture_output=True, timeout=300)
                    write(case / ("recovery-process-" + str(repetition) + ".json"), dict(returncode=recovered.returncode,
                        stdout=recovered.stdout.decode(), stderr=recovered.stderr.decode()))
                    if recovered.returncode:
                        raise ValueError("recovery_child_failed")
                    recovery_result = json.loads(recovered.stdout)
                    if not recovery_result.get("restoration_verified") or (repetition == 1 and recovery_result["deletes"] != 0):
                        raise ValueError("idempotent_recovery_not_verified")
                active_case = None
                network = native_namespace(binding_object(bindings), fixture_dir, evidence)
                original_run = record_subprocesses(evidence)
                driver.network, driver.ownership_check = network, network.ownership
                result["cases"].append(dict(action=action, case=case.name, status="passed"))
                write(case / "case-complete.json", result["cases"][-1])
        except BaseException as exc:
            result["failures"].append(dict(action=action, error=repr(exc)))
            if active_case is not None:
                if network:
                    network.close()
                subprocess.run = original_run
                rescue = subprocess.run([sys.executable, __file__, "--child", "--output", str(fixture_dir), "--case", str(active_case),
                    "--operation", "recover", *([] if sealed else ["--unsealed"])], capture_output=True, timeout=300)
                write(active_case / "emergency-recovery.json", dict(returncode=rescue.returncode, stderr=rescue.stderr.decode()))
                if rescue.returncode:
                    result["unresolved_resources"].append(str(active_case))
            break
        finally:
            if network:
                network.close()
            if "original_run" in locals():
                subprocess.run = original_run
            if result["unresolved_resources"]:
                write(output / "operator-recovery-required.json", result)
                # Retain owned namespaces and exclusion, never destroy unresolved
                # state to manufacture clean acceptance. Host reports hard blocker.
                while True:
                    time.sleep(60)
            fixture.close()
            evidence.event("fixture_closed", unresolved=bool(result["unresolved_resources"]))
            evidence.stream.close()
    result["status"] = "passed" if not result["failures"] and len(result["cases"]) == 42 else "failed"
    write(output / "result.json", result)
    return result


def launch(args):
    output = Path(tempfile.mkdtemp(prefix="native-driver-", dir=args.output))
    lock = os.open("/tmp/opencode/nanfo-privileged-lab-slot.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    container = None
    try:
        evidence = Evidence(output, "host.jsonl")
        ids = evidence.command(["docker", "ps", "-q"]).split()
        for identity in ids:
            inspection = json.loads(evidence.command(["docker", "inspect", identity]))[0]
            if inspection["HostConfig"]["Privileged"]:
                raise ValueError("another_privileged_container_owns_slot")
        source = output / "source"
        (source / "backend/scripts").mkdir(parents=True)
        shutil.copytree(ROOT / "emulation", source / "emulation", ignore=shutil.ignore_patterns("output", "commands", "results", "__pycache__"))
        shutil.copy2(__file__, source / "backend/scripts/verify_native_driver.py")
        shutil.copy2(Path(__file__).with_name("native_driver.Dockerfile"), source / "Dockerfile")
        pins = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()}
        write(output / "sources.json", pins)
        image = "nanfo-native-driver:" + uuid.uuid4().hex
        evidence.command(["docker", "build", "--network", "default", "-t", image, str(source)], timeout=600)
        image_id = evidence.command(["docker", "image", "inspect", image, "--format", "{{.Id}}"]).strip()
        protocol = dict(version="nanfo.native-driver-acceptance/v1", run_id=str(uuid.uuid4()), image_id=image_id,
            source_sha256=pins, operator_uid=os.getuid(), declared_wall_ns=time.time_ns(), declared_monotonic_ns=time.monotonic_ns(),
            budget_seconds=1800, command_timeout_seconds=5, checkpoint_timeout_seconds=20, cpu=2, memory_mib=1536,
            authority_kind="scoped-manual-driver-campaign", slot_release="explicit user authorization after ContinuousAI pass",
            graph=linkPlan(), actions=[0, 1], stops=list(range(13)), fixture="static-FIB-no-OSPF", sealed_gate="clsact-egress-matchall-drop-all")
        protocol["cases_per_action"] = ["exclusive-lock", *["STOP-" + str(i) for i in range(13)], "expired-0",
            "binding-refusal-0", "foreign-12", "restart-3", "lost-receipt-3", "recovery-interrupted-3", "normal-12"]
        for name in ("result.json", "cleanup.json"):
            release = Path(args.release) / name
            shutil.copy2(release, output / ("continuous-release-" + name))
        write(output / "protocol.json", protocol)
        name = "nanfo-native-driver-" + uuid.uuid4().hex
        container = evidence.command(["docker", "run", "-d", "--name", name, "--privileged", "--network", "none",
            "--cpus", "2", "--memory", "1536m", "--pids-limit", "256", "--tmpfs", "/run:exec,size=64m",
            "--mount", "type=bind,src=" + str(source) + ",dst=/source,readonly",
            "--mount", "type=bind,src=" + str(output) + ",dst=/evidence", image_id, "--inside", "--output", "/evidence"]).strip()
        write(output / "container.json", json.loads(evidence.command(["docker", "inspect", container])))
        evidence.command(["docker", "wait", container], timeout=1900)
        logs = evidence.command(["docker", "logs", container])
        write(output / "container-log.json", {"log": logs})
        print(str(output))
    finally:
        if container:
            running = subprocess.run(["docker", "inspect", container, "--format", "{{.State.Running}}"],
                                     capture_output=True, text=True, check=True, timeout=10).stdout.strip()
            if running == "true":
                print("Owned container still running; do not release slot or destroy unresolved resources: " + container, file=sys.stderr)
                while True:
                    time.sleep(60)
            # Export only this campaign's files to its creating operator identity.
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "chown",
                "--mount", "type=bind,src=" + str(output) + ",dst=/evidence", image_id,
                "-R", str(os.getuid()) + ":" + str(os.getgid()), "/evidence"], check=True, timeout=30)
            subprocess.run(["docker", "rm", "-f", container], check=True, timeout=30)
            write(output / "cleanup.json", dict(container_id=container, removed=True,
                scope="only-this-owned-container", unresolved_resources=json.loads((output / "result.json").read_text()).get("unresolved_resources", [])))
        os.close(lock)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", default="/tmp/opencode/nanfo-live-acceptance-7ngrbdgv")
    parser.add_argument("--case")
    parser.add_argument("--operation", choices=("apply", "recover"))
    parser.add_argument("--stop", type=int)
    parser.add_argument("--crash", type=int)
    parser.add_argument("--lost", action="store_true")
    parser.add_argument("--unsealed", action="store_true")
    parser.add_argument("--expired", action="store_true")
    args = parser.parse_args()
    if args.launch:
        launch(args)
    elif args.child:
        print(json.dumps(asyncio.run(phase(args.output, args.case, args.operation, stop=args.stop, crash=args.crash,
                                         lost=args.lost, sealed=not args.unsealed, expired=args.expired))))
    elif args.inside:
        print(json.dumps(asyncio.run(campaign(args.output))))
    else:
        parser.error("explicit --launch, --inside or --child required")


if __name__ == "__main__":
    main()
