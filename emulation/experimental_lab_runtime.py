"""One original v4 experiment; guarded transport, never rewritten source/provenance."""

import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

try:
    from .experimental_lab_contract import IMAGE, SOURCE, digest, require, snapshot, thresholds_pass
except ImportError:
    from experimental_lab_contract import IMAGE, SOURCE, digest, require, snapshot, thresholds_pass


class GuardedRuntime:
    def __init__(self, experiment, authority, persist, boundary=None, dispatch_authority=None):
        self.experiment = experiment
        self.routing = experiment.routing
        self.network = experiment.lab.network
        self.authority, self.persist = authority, persist
        self.boundary = boundary or (lambda *_: None)
        self.dispatch_authority = dispatch_authority
        self.original_command = self.network.command
        self.network.command = self.command
        self.restoring = False
        self.baseline = None
        self.calls = {"mutation_attempted": 0, "mutation_completed": 0,
                      "authority_checks": 0, "original_change_calls": 0,
                      "compensation_mutations": 0, "state_mutation_attempted": 0,
                      "state_mutation_completed": 0, "state_authority_checks": 0,
                      "state_compensations": 0}
        self.transcript = []
        self.state_transcript = []
        self.state_baseline = {}
        self.frames = []
        self.namespace_identities = {}
        self.frame_action = None
        self.frame_changes = 0
        original_change = self.routing.change

        def change(action):
            require(not self.restoring, "recovery_cannot_call_change")
            if self.frame_action is not None:
                require(action == self.frame_action, "unexpected_original_action")
                if self.frame_changes:
                    require(self.routing.action == action, "readback_cannot_reinstall_lost_route")
                self.frame_changes += 1
            self.calls["original_change_calls"] += 1
            return original_change(action)

        self.routing.change = change
        original_close = self.routing.close

        def close():
            # Check ALL reserved slots before any destructive cleanup, including
            # implicit frozen exception/terminal close and break-before-make.
            self.validate_cleanup()
            return original_close()

        self.routing.close = close
        original_check = experiment.lab.checkController

        def check():
            if not self.restoring:
                self.authority()
            return original_check()

        experiment.lab.checkController = check

    def state(self):
        return snapshot({"owned": self.routing.owned, "original": self.routing.original,
                "action": self.routing.action, "baseline": self.baseline,
                "calls": dict(self.calls), "transcript": list(self.transcript),
                "state_transcript": list(self.state_transcript),
                "state_baseline": dict(self.state_baseline),
                "frame_hashes": [digest(frame) for frame in self.frames],
                "namespace_identities": self.namespace_identities})

    def validate_slot(self, node, table, owned):
        rules, routes = self.routing.inventory(node, table)
        require(len(rules) <= 1 and len(routes) <= 1, "foreign_duplicate_reserved_rows")
        if owned is None:
            require(not rules and not routes, "foreign_unowned_reserved_slot")
            return
        _, _, src, dst, interface, gateway = owned
        for row in rules:
            require(set(row) <= {"priority", "table", "src", "dst", "flags", "action", "protocol", "tos"}
                    and type(row.get("priority")) is int and row["priority"] == table
                    and str(row.get("table")) == str(table)
                    and row.get("src") in (src, src + "/32")
                    and row.get("dst") in (dst, dst + "/32")
                    and row.get("flags", []) == [] and row.get("action", "to_tbl") == "to_tbl"
                    and row.get("protocol", "boot") == "boot" and row.get("tos", 0) == 0,
                    "foreign_policy_rule_semantics")
        for row in routes:
            require(set(row) <= {"table", "dst", "dev", "gateway", "protocol", "flags", "type", "scope", "tos"}
                    and str(row.get("table")) == str(table)
                    and row.get("dst") in (dst, dst + "/32") and row.get("dev") == interface
                    and row.get("gateway") == gateway and row.get("protocol") == "static"
                    and row.get("flags") == ["onlink"]
                    and row.get("type", "unicast") == "unicast"
                    and row.get("scope", "global") == "global" and row.get("tos", 0) == 0,
                    "foreign_policy_route_semantics")

    def validate_cleanup(self):
        from emulation.matched import TABLES
        from emulation.ospf import ROUTERS

        owned = {(row[0], row[1]): row for row in self.routing.owned}
        require(len(owned) == len(self.routing.owned), "foreign_duplicate_ownership")
        for node in {row[0] for row in self.routing.owned}:
            routes = json.loads(self.original_command(node, ["ip", "-j", "route", "show", "table", "all"]))
            for route in routes:
                if route.get("protocol") != "static":
                    continue
                for n, table, _, dst, interface, gateway in self.routing.owned:
                    if (n == node and route.get("dst") in (dst, dst + "/32")
                            and route.get("dev") == interface and route.get("gateway") == gateway):
                        require(str(route.get("table")) == str(table), "foreign_owned_route_table")
        for node in ROUTERS:
            for table in TABLES:
                self.validate_slot(node, table, owned.get((node, table)))

    def command(self, node, args, timeout=5):
        # ADR-028: every command is classified. Readbacks pass through unchanged; the
        # exact matched-owned rule/table mutations keep their frozen checks below; any
        # other lab-state mutation (tc/sysctl/ip link/addr/...) is authority/STOP
        # checked, WAL-recorded with its before-state and restored by restore().
        kind = classify_command(args)
        if kind == "state":
            return self.state_command(node, args, timeout)
        mutation = kind == "route"
        if mutation:
            require(len(args) > 2 and args[2] in ("add", "del"), "unexpected_mutation")
            allowed = []
            for n, table, src, dst, interface, gateway in self.routing.owned:
                if n != node:
                    continue
                for verb in ("add", "del"):
                    allowed.append(["ip", "rule", verb, "priority", str(table), "from",
                                    src + "/32", "to", dst + "/32", "table", str(table)])
                    allowed.append(["ip", "route", verb, dst + "/32", "via", gateway,
                                    "dev", interface, *(["onlink"] if verb == "add" else []),
                                    "table", str(table), "proto", "static"])
            require(args in allowed, "mutation_outside_exact_owned_route")
            require(not self.restoring or args[2] == "del", "recovery_cannot_add_routes")
            if self.restoring:
                self.calls["compensation_mutations"] += 1
            self.calls["mutation_attempted"] += 1
            entry = {"node": node, "argv": list(args), "began": time.monotonic(),
                     "completed": None, "restoring": self.restoring}
            self.transcript.append(entry)
            self.persist()  # owned intent, original baseline and command before I/O
            self.boundary("before", entry)
            # No journal, blocking read or hook between this check and dispatch.
            if args[2] == "add":
                self.calls["authority_checks"] += 1
                if self.dispatch_authority is not None:
                    self.dispatch_authority(entry)
                else:
                    self.authority()
            elif not self.restoring:
                try:
                    self.calls["authority_checks"] += 1
                    self.authority()
                except (ValueError, RuntimeError, OSError):
                    self.calls["compensation_mutations"] += 1
            if args[2] == "del":
                table = int(args[args.index("table") + 1])
                owned = next((row for row in self.routing.owned if row[:2] == (node, table)), None)
                self.validate_slot(node, table, owned)
        result = self.original_command(node, args, timeout=timeout)
        if mutation:
            self.calls["mutation_completed"] += 1
            entry["completed"] = time.monotonic()
            self.persist()
            self.boundary("after", entry)
        return result

    def state_command(self, node, args, timeout):
        require(not self.restoring, "recovery_cannot_mutate_lab_state")
        for key, before in self.state_resources(node, list(args)):
            if key not in self.state_baseline:
                self.state_baseline[key] = before()
        entry = {"node": node, "argv": list(args), "began": time.monotonic(), "completed": None}
        self.state_transcript.append(entry)
        self.calls["state_mutation_attempted"] += 1
        self.persist()  # before-state and command are durable before the write
        self.calls["state_authority_checks"] += 1
        self.authority()
        result = self.original_command(node, args, timeout=timeout)
        entry["completed"] = time.monotonic()
        self.calls["state_mutation_completed"] += 1
        self.persist()
        return result

    def state_resources(self, node, args):
        """Supported state mutations and their exact before-state readers."""
        if (len(args) == 14 and args[:3] == ["tc", "class", "change"] and args[3] == "dev"
                and args[5] == "parent" and args[7] == "classid" and args[9] == "htb"
                and args[10] == "rate" and args[12] == "ceil"):
            dev, parent, classid = args[4], args[6], args[8]
            return [(f"{node}|tc-class|{dev}|{classid}",
                     lambda: {"node": node, "kind": "tc-class", "dev": dev, "parent": parent,
                              "classid": classid, **self.read_class(node, dev, classid)})]
        if args[:1] == ["sysctl"] and len(args) >= 3 and args[1] in ("-w", "-qw"):
            settings = [item.split("=", 1) for item in args[2:]]
            require(all(len(item) == 2 and SYSCTL_NAME.fullmatch(item[0]) for item in settings),
                    "unsupported_state_mutation")
            return [(f"{node}|sysctl|{name}",
                     lambda name=name: {"node": node, "kind": "sysctl", "name": name,
                                        "value": self.read_sysctl(node, name)})
                    for name, _ in settings]
        raise ValueError("unsupported_state_mutation")

    def read_class(self, node, dev, classid):
        text = self.original_command(node, ["tc", "class", "show", "dev", dev, "classid", classid])
        match = re.search(r"\brate (\S+) ceil (\S+)", text)
        require(match is not None, "state_readback_unavailable")
        return {"rate": match.group(1), "ceil": match.group(2)}

    def read_sysctl(self, node, name):
        return self.original_command(node, ["sysctl", "-n", name]).strip()

    def restore_state(self):
        """Return every WAL-recorded lab-state resource to its captured before-state."""
        restored = []
        for key, before in self.state_baseline.items():
            node = before["node"]
            if before["kind"] == "tc-class":
                current = self.read_class(node, before["dev"], before["classid"])
                wanted = {"rate": before["rate"], "ceil": before["ceil"]}
                if current != wanted:
                    self.calls["state_compensations"] += 1
                    self.original_command(node, ["tc", "class", "change", "dev", before["dev"], "parent",
                        before["parent"], "classid", before["classid"], "htb", "rate", before["rate"],
                        "ceil", before["ceil"]])
                    current = self.read_class(node, before["dev"], before["classid"])
            else:
                current, wanted = self.read_sysctl(node, before["name"]), before["value"]
                if current != wanted:
                    self.calls["state_compensations"] += 1
                    self.original_command(node, ["sysctl", "-qw", before["name"] + "=" + wanted])
                    current = self.read_sysctl(node, before["name"])
            require(current == wanted, "original_lab_state_not_restored")
            restored.append(key)
        return restored

    def capture_baseline(self):
        require(self.baseline is None and not self.routing.owned, "baseline_already_owned")
        baseline = self.original_readback()
        require(all(not row["rules"] and not row["routes"]
                    for row in baseline["tables"].values()), "reserved_tables_not_empty")
        self.baseline = baseline
        if getattr(self.network, "net", None) is not None:
            for node in self.network.net.values():
                pid = node.pid
                text = Path(f"/proc/{pid}/stat").read_text()
                self.namespace_identities[node.name] = {
                    "pid": pid, "start_ticks": int(text[text.rfind(")") + 2:].split()[19]),
                    "netns": os.readlink(f"/proc/{pid}/ns/net")}
        self.persist()
        return snapshot(baseline)

    def original_readback(self):
        # Actual kernel inventory and route-get traversal, never routing.action.
        from emulation.matched import PAIRS, TABLES
        from emulation.ospf import ROUTERS

        tables = {}
        for node in ROUTERS:
            for table in TABLES:
                rules, routes = self.routing.inventory(node, table)
                tables[f"{node}:{table}"] = {"rules": rules, "routes": routes}
        return {"tables": tables, "paths": {
            f"{src}->{dst}": self.network.routePath(src, dst) for src, dst in PAIRS}}

    def frame(self, action=None):
        exp = self.experiment
        initial = exp.episode is None
        require(self.baseline is not None, "prebootstrap_baseline_required")
        require(initial or (not exp.done and exp.index < 3), "nonterminal_window_budget_exhausted")
        request = dict(version=1, command="reset" if initial else "step",
                       episode_id=None if initial else exp.episode,
                       step_index=None if initial else exp.index + 1,
                       seed=self.seed, scenario=self.scenario, action=None if initial else action,
                       mode="matched", window_seconds=2.0, episode_steps=4)
        began = time.monotonic()
        self.frame_action, self.frame_changes = (0 if initial else action), 0
        try:
            response = exp.handle(request)
        finally:
            self.frame_action = None
        frame = {"request": request, "response": response}
        self.frames.append(snapshot(frame))
        self.persist()
        require(response["ok"] and response["data"]["evidence"]["measurement_complete"]
                and not response["data"]["terminated"] and not response["data"]["truncated"],
                "original_measurement_failed")
        return {"frame": frame, "elapsed_seconds": time.monotonic() - began,
                "readback": self.routing.readback(), "completed_at": time.time(),
                "clock_monotonic": time.monotonic(), "clock_wall": time.time()}

    def restore(self, timeout_seconds=0):
        require(self.baseline is not None, "baseline_unavailable")
        self.restoring = True
        began = time.monotonic()
        try:
            # change() alone is insufficient after partial apply: its cached action
            # may still name the baseline. close() verifies/removes exact owned state.
            deadline = began + timeout_seconds
            while True:
                try:
                    self.routing.close()
                    readback = self.original_readback()
                    matches = (readback["tables"] == self.baseline["tables"] and
                        all(readback["paths"][k]["nodes"] == v["nodes"]
                            for k, v in self.baseline["paths"].items()))
                    if matches:
                        break
                except RuntimeError as exc:
                    # The frozen close removes owned rows BEFORE checking FRR.
                    # An outage can temporarily prevent that read-only traversal.
                    # Never retry a mutation/foreign-state/unknown error here.
                    if str(exc) not in {
                        "Original FRR forwarding not restored",
                        "Missing or ambiguous kernel next hop", "Kernel forwarding loop",
                    }:
                        raise
                require(not self.routing.owned, "recovery_owned_state_unresolved")
                require(time.monotonic() < deadline, "original_forwarding_not_restored")
                time.sleep(min(.1, max(0, deadline - time.monotonic())))
            # Preserve full raw readback, compare stable forwarding identity. Kernel
            # cache/expiry metadata is not configured forwarding state.
            require(readback["tables"] == self.baseline["tables"] and
                    all(readback["paths"][k]["nodes"] == v["nodes"]
                        for k, v in self.baseline["paths"].items()), "original_forwarding_not_restored")
            state_restored = self.restore_state()
            return snapshot({"baseline": self.baseline, "baseline_sha256": digest(self.baseline),
                    "readback": readback, "owned_empty": not self.routing.owned,
                    "original_forwarding_verified": True, "lab_state_restored": state_restored,
                    "duration_seconds": time.monotonic() - began})
        finally:
            self.restoring = False
            self.persist()

    def thresholds(self, evidence, policy):
        data = evidence["frame"]["response"]["data"]
        received = data["evidence"].get("udp_received")
        traffic = (received[0].get("bytes") if isinstance(received, list) and received
                   and isinstance(received[0], dict) else None)
        return thresholds_pass(data["observation"], data["evidence"]["ping"], traffic, policy)


