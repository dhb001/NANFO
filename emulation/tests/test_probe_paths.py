"""Deterministic packet fixtures, not producer self-attested path success."""

import copy
import socket
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from emulation.probe_paths import (
    CaptureInterrupted,
    captureInterfaces,
    capturePaths,
    checksum,
    decodePcap,
    observedPaths,
    probePayload,
)

WINDOW = "01800000-0000-4000-8000-000000000001"
IDENTIFIER = 18018
SECONDS = 1789041600


def ethernetPacket(sequence=1, window=WINDOW, identifier=IDENTIFIER):
    payload = probePayload(window, sequence)
    icmp = struct.pack("!BBHHH", 8, 0, 0, identifier, sequence) + payload
    icmp = icmp[:2] + struct.pack("!H", checksum(icmp)) + icmp[4:]
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(icmp),
        1,
        0,
        64,
        1,
        0,
        socket.inet_aton("10.77.0.1"),
        socket.inet_aton("10.77.0.3"),
    )
    ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
    return bytes.fromhex("0200000000030200000000010800") + ip + icmp


def pcap(records):
    data = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 256, 1)
    for micros, frame in records:
        data += struct.pack("<IIII", SECONDS, micros, len(frame), len(frame)) + frame
    return data


def captureFixture():
    route = [
        "h1-eth0-out",
        "access1-eth3-in",
        "access1-eth1-out",
        "dist1-eth3-in",
        "dist1-eth4-out",
        "access2-eth1-in",
        "access2-eth3-out",
        "h3-eth0-in",
    ]
    return {
        key: pcap(
            [
                (sequence * 100000 + route.index(key) * 1000, ethernetPacket(sequence))
                for sequence in range(1, 4)
            ]
            if key in route
            else []
        )
        for key in captureInterfaces()
    }


def decodedFixture():
    return [
        packet
        for key, data in captureFixture().items()
        for packet in decodePcap(data, key, WINDOW, IDENTIFIER)
    ]


