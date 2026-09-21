import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from emulation.measurements import readJson
from emulation.runner import Lab, requireContainer


class RunnerTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("mininet"), "Mininet belongs in the image")
    def testPinnedMininetSkipsGlobalSysctls(self):
        from mininet.net import Mininet

        with patch.object(Mininet, "inited", True), patch("mininet.net.fixLimits") as limits:
            Mininet(build=False, controller=None)
        limits.assert_not_called()

    def testSnapshotExactTopLevelAndOmission(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Lab(Path(directory))
            lab.lastProbe = time.monotonic() - 100
            lab.probes = [{"stale": True}]
            with patch.object(
                lab, "controllerState", return_value={"switches": [], "links": [], "hosts": []}
            ):
                first = lab.snapshot(queues=[])
                second = lab.snapshot(queues=[])
            self.assertEqual(
                set(first),
                {
                    "version",
                    "topology_id",
                    "run_id",
                    "sequence",
                    "observed_at",
                    "switches",
                    "links",
                    "hosts",
                    "queues",
                    "probes",
                },
            )
            self.assertEqual(first["probes"], [])
            self.assertEqual(first["switches"], [])
            self.assertEqual(second["sequence"], first["sequence"] + 1)
            self.assertEqual(first["run_id"], second["run_id"])
            self.assertNotEqual(first["run_id"], Lab(Path(directory)).runId)
            self.assertEqual(readJson(Path(directory) / "snapshot.json"), second)

    def testContainerGuardFailsClosed(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            requireContainer()

    def testStaleOrMissingControllerDoesNotCreateCounters(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("emulation.runner.STATE", Path(directory)),
        ):
            self.assertEqual(
                Lab(Path(directory)).controllerState(), {"switches": [], "links": [], "hosts": []}
            )


if __name__ == "__main__":
    unittest.main()
