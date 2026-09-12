import copy
import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from emulation.experiment import (
    Experiment,
    OspfRouting,
    SdnRouting,
    counters,
    drainQueues,
    environmentSpec,
    measurementOutcome,
    utilization,
    validate,
)
from emulation.experiment_client import decode
from emulation.measurements import atomicJson
from emulation.workloads import SCENARIOS, schedule


def request():
    return {
        "version": 1,
        "command": "reset",
        "episode_id": None,
        "step_index": None,
        "seed": 1000,
        "scenario": "path0",
        "action": None,
        "mode": "sdn",
        "window_seconds": 5,
        "episode_steps": 2,
    }


class ExperimentTests(unittest.TestCase):
    def testEnvironmentSpecHashesActualSourcesAndSemantics(self):
        spec, digest = environmentSpec()
        self.assertEqual(spec["version"], 4)
        self.assertNotIn("drain_seconds", spec)
        self.assertEqual((spec, digest), environmentSpec())
        self.assertEqual(
            digest,
            hashlib.sha256(
                json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        self.assertEqual(
            spec["source_files"]["workloads.py"],
            hashlib.sha256(Path("emulation/workloads.py").read_bytes()).hexdigest(),
        )
        with patch("emulation.experiment.Path.read_bytes", return_value=b"changed"):
            changed, changedHash = environmentSpec()
        self.assertNotEqual(digest, changedHash)
        self.assertNotEqual(spec["source_sha256"], changed["source_sha256"])

    def testMeasuredRateOutageAndMissingEvidence(self):
        worker = {
            "packets": 1000,
            "bytes": 1200000,
            "highest_sequence": 999,
            "duration_seconds": 3.0,
            "started_monotonic_seconds": 1.0,
            "finished_monotonic_seconds": 4.0,
        }
        observation = {
            "offered_mbps": 3.5,
            "background_mbps": 3.5,
            "path_utilization": [0.2, 0.3],
            "path_queue_packets": [0, 1],
        }
        evidence = {
            "drain_status": "verified_empty",
            "drain_begin": 4.0,
            "drain_end": 4.2,
            "udp_sent": [dict(worker), dict(worker)],
            "udp_received": [dict(worker), dict(worker)],
            "post_control_interval": {"start": 1.5, "end": 3.5},
            "desired_window_seconds": 2,
            "measured_window_seconds": 2,
            "ping": {"sent": 10, "received": 10, "rtt_avg_ms": 24, "interval_seconds": 2.5},
            "queue_peaks": {str(i): {} for i in range(8)},
            "counter_windows": {str(i): {"duration_seconds": 3} for i in range(8)},
        }
        for receiver in evidence["udp_received"]:
            receiver.update(duration_seconds=3.3, finished_monotonic_seconds=4.3)
        normal = copy.deepcopy(evidence)
        measurementOutcome(observation, normal, 1.2)
        self.assertEqual(observation["actual_offered_mbps"], 3.2)
        self.assertEqual(observation["goodput_mbps"] / observation["actual_offered_mbps"], 1)
        self.assertFalse(normal["service_outage"])
        self.assertIsNone(normal["latency_timeout_ms"])
        outage = copy.deepcopy(evidence)
        outage["ping"].update(received=0, rtt_avg_ms=None)
        outage["udp_received"][0].update(packets=0, bytes=0, highest_sequence=-1)
        measurementOutcome(observation, outage, 1.2)
        self.assertTrue(outage["service_outage"])
        self.assertTrue(outage["latency_censored"])
        self.assertEqual(outage["latency_timeout_ms"], 1000)
        self.assertIsNone(observation["latency_ms"])
        self.assertEqual(observation["goodput_mbps"], 0)
        self.assertEqual(observation["loss_fraction"], 1)
        for key, value in (
            ("ping", None),
            ("measured_window_seconds", 0),
            ("counter_windows", {}),
            ("queue_peaks", {}),
        ):
            invalid = {**copy.deepcopy(evidence), key: value}
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                measurementOutcome(observation, invalid, 1.2)
        for field, value in (
            ("duration_seconds", 0),
            ("bytes", 0),
            ("started_monotonic_seconds", 2),
        ):
            invalid = copy.deepcopy(evidence)
            invalid["udp_sent"][0][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                measurementOutcome(observation, invalid, 1.2)
        invalid = copy.deepcopy(evidence)
        invalid["ping"].update(sent=0, received=0, rtt_avg_ms=None)
        with self.assertRaises(RuntimeError):
            measurementOutcome(observation, invalid, 1.2)
        for change in (
            {"drain_status": "timeout", "drain_error": "drain cap exceeded"},
            {"drain_begin": 3.9},
            {"drain_end": 4.4},
            {"drain_status": "unverified", "drain_error": "missing leaf"},
        ):
            invalid = {**copy.deepcopy(evidence), **change}
            unmeasured = {**observation, "goodput_mbps": None, "loss_fraction": None}
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                measurementOutcome(unmeasured, invalid, 1.2)
            self.assertIsNone(unmeasured["goodput_mbps"])
            self.assertIsNone(unmeasured["loss_fraction"])
            self.assertEqual(invalid["udp_received"], evidence["udp_received"])

    def testValidation(self):
        validate(request())
        for key, value in (
            ("version", True),
            ("window_seconds", float("nan")),
            ("window_seconds", 1),
            ("window_seconds", 11),
            ("window_seconds", True),
            ("episode_steps", 1),
            ("episode_steps", 65),
            ("episode_steps", True),
            ("seed", -1),
            ("seed", True),
            ("scenario", "../x"),
            ("mode", "shell"),
            ("episode_id", "../x"),
            ("episode_id", str(uuid.uuid4())),
            ("action", 0),
            ("extra", "unsafe"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, TypeError)):
                validate({**request(), key: value})
        for raw in ('{"version":1,"version":1}', '{"x":NaN}', '{"x":1e999}', "{} {}", "[" * 2000):
            with self.assertRaises(ValueError):
                decode(raw)

    def testDrainRequiresTwoCompleteTimedEmptySweepsAcrossAllLinks(self):
        self.checkDrain([0, 0], "verified_empty", 2)

    def testDrainWaitsForNonemptyQueueAndRestartsEmptySequence(self):
        self.checkDrain([1, 0, 1, 0, 0], "verified_empty", 5)

    def testDrainNonemptyTimeoutRetainsRawBacklog(self):
        evidence = self.checkDrain([1], "timeout")
        self.assertTrue(all(q["backlog_packets"] == 1 for q in evidence["queue_end"].values()))
        self.assertEqual(evidence["drain_empty_observations"], [])

    def testDrainMissingQueueIsNotEmpty(self):
        self.checkDrain([None], "unverified", 0)

    def testDrainReceiverExitIsNotSuccess(self):
        self.checkDrain([0], "unverified", 0, receiverExited=True)

    def testDrainQueueTimeoutStopsOwnedChild(self):
        self.checkDrain([0], "timeout", 0, queueTimeout=True)

    def checkDrain(self, backlogs, status, sweeps=None, receiverExited=False, queueTimeout=False):
        from emulation.topology import LINKS

        clock = [10.0]
        calls = []
        processes = []
        interfaces = {
            f"{node}-eth{port}" for link in LINKS for node, port in (link["a"], link["b"])
        }

        def sleep(seconds):
            clock[0] += seconds

        def spawn(args, **kwargs):
            backlog = backlogs[min(len(calls) // len(interfaces), len(backlogs) - 1)]
            calls.append(args[-1])
            process = Mock(returncode=0)

            def communicate(timeout):
                if queueTimeout:
                    sleep(timeout)
                    raise subprocess.TimeoutExpired("tc", timeout)
                sleep(0.001)
                return json.dumps(
                    [
                        {
                            "kind": "netem",
                            "handle": "10:",
                            "parent": "5:1",
                            "backlog": backlog,
                            "qlen": backlog,
                        }
                    ]
                ), b""

            process.communicate.side_effect = communicate
            processes.append(process)
            return process

        lab = SimpleNamespace(
            net={node: Mock(popen=spawn) for link in LINKS for node, _ in (link["a"], link["b"])},
            checkController=Mock(),
        )
        receivers = [Mock(poll=Mock(return_value=0 if receiverExited else None)) for _ in range(2)]
        evidence = {"environment_spec": environmentSpec()[0]}
        with (
            patch("emulation.experiment.time.monotonic", side_effect=lambda: clock[0]),
            patch("emulation.experiment.time.sleep", side_effect=sleep),
            patch("emulation.experiment.stopProcess") as stop,
        ):
            # Use the cap itself for the forced timeout so it cannot be mistaken for emptiness.
            if queueTimeout:
                evidence["environment_spec"]["drain_max_seconds"] = 1.0
            drainQueues(lab, receivers, evidence)
        self.assertEqual(evidence["drain_status"], status)
        self.assertEqual(stop.call_count, len(processes))
        if sweeps is not None:
            self.assertEqual(evidence["drain_sweeps"], sweeps)
        self.assertEqual(evidence["late_received_packets"], [None, None])
        self.assertEqual(set(evidence["drain_queue_interfaces"]), interfaces)
        self.assertLessEqual(
            evidence["drain_duration_seconds"], evidence["environment_spec"]["drain_max_seconds"]
        )
        if status == "verified_empty":
            a, b = evidence["drain_empty_observations"]
            self.assertGreaterEqual(b["start"] - a["end"], 0.08 - 1e-12)
            self.assertEqual(set(a["queues"]), interfaces)
            self.assertEqual(set(b["queues"]), interfaces)
            self.assertEqual(evidence["queue_end"], b["queues"])
            self.assertEqual(set(calls), interfaces)
        else:
            self.assertIsNotNone(evidence["drain_error"])
        for receiver in receivers:
            receiver.send_signal.assert_not_called()
        return evidence

    def testSchedule(self):
        for scenario in SCENARIOS:
            first = schedule(1000, scenario, 64)
            self.assertEqual(len(first), 65)
            self.assertEqual(first, schedule(1000, scenario, 64))
            self.assertNotEqual(first, schedule(1001, scenario, 64))
            self.assertTrue(all(0 < p["offered_mbps"] <= 30 for p in first))
        self.assertEqual([p["background_path"] for p in schedule(1, "alternating", 2)], [0, 1, 0])

    def testMissingCountersAreNull(self):
        self.assertEqual(utilization({}, {})[0], [None, None])

    def testHoldDoesNotReinstall(self):
        routing = SdnRouting(Mock())
        routing.action = 1
        routing.prepared = {"prepared": True}
        routing.driver = Mock()
        routing.driver.verify.return_value = {"switches": {}}
        self.assertFalse(routing.change(1)["changed"])
        routing.driver.verify.assert_called_once_with(routing.prepared)
        routing.driver.apply.assert_not_called()
        routing.driver.rollback.assert_not_called()

    def testHeldFixtureStillRefreshesRealHostDiscovery(self):
        lab = Mock()
        routing = SdnRouting(lab)
        routing.fixturePath = 0
        routing.driver = Mock()
        routing.fixture(0)
        lab.probe.assert_called_once_with()
        lab.ready.assert_called_once_with(lab.controllerState.return_value)
        routing.driver.of.assert_not_called()

    def testOspfReportsActualPassiveChangesNotRequestedActions(self):
        lab = Mock()
        lab.network.routePath.return_value = {
            "nodes": ["h1", "access1", "dist1", "access2", "h3"],
            "action": 0,
        }
        routing = OspfRouting(lab)
        self.assertTrue(routing.change(1)["changed"])
        held = routing.change(1)
        self.assertFalse(held["changed"])
        self.assertEqual(held["actual_action"], 0)
        lab.network.routePath.return_value = {
            "nodes": ["h1", "access1", "dist2", "access2", "h3"],
            "action": 1,
        }
        changed = routing.change(0)
        self.assertTrue(changed["changed"])
        self.assertEqual(changed["actual_action"], 1)

    def testOrderingAndFrozenConfiguration(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Experiment(SimpleNamespace(output=Path(directory)), routing=Mock())
            env.measure = Mock(return_value={"measured": True})
            self.assertTrue(env.handle(request())["ok"])
            self.assertFalse(env.handle(request())["ok"])
            step = {
                **request(),
                "command": "step",
                "episode_id": env.episode,
                "step_index": 1,
                "action": 1,
            }
            for change in (
                {"episode_id": str(uuid.uuid4())},
                {"step_index": 2},
                {"window_seconds": 3},
                {"seed": 1001},
                {"action": True},
            ):
                self.assertFalse(env.handle({**step, **change})["ok"])
                self.assertEqual(env.index, 0)
            self.assertTrue(env.handle(step)["ok"])
            calls = env.measure.call_count
            self.assertFalse(env.handle(step)["ok"])
            self.assertEqual(env.measure.call_count, calls)
            self.assertFalse(env.handle({**step, "action": 0})["ok"])
            self.assertEqual(env.index, 1)
            self.assertFalse(
                env.handle(
                    {**step, "command": "close", "action": None, "episode_id": str(uuid.uuid4())}
                )["ok"]
            )

    def testConfigIsNotAliasedToCachedCallerRequest(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Experiment(SimpleNamespace(output=Path(directory)), routing=Mock())
            env.measure = Mock(return_value={})
            cached = request()
            self.assertTrue(env.handle(cached)["ok"])
            cached["seed"] += 1
            self.assertEqual(env.config["seed"], 1000)

    def testCounterTimeoutStopsChild(self):
        import subprocess

        process = Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("ip", 2)
        lab = SimpleNamespace(net={"access1": Mock(popen=Mock(return_value=process))})
        with patch("emulation.experiment.stopProcess") as stop:
            with self.assertRaises(subprocess.TimeoutExpired):
                counters(lab)
            stop.assert_called_once_with(process)

    def testCloseIdentityAndResetAfterTermination(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = SimpleNamespace(output=Path(directory))
            routing = Mock()
            env = Experiment(lab, routing=routing)
            env.measure = Mock(return_value={})
            env.handle(request())
            first = env.episode
            env.done = True
            self.assertTrue(env.handle(request())["ok"])
            self.assertNotEqual(first, env.episode)
            close = {**request(), "command": "close", "episode_id": env.episode, "step_index": 0}
            self.assertFalse(env.handle({**close, "episode_id": first})["ok"])
            self.assertTrue(env.handle(close)["data"]["cleanup_verified"])
            self.assertTrue(env.closed)
            self.assertFalse(env.handle(request())["ok"])

    def testFailureTruncatesWithoutFakeMeasurements(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = SimpleNamespace(output=Path(directory), processes=[], stopping=False)
            routing = Mock()
            routing.fixture.side_effect = RuntimeError("fixture failed")
            env = Experiment(lab, routing=routing)
            result = env.handle(request())
            self.assertTrue(result["ok"])
            data = result["data"]
            self.assertTrue(data["truncated"])
            self.assertFalse(data["evidence"]["measurement_complete"])
            self.assertIsNone(data["observation"]["actual_offered_mbps"])
            self.assertIsNone(data["evidence"]["service_outage"])
            self.assertFalse(data["terminated"])
            self.assertIsNone(data["observation"]["goodput_mbps"])
            self.assertIsNone(data["observation"]["loss_fraction"])
            self.assertEqual(data["observation"]["path_utilization"], [None, None])
            self.assertTrue(data["evidence"]["cleanup_verified"])

    def testUnsafeCleanupStopsOwner(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = SimpleNamespace(output=Path(directory), processes=[], stopping=False)
            routing = Mock()
            routing.close.side_effect = RuntimeError("uncertain")
            env = Experiment(lab, routing=routing)
            self.assertFalse(env.handle(request())["ok"])
            self.assertTrue(lab.stopping)


@unittest.skipUnless(os.environ.get("NANFO_EXPERIMENT_LIVE") == "1", "Opt-in owned SDN fault gate")
class ExperimentLiveTests(unittest.TestCase):
    def testLostReadbackTruncatesAndResetRecovers(self):
        argv = [
            "docker",
            "exec",
            "-i",
            "nanfo-experiment",
            "python",
            "-m",
            "emulation.experiment_client",
        ]
        trace = []

        def exchange(value):
            result = subprocess.run(
                argv, input=json.dumps(value), text=True, capture_output=True, timeout=65
            )
            response = decode(result.stdout)
            trace.append({"request": dict(value), "response": response})
            return response

        value = request()
        value.update(scenario="low", window_seconds=2)
        data = None
        try:
            for raw in ('{"version":1,"version":1}', '{"x":1e999}', "[" * 2000, "x" * 4097):
                result = subprocess.run(argv, input=raw, text=True, capture_output=True, timeout=65)
                rejected = decode(result.stdout)
                trace.append({"invalid_request": raw[:100], "response": rejected})
                self.assertFalse(rejected["ok"])
            data = exchange(value)["data"]
            self.assertFalse(data["truncated"])
            value.update(command="step", episode_id=data["episode_id"], step_index=1, action=0)
            with subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as process:
                process.stdin.write(json.dumps(value))
                process.stdin.close()
                process.stdin = None
                time.sleep(1)
                # Fault only the route owned by this disposable experiment, during load.
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "nanfo-experiment",
                        "ovs-ofctl",
                        "-O",
                        "OpenFlow13",
                        "del-flows",
                        "access1",
                        "cookie=0x4e414e4600000001/-1,table=0",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=5,
                )
                result = decode(process.communicate(timeout=65)[0])
            trace.append({"request": dict(value), "response": result})
            self.assertTrue(result["ok"])
            data = result["data"]
            self.assertTrue(data["truncated"])
            self.assertFalse(data["terminated"])
            self.assertIn("readback", data["evidence"]["error"].lower())
            self.assertTrue(data["evidence"]["cleanup_verified"])
            self.assertIsNone(data["observation"]["goodput_mbps"])
            self.assertIsNone(data["observation"]["loss_fraction"])
            value.update(command="reset", episode_id=None, step_index=None, action=None)
            data = exchange(value)["data"]
            self.assertFalse(data["truncated"])
        finally:
            if data is not None:
                value.update(
                    command="close",
                    episode_id=data["episode_id"],
                    step_index=data["step_index"],
                    action=None,
                )
                self.assertTrue(exchange(value)["data"]["cleanup_verified"])
            atomicJson(Path("emulation/output/experiment-fault-trace.json"), trace)


if __name__ == "__main__":
    unittest.main()