class ProbePathsTests(unittest.TestCase):
    def test_pending_cancel_or_stop_precedes_any_capture(self):
        for stopping in (False, True):
            lab = SimpleNamespace(stopping=stopping, mailbox=None)
            callback = Mock(return_value=True)
            with patch("emulation.probe_paths.subprocess.Popen") as spawn:
                with self.assertRaises(CaptureInterrupted):
                    capturePaths(lab, service_controls=callback)
                spawn.assert_not_called()
            self.assertEqual(callback.call_count, 0 if stopping else 1)

    def test_capture_services_controls_in_readiness_probe_and_drain_waits(self):
        real_spawn = subprocess.Popen
        for phase in ("readiness", "probe", "drain", "shutdown"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as root:
                lab = SimpleNamespace(
                    output=Path(root),
                    runId=WINDOW,
                    processes=[],
                    mailbox=None,
                    stopping=False,
                    snapshot=Mock(),
                )
                state = SimpleNamespace(started=None, sender=None)

                def spawn(args, state=state, phase=phase, **kwargs):
                    state.started = time.monotonic()
                    if args[0] == "tcpdump":
                        code = "import sys,time; "
                        if phase == "shutdown":
                            code += "import signal; signal.signal(signal.SIGINT,signal.SIG_IGN); "
                        if phase != "readiness":
                            code += "print('listening on test',file=sys.stderr,flush=True); "
                        return real_spawn(["python", "-c", code + "time.sleep(10)"], **kwargs)
                    state.sender = real_spawn(["python", "-c", "import time; time.sleep(.15)"])
                    return state.sender

                lab.net = {"h1": SimpleNamespace(popen=spawn)}
                calls = []

                def controls(state=state, calls=calls, phase=phase):
                    calls.append(time.monotonic())
                    return (
                        state.started is not None
                        and time.monotonic() - state.started > (1.4 if phase == "shutdown" else 0.12)
                        and (
                            phase == "readiness"
                            or (
                                state.sender is not None
                                and (phase == "probe" or state.sender.poll() is not None)
                            )
                        )
                    )

                meta = {"test-in": {"interface": "test", "direction": "in", "host": None}}
                with (
                    patch("emulation.probe_paths.captureInterfaces", return_value=meta),
                    patch("emulation.probe_paths.subprocess.Popen", side_effect=spawn),
                    self.assertRaises(CaptureInterrupted),
                ):
                    capturePaths(lab, service_controls=controls)
                self.assertGreater(len(calls), 3)
                self.assertLess(max(b - a for a, b in zip(calls, calls[1:])), 0.3)
                self.assertFalse(lab.processes)
                self.assertFalse((lab.output / "probe-paths.json").exists())
                lab.snapshot.assert_not_called()

    def test_default_capture_checkpoint_polls_manual_cancels_only(self):
        mailbox = SimpleNamespace(control_generation=0)

        def poll(**kwargs):
            self.assertEqual(kwargs, {"cancel_only": True})
            mailbox.control_generation += 1

        mailbox.poll = Mock(side_effect=poll)
        lab = SimpleNamespace(stopping=False, mailbox=mailbox)
        with self.assertRaises(CaptureInterrupted):
            capturePaths(lab)
        mailbox.poll.assert_called_once()

    def test_three_correlated_packets_have_observed_ordered_hops(self):
        packets = decodedFixture()
        paths = observedPaths(packets, WINDOW, IDENTIFIER)
        self.assertEqual(len(packets), 24)
        self.assertEqual([p["status"] for p in paths], ["measured"] * 3)
        self.assertEqual(
            [h["dpid"] for h in paths[0]["observed_hops"]],
            ["0000000000000004", "0000000000000002", "0000000000000005"],
        )
        self.assertEqual(len({p["packet_id"] for p in paths}), 3)

    def test_missing_receive_interface_is_partial_never_filled_from_topology(self):
        packets = [p for p in decodedFixture() if p["capture_id"] != "dist1-eth3-in"]
        paths = observedPaths(packets, WINDOW, IDENTIFIER)
        self.assertTrue(all(p["status"] == "partial" for p in paths))
        self.assertTrue(
            all(
                h["ingress_port"] is None
                for p in paths
                for h in p["observed_hops"]
                if h["dpid"] == "0000000000000002"
            )
        )

    def test_duplicate_record_dedup_but_distinct_receive_times_are_ambiguous(self):
        packets = decodedFixture()
        baseline = observedPaths(packets, WINDOW, IDENTIFIER)
        self.assertEqual(
            observedPaths(packets + copy.deepcopy(packets), WINDOW, IDENTIFIER), baseline
        )
        # Pick a definite second sighting on a switch ingress.
        extra = next(copy.deepcopy(p) for p in packets if p["capture_id"] == "dist1-eth3-in")
        extra["timestamp"] = "2026-09-10T12:00:00.103500+00:00"
        self.assertEqual(
            observedPaths([*packets, extra], WINDOW, IDENTIFIER)[0]["status"], "ambiguous"
        )

    def test_wrong_window_id_sequence_reply_or_identifier_cannot_correlate(self):
        for frame in (
            ethernetPacket(window="01800000-0000-4000-8000-000000000002"),
            ethernetPacket(identifier=123),
            ethernetPacket(sequence=4),
        ):
            self.assertEqual(decodePcap(pcap([(1, frame)]), "h1-eth0-out", WINDOW, IDENTIFIER), [])

    def test_pcap_bounds_truncation_and_checksum(self):
        data = pcap([(1, ethernetPacket())])
        corrupt = bytearray(data)
        corrupt[40 + 14 + 20 + 2] ^= 1
        for bad in (b"", data[:-1], b"x" * 65537, data[:20], bytes(corrupt)):
            with self.assertRaises(ValueError):
                decodePcap(bad, "h1-eth0-out", WINDOW, IDENTIFIER)

    def test_all_fabric_ports_and_both_host_directions_are_instrumented(self):
        interfaces = captureInterfaces()
        self.assertEqual(len(interfaces), 40)
        self.assertIn("core-eth1-in", interfaces)
        self.assertIn("core-eth2-out", interfaces)
        self.assertIn("h3-eth0-in", interfaces)

    def test_reflected_request_is_ambiguous_not_a_complete_route(self):
        packets = decodedFixture()
        extra = next(copy.deepcopy(p) for p in packets if p["capture_id"] == "h1-eth0-out")
        extra["capture_id"] = "h1-eth0-in"
        self.assertEqual(
            observedPaths([*packets, extra], WINDOW, IDENTIFIER)[0]["status"], "ambiguous"
        )

    def test_no_packets_never_generates_planned_hops(self):
        paths = observedPaths([], WINDOW, IDENTIFIER)
        self.assertTrue(all(p["status"] == "partial" and not p["observed_hops"] for p in paths))


if __name__ == "__main__":
    unittest.main()
