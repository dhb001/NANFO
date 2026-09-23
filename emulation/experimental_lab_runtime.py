"""One original v4 experiment; guarded transport, never rewritten source/provenance."""

import hashlib
import importlib
import json
import os
import time
from pathlib import Path

try:
    from .experimental_lab_contract import IMAGE, SOURCE, digest, require, snapshot
except ImportError:
    from experimental_lab_contract import IMAGE, SOURCE, digest, require, snapshot


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
                      "compensation_mutations": 0}
        self.transcript = []
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
        # All original shape/readback calls pass through unchanged. Only the exact
        # matched-owned rule/table mutations are admitted by this wrapper.
        mutation = args[:2] in (["ip", "route"], ["ip", "rule"])
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
            return snapshot({"baseline": self.baseline, "baseline_sha256": digest(self.baseline),
                    "readback": readback, "owned_empty": not self.routing.owned,
                    "original_forwarding_verified": True,
                    "duration_seconds": time.monotonic() - began})
        finally:
            self.restoring = False
            self.persist()

    def thresholds(self, evidence, policy):
        data = evidence["frame"]["response"]["data"]
        obs = data["observation"]
        ping = data["evidence"]["ping"]
        return (obs["goodput_mbps"] >= policy["min_goodput_mbps"]
                and obs["loss_fraction"] <= policy["max_loss_fraction"]
                and ping["sent"] > 0 and 1 - ping["received"] / ping["sent"] <= policy["max_loss_fraction"]
                and obs["latency_ms"] is not None and obs["latency_ms"] <= policy["max_rtt_ms"])


def load_original(source_directory):
    """Must run with frozen source parent on PYTHONPATH, wrapper in separate mount."""
    directory = Path(source_directory).resolve()
    module = importlib.import_module("emulation.experiment")
    require(Path(module.__file__).resolve().parent == directory, "wrong_loaded_source_directory")
    spec, spec_hash = module.environmentSpec("matched")
    require(spec["source_sha256"] == SOURCE and spec["version"] == 4, "frozen_source_mismatch")
    require(os.environ.get("NANFO_LAB_IMAGE_ID") == IMAGE, "image_binding_mismatch")
    for name, expected in spec["source_files"].items():
        require(hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected,
                "frozen_file_mismatch")
    require(digest(spec) == spec_hash, "spec_hash_mismatch")
    matched = importlib.import_module("emulation.matched")
    require(Path(matched.__file__).resolve().parent == directory, "wrong_matched_source")
    return module
