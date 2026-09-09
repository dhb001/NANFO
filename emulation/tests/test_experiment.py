import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from emulation.experiment import Experiment, SdnRouting, utilization, validate
from emulation.experiment_client import decode
from emulation.workloads import SCENARIOS, schedule


def request():
    return {"version": 1, "command": "reset", "episode_id": None, "step_index": None,
            "seed": 1000, "scenario": "path0", "action": None, "mode": "sdn",
            "window_seconds": 5, "episode_steps": 2}


class ExperimentTests(unittest.TestCase):
    def testValidation(self):
        validate(request())
        for key, value in (("version", True), ("window_seconds", float("nan")),
                           ("window_seconds", 1), ("window_seconds", 11), ("window_seconds", True),
                           ("episode_steps", 1), ("episode_steps", 65), ("episode_steps", True),
                           ("seed", -1), ("seed", True), ("scenario", "../x"), ("mode", "shell"),
                           ("episode_id", "../x"), ("episode_id", str(uuid.uuid4())),
                           ("action", 0), ("extra", "unsafe")):
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, TypeError)):
                validate({**request(), key: value})
        for raw in ('{"version":1,"version":1}', '{"x":NaN}', '{} {}'):
            with self.assertRaises(ValueError):
                decode(raw)

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
        self.assertFalse(routing.change(1)["changed"])
        routing.driver.verify.assert_called_once_with(routing.prepared)
        routing.driver.apply.assert_not_called()
        routing.driver.rollback.assert_not_called()

    def testOrderingAndFrozenConfiguration(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Experiment(SimpleNamespace(output=Path(directory)), routing=Mock())
            env.measure = Mock(return_value={"measured": True})
            self.assertTrue(env.handle(request())["ok"])
            self.assertFalse(env.handle(request())["ok"])
            step = {**request(), "command": "step", "episode_id": env.episode,
                    "step_index": 1, "action": 1}
            for change in ({"episode_id": str(uuid.uuid4())}, {"step_index": 2},
                           {"window_seconds": 3}, {"seed": 1001}, {"action": True}):
                self.assertFalse(env.handle({**step, **change})["ok"])
                self.assertEqual(env.index, 0)
            self.assertTrue(env.handle(step)["ok"])
            self.assertFalse(env.handle(step)["ok"])
            self.assertEqual(env.index, 1)
            self.assertFalse(env.handle({**step, "command": "close", "action": None,
                                         "episode_id": str(uuid.uuid4())})["ok"])

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


if __name__ == "__main__":
    unittest.main()
