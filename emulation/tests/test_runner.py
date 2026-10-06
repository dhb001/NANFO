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

    def testControlRequestErrorsAreScopedToTheirConnection(self):
        import socket
        from types import SimpleNamespace
        from unittest.mock import Mock

        from emulation import runner

        lab = SimpleNamespace(
            verify=Mock(side_effect=RuntimeError("iperf3 client/server failed")),
            ready=Mock(return_value=True),
            controllerState=Mock(return_value={}),
            runId="run",
            sequence=3,
            close=Mock(),
        )
        connection = Mock()
        connection.recv.return_value = b"smoke\n"
        with patch("sys.stderr"):
            self.assertEqual(
                runner.answer(lab, connection),
                {"passed": False, "error": "RuntimeError: iperf3 client/server failed"},
            )
            connection.recv.side_effect = socket.timeout("timed out")
            self.assertEqual(runner.answer(lab, connection)["error"], "TimeoutError: timed out")
        lab.close.assert_not_called()
        connection.recv.side_effect = None
        connection.recv.return_value = b"status\n"
        self.assertEqual(runner.answer(lab, connection), {"passed": True, "run_id": "run", "sequence": 3})
        connection.recv.return_value = b"rm -rf /\n"
        self.assertEqual(runner.answer(lab, connection)["error"], "Unknown command")

    def testHealthcheckRequestStatusInterfaceIsStable(self):
        """compose.lab*.yaml healthcheck: `python -m emulation.runner --request status`."""
        import json
        import socket
        import sys
        import threading

        from emulation import runner

        with patch.object(sys, "argv", ["runner", "--request", "status"]), \
                patch.object(runner, "request", return_value=0) as request, \
                patch.object(runner, "requireContainer") as guard:
            self.assertEqual(runner.main(), 0)
        request.assert_called_once_with("status")
        guard.assert_not_called()  # a probe never starts or validates a lab
        for passed, code in ((True, 0), (False, 1)):
            with tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / "control.sock")
                received = []
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(path)
                    server.listen(1)

                    def serve(server=server, received=received, passed=passed):
                        connection, _ = server.accept()
                        with connection:
                            received.append(connection.recv(32))
                            connection.sendall(json.dumps({"passed": passed, "run_id": "r"}).encode())

                    thread = threading.Thread(target=serve)
                    thread.start()
                    with patch.object(runner, "SOCKET", path), patch("builtins.print"):
                        self.assertEqual(runner.request("status"), code)
                    thread.join(2)
                self.assertEqual(received, [b"status\n"])

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