MUTATING_VERBS = frozenset({"add", "del", "delete", "change", "replace", "set", "flush", "append",
                            "prepend", "save", "restore", "exec", "attach", "detach"})
SYSCTL_NAME = re.compile(r"net\.ipv4\.(ip_forward|conf\.[A-Za-z0-9_.-]{1,40}\.(rp_filter|send_redirects))")


def classify_command(args):
    """'route' (exact owned ip route/rule), 'readback', or 'state' (any other write)."""
    args = list(args)
    if args[:2] in (["ip", "route"], ["ip", "rule"]):
        return "route"
    head, rest = (args[0], args[1:]) if args else ("", [])
    if head in ("ip", "tc"):
        read = "show" in rest or "list" in rest or (head == "ip" and "get" in rest)
        return "readback" if read and not MUTATING_VERBS.intersection(rest) else "state"
    if head == "sysctl":
        writes = any("=" in item for item in rest) or any(
            item.startswith("-") and "w" in item for item in rest)
        return "state" if writes else "readback"
    if head == "vtysh":
        commands = [rest[index + 1] for index, item in enumerate(rest[:-1]) if item == "-c"]
        return "readback" if commands and all(c.startswith("show ") for c in commands) else "state"
    return "state"


def load_original(source_directory):
    """Must run with frozen source parent on PYTHONPATH, wrapper in separate mount.

    ADR-028: every frozen file is read once and hashed BEFORE any of it executes; the
    import system then executes only those verified bytes (no re-read/TOCTOU), and
    any unverified ``emulation.*`` module is refused for the process lifetime.
    """
    directory = Path(source_directory).resolve()
    require(os.environ.get("NANFO_LAB_IMAGE_ID") == IMAGE, "image_binding_mismatch")
    require("emulation" not in sys.modules, "emulation_package_already_imported")
    sources = {name: _read_frozen(directory, name) for name in (*FROZEN_SOURCE_FILES, "__init__.py")}
    hashes = {name: hashlib.sha256(sources[name]).hexdigest() for name in FROZEN_SOURCE_FILES}
    require(hashlib.sha256(sources["__init__.py"]).hexdigest() == FROZEN_PACKAGE_INIT_SHA256,
            "frozen_package_mismatch")
    require(source_digest(hashes) == SOURCE, "frozen_source_mismatch")
    sys.meta_path.insert(0, VerifiedSourceFinder(directory, {
        name: data for name, data in sources.items() if name.endswith(".py")}))
    module = importlib.import_module("emulation.experiment")
    require(Path(module.__file__).resolve().parent == directory, "wrong_loaded_source_directory")
    spec, spec_hash = module.environmentSpec("matched")
    require(spec["source_sha256"] == SOURCE and spec["version"] == 4
            and spec["source_files"] == hashes, "frozen_source_mismatch")
    require(digest(spec) == spec_hash, "spec_hash_mismatch")
    matched = importlib.import_module("emulation.matched")
    require(Path(matched.__file__).resolve().parent == directory, "wrong_matched_source")
    return module


