"""Journaled Linux/FRR source-specific host routes, separate from frozen experiments.

Same paths, /32 selectors, tables and kernel commands as matched.MatchedRouting;
preparation/readback/compensation are durable-receiver operations rather than an
experiment step. Does not create namespaces, run workloads or change FRR costs.
"""

import asyncio
import json

from emulation.autonomous_contract import RUNTIME, action_map
from emulation.autonomous_driver import finish_thread, readback_digest
from emulation.measurements import parsePing, utcNow
from emulation.ospf import PATHS, ROUTERS, linkPlan

TABLES = (19110, 19111)
PAIRS = (("h1", "h3"), ("h3", "h1"), ("h2", "h4"), ("h4", "h2"))


def validate_plan(plan):
    if (set(plan) != {"runtime", "action", "runtime_binding_sha256"} or plan["runtime"] != RUNTIME
            or type(plan["action"]) is not int or plan["action"] not in (0, 1)
            or not isinstance(plan["runtime_binding_sha256"], str)
            or len(plan["runtime_binding_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in plan["runtime_binding_sha256"])):
        raise ValueError("invalid_frr_plan")
    return plan


class LinuxFRRDriver:
    driver_id = RUNTIME

    def __init__(self, network, *, resource_id, run_id, binding_sha256, ownership_check, dispatch_guard,
                 baseline_action=0):
        self.network, self.resource_id, self.run_id = network, resource_id, str(run_id)
        self.binding_sha256, self.ownership_check = binding_sha256, ownership_check
        self.dispatch_guard = dispatch_guard
        if type(baseline_action) is not int or baseline_action not in (0, 1):
            raise ValueError("frr_baseline_action_required")
        self.baseline_action = baseline_action
        if not callable(dispatch_guard):
            raise ValueError("frr_independent_dispatch_guard_required")
        if network.plan != linkPlan() or action_map() != {str(i): list(p) for i, p in enumerate(PATHS)}:
            raise ValueError("frr_topology_not_frozen_action_map")

    def owned(self):
        if self.ownership_check(self.resource_id, self.run_id) is not True:
            raise ValueError("frr_namespace_ownership_lost")

    async def healthcheck(self):
        def read():
            self.owned()
            self.paths()
            for node in ROUTERS:
                for table in TABLES:
                    self.inventory(node, table)
            self.owned()
        await finish_thread(read)

    def inventory(self, node, table):
        rules = json.loads(self.network.command(node, ["ip", "-j", "rule", "show"]))
        routes = json.loads(self.network.command(node, ["ip", "-j", "route", "show", "table", "all"]))
        return {"rules": [r for r in rules if r.get("priority") == table or str(r.get("table")) == str(table)],
                "routes": [r for r in routes if str(r.get("table")) == str(table)]}

    def paths(self):
        return {f"{s}->{d}": self.network.routePath(s, d)["nodes"] for s, d in PAIRS}

    def resources(self, action):
        rows = []
        for table, (source, destination) in zip(TABLES, PAIRS[:2]):
            path = PATHS[action] if source == "h1" else tuple(reversed(PATHS[action]))
            for node, peer in zip(path, (*path[1:], destination)):
                link = next(link for link in self.network.plan if {link["a"][0], link["b"][0]} == {node, peer})
                endpoint = next(e for e in link["endpoints"] if e["node"] == node)
                gateway = next(e["ipv4"] for e in link["endpoints"] if e["node"] == peer)
                rows.append(dict(node=node, table=table, source=self.network.hostAddresses[source],
                    destination=self.network.hostAddresses[destination], interface=endpoint["interface"], gateway=gateway))
        return rows

    @staticmethod
    def matches(row, value, kind):
        if kind == "rules":
            # Reject foreign semantics even when the obvious source/destination match.
            return (set(value) <= {"priority", "src", "dst", "table", "protocol"}
                and value.get("priority") == row["table"] and str(value.get("table")) == str(row["table"])
                and value.get("src") in (row["source"], row["source"] + "/32")
                and value.get("dst") in (row["destination"], row["destination"] + "/32")
                and value.get("protocol", "unspec") in ("unspec", "boot"))
        return (set(value) <= {"dst", "gateway", "dev", "table", "protocol", "flags", "scope"}
            and str(value.get("table")) == str(row["table"])
            and value.get("dst") in (row["destination"], row["destination"] + "/32")
            and value.get("gateway") == row["gateway"] and value.get("dev") == row["interface"]
            and value.get("protocol") == "static" and value.get("flags", []) == ["onlink"]
            and value.get("scope", "global") == "global")

    def read_owned(self, prepared, *, complete):
        expected = {(r["node"], r["table"]): r for r in prepared["resources"]}
        actual = {}
        # Inspect ALL reserved tables, including unused routers and absent resources.
        for node in ROUTERS:
            for table in TABLES:
                inventory = self.inventory(node, table)
                row = expected.get((node, table))
                for kind, values in inventory.items():
                    if (len(values) > 1 or (values and (row is None or not self.matches(row, values[0], kind)))
                            or (complete and row is not None and len(values) != 1)):
                        raise ValueError("foreign_or_incomplete_frr_resource")
                actual[f"{node}:{table}"] = inventory
        return actual

    def validate_prepared(self, prepared):
        self.owned()
        if (prepared.get("runtime") != RUNTIME or prepared.get("run_id") != self.run_id
                or prepared.get("binding_sha256") != self.binding_sha256
                or prepared.get("resources") != self.resources(prepared["plan"]["action"])):
            raise ValueError("frr_prepared_identity_mismatch")
        validate_plan(prepared["plan"])
        if prepared["plan"]["runtime_binding_sha256"] != self.binding_sha256:
            raise ValueError("frr_plan_binding_mismatch")

    @staticmethod
    def command(row, kind, operation):
        if kind == "rules":
            return ["ip", "rule", operation, "priority", str(row["table"]), "from", row["source"] + "/32",
                    "to", row["destination"] + "/32", "table", str(row["table"])]
        return ["ip", "route", operation, row["destination"] + "/32", "via", row["gateway"],
                "dev", row["interface"], *(["onlink"] if operation == "add" else []),
                "table", str(row["table"]), "proto", "static"]

    async def prepare(self, plan):
        validate_plan(plan)
        def read():
            self.owned()
            if plan["runtime_binding_sha256"] != self.binding_sha256:
                raise ValueError("frr_plan_binding_mismatch")
            before = self.paths()
            for source, destination in PAIRS[:2]:
                path = PATHS[self.baseline_action]
                if before[f"{source}->{destination}"] != [source, *(path if source == "h1" else reversed(path)), destination]:
                    raise ValueError("frr_baseline_action_readback_mismatch")
            prepared = dict(runtime=RUNTIME, run_id=self.run_id, binding_sha256=self.binding_sha256,
                plan=plan, resources=self.resources(plan["action"]), before=before)
            for node in ROUTERS:
                for table in TABLES:
                    if any(self.inventory(node, table).values()):
                        raise ValueError("reserved_frr_resource_already_owned")
            return prepared
        return await finish_thread(read)

    async def apply(self, prepared, checkpoint):
        loop = asyncio.get_running_loop()
        def write():
            self.validate_prepared(prepared)
            for row in prepared["resources"]:
                for kind in ("routes", "rules"):
                    self.validate_prepared(prepared)
                    self.read_owned(prepared, complete=False)
                    if self.inventory(row["node"], row["table"])[kind]:
                        raise ValueError("frr_resource_changed_before_add")
                    args = self.command(row, kind, "add")
                    self.owned()
                    # All binding/namespace/inventory reads precede the final
                    # server check. Never spend its authority on another read sweep.
                    self.network.mutate(row["node"], args,
                        lambda: asyncio.run_coroutine_threadsafe(checkpoint(), loop).result(timeout=20))
        await finish_thread(write)

    async def verify(self, prepared, plan):
        def read():
            self.validate_prepared(prepared)
            if plan != prepared["plan"]:
                raise ValueError("frr_readback_plan_mismatch")
            actual = self.read_owned(prepared, complete=True)
            paths = self.paths()
            for s, d in PAIRS[:2]:
                path = PATHS[plan["action"]]
                expected = [s, *(path if s == "h1" else reversed(path)), d]
                if paths[f"{s}->{d}"] != expected:
                    raise ValueError("frr_actual_path_mismatch")
            for s, d in PAIRS[2:]:
                if paths[f"{s}->{d}"] != prepared["before"][f"{s}->{d}"]:
                    raise ValueError("frr_background_path_changed")
            sent = received = 0
            for s, d in PAIRS[:2]:
                raw = self.network.command(s, ["ping", "-n", "-c", "3", "-i", ".1", "-W", "1",
                                                self.network.hostAddresses[d]])
                probe = parsePing(raw, s, d, 1.0, utcNow())
                if probe is None or probe["sent"] != 3 or probe["received"] != 3:
                    raise ValueError("frr_reachability_failed")
                sent += probe["sent"]
                received += probe["received"]
            return {"readback_sha256": readback_digest({"resources": actual, "paths": paths}),
                    "readback_verified": True, "probe": {"sent": sent, "received": received},
                    "traffic_effects_verified": False}
        return await finish_thread(read)

    async def compensate(self, prepared, checkpoint):
        loop = asyncio.get_running_loop()
        def restore():
            self.validate_prepared(prepared)
            # Refuse all foreign state BEFORE deleting any owned tuple.
            self.read_owned(prepared, complete=False)
            for row in reversed(prepared["resources"]):
                for kind in ("rules", "routes"):
                    self.validate_prepared(prepared)
                    self.read_owned(prepared, complete=False)
                    if self.inventory(row["node"], row["table"])[kind]:
                        args = self.command(row, kind, "del")
                        self.owned()
                        # This callback is the independent recovery ownership/fence
                        # boundary, not the revoked requester's dispatch authority.
                        self.network.mutate(row["node"], args,
                            lambda: asyncio.run_coroutine_threadsafe(checkpoint(), loop).result(timeout=20))
            for node in ROUTERS:
                for table in TABLES:
                    if any(self.inventory(node, table).values()):
                        raise ValueError("frr_restoration_resources_remain")
            actual = self.paths()
            if actual != prepared["before"]:
                raise ValueError("frr_baseline_not_restored")
            return {"readback_sha256": readback_digest(actual), "restoration_verified": True}
        return await finish_thread(restore)
