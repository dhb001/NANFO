"""Fake kernel for FRR driver decisions/readback; no network or subprocess use."""

import copy
import json

from emulation.autonomous_frr import PAIRS, PATHS, TABLES
from emulation.ospf import OSPFNetwork


class FakeFRRNetwork(OSPFNetwork):
    def __init__(self):
        super().__init__()
        self.rules, self.routes, self.writes = {}, {}, []
        self.fail_after = None

    def mutate(self, node, args, checkpoint, timeout=5):
        checkpoint()
        return self.command(node, args, timeout)

    def command(self, node, args, timeout=5):
        if args == ["ip", "-j", "rule", "show"]:
            return json.dumps([r for (n, _), rows in self.rules.items() if n == node for r in rows])
        if args == ["ip", "-j", "route", "show", "table", "all"]:
            return json.dumps([r for (n, _), rows in self.routes.items() if n == node for r in rows])
        if args[0] == "ping":
            return "3 packets transmitted, 3 received, 0% packet loss, time 200ms\nrtt min/avg/max/mdev = 1.0/1.0/1.0/0.0 ms"
        kind, op = args[1:3]
        table = int(args[args.index("table") + 1])
        key = node, table
        if kind == "route":
            row = dict(dst=args[3], gateway=args[args.index("via") + 1], dev=args[args.index("dev") + 1],
                       table=table, protocol="static", flags=["onlink"])
            store = self.routes
        else:
            row = dict(priority=int(args[args.index("priority") + 1]), src=args[args.index("from") + 1],
                       dst=args[args.index("to") + 1], table=table)
            store = self.rules
        if op == "add":
            assert not store.get(key)
            store[key] = [row]
        elif op == "del":
            assert store.get(key) == [row]
            store[key] = []
        else:
            raise AssertionError(args)
        self.writes.append((node, copy.deepcopy(args)))
        if self.fail_after == len(self.writes):
            raise RuntimeError("timeout_after_kernel_acceptance")
        return ""

    def routePath(self, source, destination):
        index = PAIRS.index((source, destination))
        if index < 2:
            table = TABLES[index]
            dist2 = self.rules.get(("dist2", table)) and self.routes.get(("dist2", table))
            path = PATHS[int(bool(dist2))]
        else:
            path = PATHS[0]
        return {"nodes": [source, *(path if source in ("h1", "h2") else reversed(path)), destination]}


async def allow_dispatch(_):
    return None
