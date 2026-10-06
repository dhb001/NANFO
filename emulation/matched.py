"""ADR-013 source-specific foreground routing in the shared FRR lab."""

import json

from emulation.lab_contracts import RESERVED_TABLES, ROUTE_PAIRS
from emulation.ospf import PATHS, ROUTERS

# Shared versioned lab contract (drift-tested against the frozen v4 files).
TABLES = RESERVED_TABLES
PAIRS = ROUTE_PAIRS


class MatchedRouting:
    def __init__(self, lab):
        self.lab = lab
        self.network = lab.network
        self.action = None
        self.owned = []
        self.original = None

    def fixture(self, path):
        self.lab.checkController()  # Background always follows FRR, just as in baseline.

    def inventory(self, node, table):
        rules = json.loads(self.network.command(node, ["ip", "-j", "rule", "show"]))
        # Query all tables: iproute2 errors on a never-created empty table.
        routes = json.loads(
            self.network.command(node, ["ip", "-j", "route", "show", "table", "all"])
        )
        return (
            [r for r in rules if r.get("priority") == table or str(r.get("table")) == str(table)],
            [r for r in routes if str(r.get("table")) == str(table)],
        )

    def readback(self):
        result = {}
        for node, table, source, destination, interface, gateway in self.owned:
            rules, routes = self.inventory(node, table)
            if not (
                len(rules) == len(routes) == 1
                and rules[0].get("priority") == table
                and str(rules[0].get("table")) == str(table)
                and rules[0].get("src") in (source, source + "/32")
                and rules[0].get("dst") in (destination, destination + "/32")
                and routes[0].get("dst") in (destination, destination + "/32")
                and routes[0].get("dev") == interface
                and routes[0].get("gateway") == gateway
                and routes[0].get("protocol") == "static"
            ):
                raise RuntimeError("Foreground policy rule/table readback mismatch")
            result[f"{node}:{table}"] = {"rules": rules, "routes": routes}
        paths = {f"{s}->{d}": self.network.routePath(s, d) for s, d in PAIRS}
        for source, destination in PAIRS[:2]:
            expected = [source, *PATHS[self.action], destination]
            if source == "h3":
                expected = [source, *reversed(PATHS[self.action]), destination]
            if paths[f"{source}->{destination}"]["nodes"] != expected:
                raise RuntimeError("Foreground kernel path differs from entire explicit route")
        for source, destination in PAIRS[2:]:
            key = f"{source}->{destination}"
            if paths[key]["nodes"] != self.original[key]:
                raise RuntimeError("Foreground override changed background forwarding")
        return {"owned": result, "paths": paths}

    def change(self, action):
        if type(action) is not int or action not in (0, 1):
            raise ValueError("Foreground action must be 0 or 1")
        changed = self.action != action
        if changed:
            self.close()
            for node in ROUTERS:
                for table in TABLES:
                    rules, routes = self.inventory(node, table)
                    if rules or routes:
                        raise RuntimeError("Reserved foreground rule/table already occupied")
            self.original = {f"{s}->{d}": self.network.routePath(s, d)["nodes"] for s, d in PAIRS}
            try:
                for table, (source, destination) in zip(TABLES, PAIRS[:2]):
                    path = PATHS[action] if source == "h1" else tuple(reversed(PATHS[action]))
                    for node, peer in zip(path, (*path[1:], destination)):
                        link = next(
                            link
                            for link in self.network.plan
                            if {link["a"][0], link["b"][0]} == {node, peer}
                        )
                        endpoint = next(e for e in link["endpoints"] if e["node"] == node)
                        gateway = next(e["ipv4"] for e in link["endpoints"] if e["node"] == peer)
                        src, dst = (self.network.hostAddresses[h] for h in (source, destination))
                        interface = endpoint["interface"]
                        # Record before mutation: a timeout can occur after kernel acceptance.
                        self.owned.append((node, table, src, dst, interface, gateway))
                        self.network.command(
                            node,
                            [
                                "ip",
                                "route",
                                "add",
                                dst + "/32",
                                "via",
                                gateway,
                                "dev",
                                interface,
                                "onlink",
                                "table",
                                str(table),
                                "proto",
                                "static",
                            ],
                        )
                        self.network.command(
                            node,
                            [
                                "ip",
                                "rule",
                                "add",
                                "priority",
                                str(table),
                                "from",
                                src + "/32",
                                "to",
                                dst + "/32",
                                "table",
                                str(table),
                            ],
                        )
                self.action = action
                self.readback()
            except BaseException:
                self.close()
                raise
        return {
            "changed": changed,
            "path": list(PATHS[action]),
            "actual_action": action,
            "readback": self.readback(),
            "policy": self.network.policy,
            "strategy": "source-specific break-before-make; FRR main table in gap",
        }

    def close(self):
        for node, table, src, dst, interface, gateway in reversed(self.owned):
            rules, routes = self.inventory(node, table)
            for rule in rules:
                if not (
                    rule.get("priority") == table
                    and str(rule.get("table")) == str(table)
                    and rule.get("src") in (src, src + "/32")
                    and rule.get("dst") in (dst, dst + "/32")
                ):
                    raise RuntimeError("Refusing cleanup of foreign policy rule")
                self.network.command(
                    node,
                    [
                        "ip",
                        "rule",
                        "del",
                        "priority",
                        str(table),
                        "from",
                        src + "/32",
                        "to",
                        dst + "/32",
                        "table",
                        str(table),
                    ],
                )
            for route in routes:
                if not (
                    route.get("dst") in (dst, dst + "/32")
                    and route.get("dev") == interface
                    and route.get("gateway") == gateway
                    and route.get("protocol") == "static"
                ):
                    raise RuntimeError("Refusing cleanup of foreign policy route")
                self.network.command(
                    node,
                    [
                        "ip",
                        "route",
                        "del",
                        dst + "/32",
                        "via",
                        gateway,
                        "dev",
                        interface,
                        "table",
                        str(table),
                        "proto",
                        "static",
                    ],
                )
            if any(self.inventory(node, table)):
                raise RuntimeError("Foreground cleanup readback failed")
        self.owned.clear()
        self.action = None
        if self.original is not None:
            for source, destination in PAIRS:
                if (
                    self.network.routePath(source, destination)["nodes"]
                    != self.original[f"{source}->{destination}"]
                ):
                    raise RuntimeError("Original FRR forwarding not restored")
            self.original = None