# Exact frozen v4 experiment.SOURCE_FILES order/content (drift-tested against the archive).
FROZEN_SOURCE_FILES = ("experiment.py", "workloads.py", "actions.py", "topology.py", "ospf.py",
                       "matched.py", "measurements.py", "runner.py", "controller.py",
                       "experiment_client.py", "Dockerfile", "requirements.txt", "compose.yaml")
FROZEN_PACKAGE_INIT_SHA256 = "9f0ac359983701c537e4ebde9b412a3b8de66de3264321784b0fbab409ed89d5"
FROZEN_FILE_LIMIT = 4 * 1024 * 1024


def source_digest(hashes):
    """Frozen experiment.environmentSpec source digest over {name: sha256}."""
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":"))
                          .encode("ascii")).hexdigest()


def _read_frozen(directory, name):
    try:
        fd = os.open(str(directory / name), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ValueError("frozen_source_unavailable") from None
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_size <= FROZEN_FILE_LIMIT, "frozen_source_not_regular")
        chunks, size = [], 0
        while True:
            part = os.read(fd, 1 << 20)
            if not part:
                break
            size += len(part)
            require(size <= FROZEN_FILE_LIMIT, "frozen_source_not_regular")
            chunks.append(part)
        return b"".join(chunks)
    finally:
        os.close(fd)


class VerifiedSourceFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves the frozen ``emulation`` package only from pre-hashed in-memory bytes."""

    def __init__(self, directory, sources):
        self.directory, self.sources = directory, dict(sources)

    def find_spec(self, name, path=None, target=None):
        if name != "emulation" and not name.startswith("emulation."):
            return None
        filename = "__init__.py" if name == "emulation" else name[len("emulation."):] + ".py"
        if "/" in filename or filename.count(".") != 1 or filename not in self.sources:
            raise ImportError("unverified_frozen_module:" + name)
        return importlib.util.spec_from_file_location(
            name, str(self.directory / filename), loader=self,
            submodule_search_locations=[str(self.directory)] if name == "emulation" else None)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        filename = Path(module.__spec__.origin).name
        exec(compile(self.sources[filename], module.__spec__.origin, "exec"), module.__dict__)
