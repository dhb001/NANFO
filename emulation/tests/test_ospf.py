import json
import os
import unittest
from unittest.mock import Mock, patch

from emulation.ospf import (
    HOSTS,
    LINKS,
    PATHS,
    ROUTER_IDS,
    ROUTERS,
    OSPFEnv,
    OSPFNetwork,
    fullNeighbors,
    linkPlan,
    routerConfig,
)


class OSPFTests(unittest.TestCase):
    def testPlanMatchesGraphAndShaping(self):
        plan = linkPlan()
        self.assertEqual(len(plan), 11)
        self.assertEqual(ROUTERS, ("core", "dist1", "dist2", "access1", "access2"))
        for index, (link, source) in enumerate(zip(plan, LINKS), 1):
            for key, value in source.items():
                self.assertEqual(link[key], value)
            self.assertEqual(link["subnet"], f"10.78.{index}.0/30")
            self.assertEqual([row["cidr"] for row in link["endpoints"]],
                             [f"10.78.{index}.1/30", f"10.78.{index}.2/30"])
        self.assertEqual([row["cost"] for row in plan],
                         [101, 102, 203, 504, 505, 506, 507, 108, 109, 110, 111])

    def testConfigUsesRealOspfAndExplicitSinglePathPolicy(self):
        self.assertEqual(len(set(ROUTER_IDS.values())), 5)
        for name in ROUTERS:
            config = routerConfig(name)
            self.assertIn(f"ospf router-id {ROUTER_IDS[name]}", config)
            self.assertIn("maximum-paths 1", config)
            self.assertIn("passive-interface default", config)
            self.assertNotIn("ip route ", config)
            for link in linkPlan():
                for endpoint in link["endpoints"]:
                    if endpoint["node"] != name:
                        continue
                    self.assertIn(f"interface {endpoint['interface']}\n", config)
                    self.assertIn(f" ip ospf cost {link['cost']}\n", config)
                    self.assertEqual(f" no passive-interface {endpoint['interface']}\n" in config,
                                     endpoint["peer"] in ROUTERS)
        with self.assertRaises(ValueError):
            routerConfig("h1")

    def testUnequalCostTiePolicySelectsDist1OnBothDirections(self):
        costs = {frozenset((link["a"][0], link["b"][0])): link["cost"] for link in linkPlan()}
        totals = [sum(costs[frozenset(pair)] for pair in zip(path, path[1:])) for path in PATHS]
        self.assertEqual(totals, [1010, 1012])
        self.assertLess(totals[0], totals[1])

    def testHostAndMeasurementInterfaceContract(self):
        env = OSPFEnv()
        self.assertIs(OSPFEnv, OSPFNetwork)
        self.assertEqual(env.hostAddresses, {f"h{i}": f"10.78.{i+7}.2" for i in range(1, 5)})
        for index, host in enumerate(HOSTS, 8):
            self.assertEqual(env.hosts[host["name"]]["gateway"], f"10.78.{index}.1")
        for action in (0, 1):
            interfaces = env.pathInterfaces(action)
            self.assertEqual(len(interfaces), 4)
            self.assertEqual({row["capacity_mbps"] for row in interfaces}, {20})
            self.assertEqual({row["node"] for row in interfaces}, set(PATHS[action]))
        for bad in (True, 2, -1, "0"):
            with self.assertRaises(ValueError):
                env.pathInterfaces(bad)
        with self.assertRaises(RuntimeError):
            env.get("core")
        env.close()
        env.close()

    def testNeighborsRequireExactFullPeersAndInterfaces(self):
        value = {ROUTER_IDS["dist1"]: [{"nbrState": "Full/-", "ifaceName": "core-eth1:10.78.1.1"}],
                 ROUTER_IDS["dist2"]: [{"nbrState": "Full/-", "ifaceName": "core-eth2:10.78.2.1"}]}
        self.assertTrue(fullNeighbors(value, "core"))
        value[ROUTER_IDS["dist2"]][0]["nbrState"] = "ExStart/-"
        self.assertFalse(fullNeighbors(value, "core"))
        self.assertFalse(fullNeighbors({}, "core"))
        self.assertFalse(fullNeighbors([], "core"))

    def testRoutePathUsesKernelAndRejectsLoopAndUntrustedGateway(self):
        env = OSPFEnv()
        routes = {
            "h1": {"dev": "h1-eth0", "gateway": "10.78.8.1"},
            "access1": {"dev": "access1-eth1", "gateway": "10.78.4.1"},
            "dist1": {"dev": "dist1-eth4", "gateway": "10.78.6.2"},
            "access2": {"dev": "access2-eth3"},
        }
        with patch.object(env, "command", side_effect=lambda name, args: json.dumps([routes[name]])):
            self.assertEqual(env.routePath()["nodes"], ["h1", "access1", "dist1", "access2", "h3"])
            self.assertEqual(env.routePath()["action"], 0)
            routes["dist1"] = {"dev": "dist1-eth3", "gateway": "10.78.4.2"}
            with self.assertRaisesRegex(RuntimeError, "loop"):
                env.routePath()
            routes["access1"]["gateway"] = "192.0.2.1"
            with self.assertRaisesRegex(RuntimeError, "gateway"):
                env.routePath()

    def testHostGuardRunsBeforeMininetImportOrMutation(self):
        env = OSPFEnv()
        with patch("emulation.ospf.requireContainer", side_effect=RuntimeError("isolated")), \
                self.assertRaisesRegex(RuntimeError, "isolated"):
            env.start()
        self.assertIsNone(env.net)
        self.assertIsNone(env.directory)

    def testRejectsManualControl(self):
        with patch("emulation.ospf.requireContainer"), \
                patch.dict(os.environ, {"EMULATION_CONTROL_ENABLED": "true"}), \
                self.assertRaisesRegex(RuntimeError, "manual"):
            OSPFEnv().start()

    def testCommandTimeoutStopsOwnedChild(self):
        import subprocess

        env = OSPFEnv()
        process = Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("ip", 5)
        with patch.object(env, "get", return_value=Mock(popen=Mock(return_value=process))), \
                patch("emulation.ospf.stopProcess") as stop, \
                self.assertRaises(subprocess.TimeoutExpired):
            env.command("core", ["ip", "-j", "route"])
        stop.assert_called_once_with(process)


@unittest.skipUnless(os.environ.get("NANFO_OSPF_LIVE") == "1", "Opt-in isolated FRR live gate")
class OSPFLiveTests(unittest.TestCase):
    def testRealAdjacenciesKernelRoutesAndPackets(self):
        network = OSPFNetwork()
        try:
            network.start()
            result = network.verify()
            self.assertEqual(result["full_directed_adjacencies"], 14)
            self.assertEqual(result["ping_sent"], 36)
            self.assertEqual(result["ping_received"], 36)
            self.assertEqual(result["paths"]["h1->h3"]["action"], 0)
            self.assertEqual(result["paths"]["h2->h4"]["action"], 0)
            self.assertEqual(len(result["counters"]), 18)
            self.assertEqual(len(result["queues"]), 18)
            self.assertTrue(all(row["queue"] is not None for row in result["queues"]))
        finally:
            network.close()


if __name__ == "__main__":
    unittest.main()
