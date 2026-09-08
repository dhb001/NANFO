import json
import tempfile
import unittest
from pathlib import Path

from emulation.measurements import (
    MAX_BYTES,
    MultipartReplies,
    atomicJson,
    parsePing,
    parseQueue,
    readJson,
)
from emulation.topology import (
    HOSTS,
    LINKS,
    SWITCHES,
    expectedLinks,
    manifest,
    nextPort,
    portCapacities,
)


class TopologyTests(unittest.TestCase):
    def testCampusAndUniquePorts(self):
        self.assertEqual(len(SWITCHES), 5)
        self.assertEqual(len(HOSTS), 4)
        endpoints = [link[side] for link in LINKS for side in ("a", "b")]
        self.assertEqual(len(endpoints), len(set(endpoints)))
        self.assertEqual(len(expectedLinks()), 14)
        self.assertEqual(len(portCapacities()), 18)
        for link in LINKS:
            self.assertGreater(link["capacity_mbps"], 0)
            self.assertGreater(link["delay_ms"], 0)
            self.assertGreater(link["max_queue_size"], 0)
        for switch in SWITCHES:
            self.assertRegex(switch["dpid"], r"^[0-9a-f]{16}$")

    def testManifestDetachedAndSerializable(self):
        result = manifest()
        json.dumps(result)
        result["switches"][0]["name"] = "changed"
        self.assertEqual(manifest()["switches"][0]["name"], "core")

    def testObservedPathsLoopFreeAndRedundant(self):
        links = [
            dict(zip(("src_dpid", "src_port", "dst_dpid", "dst_port"), link))
            for link in expectedLinks()
        ]
        for removed in (None, ("0000000000000002", "0000000000000004")):
            available = [
                link
                for link in links
                if removed is None or {link["src_dpid"], link["dst_dpid"]} != set(removed)
            ]
            for source in SWITCHES:
                for target in SWITCHES:
                    current, seen = source["dpid"], set()
                    while current != target["dpid"]:
                        self.assertNotIn(current, seen)
                        seen.add(current)
                        port = nextPort(current, target["dpid"], available)
                        self.assertIsNotNone(port)
                        current = next(
                            link["dst_dpid"]
                            for link in available
                            if link["src_dpid"] == current and link["src_port"] == port
                        )
        self.assertIsNone(nextPort(SWITCHES[0]["dpid"], SWITCHES[1]["dpid"], []))
        self.assertIsNone(nextPort(links[0]["src_dpid"], links[0]["dst_dpid"], [links[0]]))


class MeasurementTests(unittest.TestCase):
    def testLeafQueueNotDoubleCounted(self):
        rows = [
            {"kind": "htb", "handle": "5:", "backlog": 900, "qlen": 3},
            {"kind": "netem", "handle": "10:", "parent": "5:1", "backlog": 900, "qlen": 3},
        ]
        self.assertEqual(parseQueue(json.dumps(rows)), {"backlog_bytes": 900, "backlog_packets": 3})
        rows[1]["backlog"] = 0
        rows[1]["qlen"] = 0
        self.assertEqual(parseQueue(json.dumps(rows)), {"backlog_bytes": 0, "backlog_packets": 0})

    def testUnavailableQueueIsNotZero(self):
        for value in (
            "invalid",
            "{}",
            "[]",
            '[{"kind":"htb","backlog":0,"qlen":0}]',
            '[{"kind":"netem"}]',
            '[{"kind":"netem","backlog":-1,"qlen":0}]',
            '[{"kind":"netem","backlog":true,"qlen":0}]',
        ):
            self.assertIsNone(parseQueue(value))

    def testPingObservations(self):
        text = "2 packets transmitted, 2 received, 0% packet loss\nrtt min/avg/max/mdev = 1.2/2.3/3.4/0.1 ms"
        result = parsePing(text, "h1", "h3", 1.2, "2026-09-08T12:00:00Z")
        self.assertEqual(result["rtt_avg_ms"], 2.3)
        self.assertEqual(result["received"], 2)
        self.assertIsNone(parsePing("ping failed", "h1", "h3", 1, "now"))
        self.assertIsNone(parsePing(text, "h1", "h3", 0, "now"))
        result = parsePing("2 packets transmitted, 0 received", "h1", "h3", 2, "now")
        self.assertIsNone(result["rtt_avg_ms"])

    def testAtomicBoundedPublication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            atomicJson(path, {"sequence": 0})
            atomicJson(path, {"sequence": 1})
            self.assertEqual(readJson(path), {"sequence": 1})
            with self.assertRaises(ValueError):
                atomicJson(path, "x" * MAX_BYTES)
            with self.assertRaises(ValueError):
                atomicJson(path, float("nan"))
            self.assertEqual(readJson(path), {"sequence": 1})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def testMultipartRequiresBothCompleteReplies(self):
        replies = MultipartReplies()
        replies.begin("1", 10, 11, 0)
        replies.receive("1", "ports", 99, [{"wrong": True}], False, "ignored", 1)
        replies.receive("1", "ports", 10, [{"port_no": 1}], True, "first", 1)
        replies.receive("1", "flows", 11, [], False, "second", 2)
        self.assertEqual(replies.samples(2), [])
        replies.receive("1", "ports", 10, [{"port_no": 2}], False, "actual-reply-time", 3)
        result = replies.samples(3)[0]
        self.assertEqual(result["observed_at"], "actual-reply-time")
        self.assertEqual(result["ports"], [{"port_no": 1}, {"port_no": 2}])
        self.assertEqual(replies.samples(10), [])

    def testMultipartTimeoutAndBounds(self):
        replies = MultipartReplies()
        replies.begin("1", 1, 2, 0)
        replies.receive("1", "ports", 1, [], False, "late", 6)
        replies.receive("1", "flows", 2, [], False, "late", 6)
        self.assertEqual(replies.samples(6), [])
        replies.begin("1", 3, 4, 7)
        replies.receive("1", "ports", 3, [{}] * 129, False, "oversized", 8)
        self.assertNotIn("1", replies.pending)


if __name__ == "__main__":
    unittest.main()
