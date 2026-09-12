import copy
import json
import random
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from emulation.experiment import environmentSpec, pathPorts, utilization, validate
from emulation.matched import PAIRS, TABLES, MatchedRouting
from emulation.ospf import PATHS, ROUTER_IDS, ROUTERS, OSPFNetwork, linkPlan
from emulation.tests.test_experiment import request
from emulation.workloads import MATCHED_CAPACITIES, MATCHED_SCENARIOS, schedule


class MatchedTests(unittest.TestCase):
    def testStationaryPairedSchedulesAndVersion(self):
        for scenario, capacities in (("path0", [2, 20]), ("path1", [20, 2]), ("low", [20, 20])):
            phases = schedule(1000, scenario, 3, "matched")
            self.assertEqual(phases, schedule(1000, scenario, 3, "ospf"))
            self.assertTrue(all(p["path_capacity_mbps"] == capacities for p in phases))
            self.assertEqual(len({p["offered_mbps"] for p in phases}), 1)
            self.assertEqual(len({p["background_mbps"] for p in phases}), 1)
            self.assertEqual({p["background_path"] for p in phases}, {0})
        self.assertEqual(environmentSpec("matched"), environmentSpec("ospf"))
        self.assertEqual(environmentSpec("matched")[0]["version"], 5)
        self.assertEqual(environmentSpec("sdn")[0]["version"], 4)
        for mode in ("ospf", "matched"):
            validate({**request(), "mode": mode})
            for scenario in ("alternating", "burst", "anchor0", "anchor1"):
                with self.assertRaises(ValueError):
                    validate({**request(), "mode": mode, "scenario": scenario})

    def testIndependentProfileReplayAndAnchorCompatibility(self):
        spec = environmentSpec("matched")[0]
        self.assertEqual(spec["schedule_version"], "seeded-stationary-profiles-v5")
        self.assertEqual(list(spec["profiles"]), list(MATCHED_SCENARIOS))
        self.assertEqual(len(MATCHED_SCENARIOS), 9)
        for seed in (0, 1, 1000, 2147483647):
            for scenario, profile in spec["profiles"].items():
                rng = random.Random(seed)
                offered = round(rng.uniform(*profile["offered_mbps"]), 3)
                background = round(rng.uniform(*profile["background_mbps"]), 3)
                capacities = [None, None]
                for path in profile["capacity_draw_order"]:
                    choices = profile["path_capacity_mbps"][path]
                    capacities[path] = choices[0] if len(choices) == 1 else rng.choice(choices)
                expected = [
                    {
                        "phase_index": i,
                        "offered_mbps": offered,
                        "background_mbps": background,
                        "background_path": 0,
                        "path_capacity_mbps": capacities,
                    }
                    for i in range(65)
                ]
                for mode in ("matched", "ospf"):
                    self.assertEqual(schedule(seed, scenario, 64, mode), expected)
                    validate({**request(), "mode": mode, "scenario": scenario})
                if scenario in ("low", "path0", "path1"):
                    old = random.Random(seed)
                    self.assertEqual(offered, round(old.uniform(5.8, 6.2), 3))
                    self.assertEqual(background, round(old.uniform(1.8, 2.2), 3))
                elif scenario != "overload":
                    with self.assertRaises(ValueError):
                        validate({**request(), "scenario": scenario})
        for family in ("moderate", "severe"):
            a, b = [schedule(1000, family + str(i), 2, "matched")[0] for i in (0, 1)]
            self.assertEqual(a["path_capacity_mbps"], b["path_capacity_mbps"][::-1])
            self.assertEqual(a["offered_mbps"], b["offered_mbps"])
        phases = schedule(1000, "overload", 2, "matched")
        phases[0]["path_capacity_mbps"][0] = 999
        self.assertNotEqual(phases[0]["path_capacity_mbps"], phases[1]["path_capacity_mbps"])

    def testGoldenDrawsAndProfileRanges(self):
        expected = {
            "low": (6.111, 2.068, [20, 20]),
            "path0": (6.111, 2.068, [2, 20]),
            "path1": (6.111, 2.068, [20, 2]),
            "balanced": (4.555, 1.670, [20, 20]),
            "moderate0": (9.555, 2.340, [6, 20]),
            "moderate1": (9.555, 2.340, [20, 6]),
        }
        for scenario, values in expected.items():
            phase = schedule(1000, scenario, 2, "matched")[0]
            self.assertEqual(
                (phase["offered_mbps"], phase["background_mbps"], phase["path_capacity_mbps"]),
                values,
            )
        for seed in range(100):
            for scenario in MATCHED_SCENARIOS:
                phase = schedule(seed, scenario, 2, "matched")[0]
                if scenario.startswith("severe"):
                    low = int(scenario[-1])
                    self.assertIn(phase["path_capacity_mbps"][low], (3, 4, 5))
                    self.assertIn(phase["path_capacity_mbps"][1 - low], range(12, 21))
                    self.assertTrue(7 <= phase["offered_mbps"] <= 10)
                if scenario == "overload":
                    self.assertTrue(all(c in (6, 7, 8) for c in phase["path_capacity_mbps"]))
                    self.assertTrue(10 <= phase["offered_mbps"] <= 12)
                    self.assertTrue(2 <= phase["background_mbps"] <= 3)

    def testUtilizationUsesActualCapacity(self):
        before, after = {}, {}
        for ports in pathPorts():
            for node, port in ports:
                key = f"{node}-eth{port}"
                before[key] = {"monotonic_seconds": 1, "tx_bytes": 0}
                after[key] = {"monotonic_seconds": 2, "tx_bytes": 250000}
        self.assertEqual(utilization(before, after, [2, 20])[0], [1, 0.1])

    def testShapingReadbackAndHoldNeverReconfigures(self):
        network = OSPFNetwork()
        rates = {}

        def command(node, args):
            if "change" in args:
                rates[node, args[4]] = args[args.index("rate") + 1][:-4]
                return ""
            return f"class htb 5:1 root leaf 10: prio 0 rate {rates[node, args[-1]]}Mbit ceil {rates[node, args[-1]]}Mbit burst 15Kb cburst 1600b \n"

        with patch.object(network, "command", side_effect=command) as run:
            for capacity in MATCHED_CAPACITIES:
                readback = network.shape([capacity, 20])
                self.assertEqual([r["capacity_mbps"] for r in readback], [capacity] * 4 + [20] * 4)
                self.assertEqual(
                    {r["capacity_mbps"] for r in network.pathInterfaces(0)}, {capacity}
                )
            self.assertEqual(len(network.shape([2, 20])), 8)
            run.reset_mock()
            network.shape()
            self.assertTrue(all("change" not in c.args[1] for c in run.call_args_list))
            rates["access1", "access1-eth1"] = "20"
            with self.assertRaisesRegex(RuntimeError, "capacity"):
                network.shape()
        for bad in ([True, 20], [0, 20], [9, 20], [11, 20], [21, 20], [6.0, 20], [2], "2"):
            with self.assertRaises(ValueError):
                network.shape(bad)

    def testStationaryReadbackRejectsAdjacencyAndReverseBackgroundDrift(self):
        network = OSPFNetwork()
        neighbors = {
            name: {
                "neighbors": {
                    ROUTER_IDS[e["peer"]]: [{"state": "Full/-", "ifaceName": e["interface"]}]
                    for link in linkPlan()
                    for e in link["endpoints"]
                    if e["node"] == name and e["peer"] in ROUTERS
                }
            }
            for name in ROUTERS
        }
        network.vty = Mock(side_effect=lambda name, _: neighbors[name])

        def path(s, d):
            route = PATHS[1 if s in ("h1", "h3") else 0]
            return {"nodes": [s, *(route if s < d else reversed(route)), d]}

        network.routePath = Mock(side_effect=path)
        self.assertEqual(len(network.stationaryReadback(1)["paths"]), 4)
        network.routePath.side_effect = lambda s, d: {"nodes": []} if s == "h4" else path(s, d)
        with self.assertRaisesRegex(RuntimeError, "kernel path drift"):
            network.stationaryReadback(1)
        neighbors["core"] = {"neighbors": {}}
        with self.assertRaisesRegex(RuntimeError, "adjacency drift"):
            network.stationaryReadback(1)

    def routing(self):
        network = OSPFNetwork()
        lab = SimpleNamespace(network=network, checkController=Mock())
        routing = MatchedRouting(lab)
        rules, routes = {}, {}

        def command(node, args):
            if args[1:3] == ["-j", "rule"]:
                return json.dumps([r for (n, _), r in rules.items() if n == node])
            if args[1:3] == ["-j", "route"]:
                return json.dumps([r for (n, _), r in routes.items() if n == node])
            table = int(args[args.index("table") + 1])
            target = rules if args[1] == "rule" else routes
            if args[2] == "del":
                del target[node, table]
            elif args[1] == "rule":
                target[node, table] = {
                    "table": table,
                    "priority": table,
                    "src": args[args.index("from") + 1],
                    "dst": args[args.index("to") + 1],
                }
            else:
                target[node, table] = {
                    "table": table,
                    "dst": args[3],
                    "protocol": "static",
                    "dev": args[args.index("dev") + 1],
                    "gateway": args[args.index("via") + 1],
                }
            return ""

        def path(source, destination):
            action = routing.action if source in ("h1", "h3") and routing.action is not None else 0
            nodes = PATHS[action] if source < destination else tuple(reversed(PATHS[action]))
            return {"nodes": [source, *nodes, destination], "action": action}

        network.command = Mock(side_effect=command)
        network.routePath = Mock(side_effect=path)
        return routing, rules, routes

    def testWholeBidirectionalRouteHoldRestoreAndNoBackgroundMutation(self):
        routing, rules, routes = self.routing()
        for action in (0, 1, 0):
            result = routing.change(action)
            self.assertTrue(result["changed"])
            self.assertEqual(len(rules), 6)
            self.assertEqual(len(routes), 6)
            snapshot = copy.deepcopy((rules, routes))
            self.assertFalse(routing.change(action)["changed"])
            self.assertEqual(snapshot, (rules, routes))
            for rule in rules.values():
                self.assertEqual({rule["src"], rule["dst"]}, {"10.78.8.2/32", "10.78.10.2/32"})
        routing.close()
        routing.close()
        self.assertFalse(rules or routes)
        self.assertTrue(
            all("flush" not in c.args[1] for c in routing.network.command.call_args_list)
        )
        for pair in PAIRS:
            routing.network.routePath.assert_any_call(*pair)

    def testOccupiedTableAndForeignCleanupRefused(self):
        routing, rules, routes = self.routing()
        routes["core", TABLES[0]] = {"table": TABLES[0], "dst": "192.0.2.0/24"}
        with self.assertRaisesRegex(RuntimeError, "occupied"):
            routing.change(1)
        self.assertFalse(routing.owned)
        self.assertEqual(len(routes), 1)
        routes.clear()
        routing.change(1)
        rules["access1", TABLES[0]]["src"] = "192.0.2.1"
        with self.assertRaisesRegex(RuntimeError, "readback"):
            routing.change(1)
        with self.assertRaisesRegex(RuntimeError, "foreign"):
            routing.close()
        self.assertEqual(rules["access1", TABLES[0]]["src"], "192.0.2.1")

    def testPartialInstallFailureRestores(self):
        routing, rules, routes = self.routing()
        command = routing.network.command.side_effect

        def fail(node, args):
            if args[1:3] == ["rule", "add"]:
                raise RuntimeError("injected failure")
            return command(node, args)

        routing.network.command.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, "injected"):
            routing.change(1)
        self.assertFalse(rules or routes or routing.owned)
