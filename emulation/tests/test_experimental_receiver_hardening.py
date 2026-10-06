"""ADR-028 receiver hardening: v2 thresholds, failure evidence, lifecycle, real sockets."""

import hashlib
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import emulation.tests.test_experimental_lab as base
from emulation import experimental_lab_receiver as receiver_module
from emulation.experimental_lab_contract import (
    IMAGE,
    MODEL,
    POLICY_MAX_LIFETIME_SECONDS,
    POLICY_VERSION,
    SOURCE,
    THRESHOLD_FIELDS,
    Request,
    atomic_write,
    canonical,
    load_policy,
    thresholds,
    thresholds_pass,
    wrapper_digest,
)
from emulation.experimental_lab_receiver import Receiver, failure_record, redact, serve


def helper():
    return base.ContractTests("test_strict_request_no_boolean_actions_or_duplicate_fields")


def policy(**changes):
    value = dict(version=POLICY_VERSION, image_id=IMAGE, source_sha256=SOURCE, model_sha256=MODEL,
                 container_id="c" * 64, owner_label="test-owner", seed=9001, scenario="path0",
                 expires_at=time.time() + 100, max_duration_seconds=30, heartbeat_seconds=10,
                 min_dwell_seconds=0, max_observation_age_seconds=30, min_goodput_mbps=1,
                 max_loss_fraction=.2, max_probe_loss_fraction=.6, min_probe_sent=3,
                 min_traffic_bytes=1200, max_rtt_ms=100, wrapper_sha256=wrapper_digest(),
                 controller_policy_sha256=None)
    value.update(changes)
    return value


class PolicyV2Tests(unittest.TestCase):
    def load(self, value):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "policy.json"
            atomic_write(path, value)
            return load_policy(path, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_one_versioned_schema_with_separate_probe_and_traffic_thresholds(self):
        loaded = self.load(policy())
        self.assertEqual(POLICY_VERSION, "nanfo.experimental-receiver-policy/v2")
        self.assertEqual(set(thresholds(loaded)), set(THRESHOLD_FIELDS))
        self.assertEqual(thresholds(loaded)["max_probe_loss_fraction"], .6)
        missing = policy()
        del missing["min_traffic_bytes"]
        cases = {"exact_policy_fields_required": missing,
                 "unqualified_runtime_or_model": policy(version="nanfo.experimental-receiver-policy/v1"),
                 "invalid_policy_min_probe_sent": policy(min_probe_sent=True),
                 "invalid_policy_min_traffic_bytes": policy(min_traffic_bytes=0),
                 "invalid_policy_max_probe_loss_fraction": policy(max_probe_loss_fraction=1.5)}
        for reason, value in cases.items():
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.load(value)

    def test_policy_lifetime_is_capped_relative_to_now(self):
        with self.assertRaisesRegex(ValueError, "policy_lifetime_exceeds_cap"):
            self.load(policy(expires_at=time.time() + POLICY_MAX_LIFETIME_SECONDS + 60))
        self.load(policy(expires_at=time.time() + POLICY_MAX_LIFETIME_SECONDS - 60))
        # Expiry itself is an authority decision; an expired policy stays auditable.
        self.assertLess(self.load(policy(expires_at=time.time() - 5))["expires_at"], time.time())

    def test_udp_delivery_and_icmp_probe_loss_are_independent(self):
        rules = policy()
        observation = {"goodput_mbps": 5.0, "loss_fraction": .1, "latency_ms": 10.0}
        ping = {"sent": 10, "received": 5}
        self.assertTrue(thresholds_pass(observation, ping, 1200, rules))
        failing = {
            "probe_loss": (observation, ping, 1200, {**rules, "max_probe_loss_fraction": .4}),
            "udp_loss": ({**observation, "loss_fraction": .3}, ping, 1200, rules),
            "probe_count": (observation, {"sent": 2, "received": 2}, 1200, rules),
            "traffic": (observation, ping, 1199, rules),
            "traffic_type": (observation, ping, 1200.0, rules),
            "rtt_missing": ({**observation, "latency_ms": None}, ping, 1200, rules),
            "rtt_high": ({**observation, "latency_ms": 101.0}, ping, 1200, rules),
            "goodput": ({**observation, "goodput_mbps": .5}, ping, 1200, rules),
            "bool_count": (observation, {"sent": True, "received": True}, 1200, rules),
            "received_exceeds_sent": (observation, {"sent": 3, "received": 4}, 1200, rules),
        }
        for case, args in failing.items():
            with self.subTest(case=case):
                self.assertFalse(thresholds_pass(*args))

    def test_runtime_thresholds_use_foreground_receiver_bytes(self):
        runtime, _, _, _ = base.fixture()
        evidence = {"frame": {"response": {"data": {
            "observation": {"goodput_mbps": 5.0, "loss_fraction": 0.0, "latency_ms": 5.0},
            "evidence": {"ping": {"sent": 4, "received": 4},
                         "udp_received": [{"bytes": 2400}, {"bytes": 0}]}}}}}
        self.assertTrue(runtime.thresholds(evidence, policy()))
        evidence["frame"]["response"]["data"]["evidence"]["udp_received"][0]["bytes"] = 1000
        self.assertFalse(runtime.thresholds(evidence, policy()))


class RequestTests(unittest.TestCase):
    def test_non_string_request_ids_are_rejected_as_invalid_values(self):
        request = helper().request()
        for value in (5, None, ["x"], {"a": 1}, "X" * 36, str(uuid4()).upper()):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "invalid_request_id"):
                Request.parse(json.dumps({**request, "request_id": value}).encode())


class FailureEvidenceTests(unittest.TestCase):
    def test_redaction_removes_paths_and_long_hex(self):
        text = redact("boom at /opt/nanfo/emulation/x.py token=" + "ab" * 32 + "\nnext line")
        self.assertEqual(text, "boom at <path> token=<hex> next line")
        self.assertLessEqual(len(redact("x" * 999)), 160)

    def test_operation_failure_persists_class_redacted_message_and_frames(self):
        tests = helper()
        with tempfile.TemporaryDirectory() as root:
            receiver, _, _, _ = tests.receiver(Path(root))
            try:
                receiver.runtime.capture_baseline()
                receiver.phase = "observed"
                receiver.last_frame = {"completed_at": time.time()}
                receiver.authority = lambda: None

                def exploding_frame(action):
                    raise RuntimeError("frozen failure at /opt/nanfo/emulation/ospf.py key " + "f" * 64)

                receiver.runtime.frame = exploding_frame
                request = {**tests.wire(receiver, "execute"), "action": 1, "duration_seconds": 10}
                response = receiver.handle(canonical(request))
                self.assertEqual(response["status"], "rejected")
                failure = response["evidence"]["failure"]
                self.assertEqual(response["evidence"]["reason"], "receiver_operation_failed")
                self.assertEqual(failure["exception"], "RuntimeError")
                self.assertEqual(failure["context"], "execute")
                self.assertIn("exploding_frame", failure["frames"])
                self.assertNotIn("/opt/nanfo", failure["message"])
                self.assertNotIn("f" * 64, json.dumps(response))
                journal = json.loads(receiver.journal_path.read_bytes())
                self.assertEqual(journal["failures"][-1]["exception"], "RuntimeError")
                self.assertTrue(response["evidence"]["restoration"]["original_forwarding_verified"])
            finally:
                os.close(receiver.claim)

    def test_watchdog_restore_failure_is_recorded_not_suppressed(self):
        receiver = Receiver.__new__(Receiver)
        receiver.runtime = SimpleNamespace(restore=Mock(side_effect=RuntimeError("readback unavailable")))
        receiver.policy = {"heartbeat_seconds": 10}
        receiver.lock = threading.RLock()
        receiver.shutdown = threading.Event()
        receiver.active_until = time.time() - 1
        receiver.latch_stop = Mock()
        receiver.persist = Mock()
        receiver.authority = Mock(side_effect=KeyError("unexpected_state"))
        worker = threading.Thread(target=receiver.watchdog)
        with patch.object(receiver_module.LOG, "error") as logged:
            worker.start()
            try:
                deadline = time.monotonic() + 2
                while not getattr(receiver, "failures", None) and time.monotonic() < deadline:
                    time.sleep(.01)
            finally:
                receiver.shutdown.set()
                worker.join(2)
        self.assertEqual(receiver.failures[0]["context"], "watchdog_restore")
        self.assertEqual(receiver.failures[0]["exception"], "RuntimeError")
        self.assertEqual(receiver.phase, "recovery_required")
        receiver.latch_stop.assert_called_with("watchdog:authority_unavailable", "receiver")
        self.assertTrue(logged.called)

    def test_failure_record_is_bounded(self):
        receiver = Receiver.__new__(Receiver)
        for index in range(receiver_module.MAX_FAILURES + 3):
            receiver.record_failure("x", ValueError(str(index)))
        self.assertEqual(len(receiver.failures), receiver_module.MAX_FAILURES)
        self.assertEqual(receiver.failures_dropped, 3)
        self.assertEqual(failure_record("c", ValueError("v"))["frames"], [])


class LifecycleTests(unittest.TestCase):
    def test_existing_journal_is_never_resumed(self):
        tests = helper()
        with tempfile.TemporaryDirectory() as root:
            receiver, _, _, _ = tests.receiver(Path(root))
            os.close(receiver.claim)
            with self.assertRaisesRegex(ValueError, "existing_receiver_journal_requires_operator_recovery"):
                tests.receiver(Path(root))

    def test_failpoints_are_ignored_unless_explicitly_armed(self):
        tests = helper()
        for armed in (False, True):
            with self.subTest(armed=armed), tempfile.TemporaryDirectory() as root:
                receiver, rules, routes, _ = tests.receiver(Path(root), failpoints=armed)
                try:
                    receiver.runtime.capture_baseline()
                    receiver.phase = "executing"
                    receiver.current = Request.parse(canonical({**tests.request(),
                                                                "policy_sha256": receiver.policy_hash}))
                    receiver.operation_start = 0
                    tests.grant(receiver)
                    atomic_write(Path(root) / "failpoint.json", {"policy_sha256": receiver.policy_hash,
                        "operation": "execute", "ordinal": 1, "when": "before", "effect": "raise",
                        "timeout_seconds": 1})
                    with receiver.lock:
                        if armed:
                            with self.assertRaisesRegex(RuntimeError, "injected_partial_apply"):
                                receiver.runtime.routing.change(1)
                        else:
                            receiver.runtime.routing.change(1)
                    self.assertEqual((Path(root) / "boundary.json").exists(), armed)
                    self.assertEqual(bool(rules or routes), not armed)
                    journal = json.loads(receiver.journal_path.read_bytes())
                    self.assertIs(journal["failpoints_enabled"], armed)
                finally:
                    os.close(receiver.claim)


class TransportClassificationTests(unittest.TestCase):
    def test_only_authenticated_state_changing_requests_latch_on_lost_replies(self):
        tests = helper()
        with tempfile.TemporaryDirectory() as root:
            receiver, _, _, _ = tests.receiver(Path(root))
            try:
                def raw(operation, **changes):
                    return canonical({**tests.wire(receiver, operation), **changes})

                self.assertFalse(receiver.transport_failure_latches(b"not json"))
                self.assertFalse(receiver.transport_failure_latches(raw("execute", token="e" * 64)))
                self.assertFalse(receiver.transport_failure_latches(raw("execute", policy_sha256="e" * 64)))
                for operation in ("status", "heartbeat", "observe", "stop"):
                    self.assertFalse(receiver.transport_failure_latches(raw(operation)), operation)
                for operation in ("bootstrap", "bind", "verify", "restore", "recover"):
                    self.assertTrue(receiver.transport_failure_latches(raw(operation)), operation)
                self.assertTrue(receiver.transport_failure_latches(raw("execute", action=1, duration_seconds=5)))
            finally:
                os.close(receiver.claim)


class SocketTests(unittest.TestCase):
    def setUp(self):
        self.tests = helper()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.receiver, _, _, _ = self.tests.receiver(self.root)
        self.path = str(self.root / "receiver.sock")
        self.server = threading.Thread(target=serve, args=(self.receiver, self.path), daemon=True)
        self.server.start()
        deadline = time.monotonic() + 2
        while not os.path.exists(self.path) and time.monotonic() < deadline:
            time.sleep(.01)

    def tearDown(self):
        self.receiver.shutdown.set()
        self.server.join(3)
        os.close(self.receiver.claim)
        self.temp.cleanup()

    def connect(self):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(5)
        client.connect(self.path)
        return client

    def exchange(self, payload):
        with self.connect() as client:
            client.sendall(payload)
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                part = client.recv(65536)
                if not part:
                    break
                chunks.append(part)
        return json.loads(b"".join(chunks))

    def status(self):
        return canonical(self.tests.wire(self.receiver, "status"))

    def assertNotStopped(self):
        self.assertFalse(self.receiver.stopped)
        self.assertFalse((self.root / "STOP").exists())

    def test_wrong_token_and_oversize_requests_get_bounded_rejection_without_stop(self):
        self.assertEqual(self.exchange(self.status())["status"], "ok")
        wrong = canonical({**self.tests.wire(self.receiver, "restore"), "token": "e" * 64})
        with patch.object(receiver_module.LOG, "warning"):
            self.assertEqual(self.exchange(wrong), {"error": "request_rejected"})
            self.assertEqual(self.exchange(b"{" + b" " * 9000 + b"}"), {"error": "request_rejected"})
            self.assertEqual(self.exchange(b'{"request_id": 7}'), {"error": "request_rejected"})
        self.assertNotStopped()

    def test_idle_peers_are_dropped_after_the_read_deadline_and_slots_recover(self):
        with patch.object(receiver_module, "REQUEST_READ_SECONDS", .3), \
                patch.object(receiver_module.LOG, "warning"):
            idle = [self.connect() for _ in range(receiver_module.MAX_CLIENTS)]
            try:
                time.sleep(.1)
                with self.connect() as refused:
                    self.assertEqual(refused.recv(10), b"")  # 4-slot exhaustion: closed at once
                time.sleep(.5)
                for peer in idle:
                    self.assertEqual(peer.recv(10), b"")  # dropped, no reply
                self.assertEqual(self.exchange(self.status())["status"], "ok")
            finally:
                for peer in idle:
                    peer.close()
        self.assertNotStopped()

    def early_close(self, payload):
        closed = threading.Event()
        original = self.receiver.handle

        def delayed(raw):
            closed.wait(2)
            time.sleep(.05)
            return original(raw)

        self.receiver.handle = delayed
        with patch.object(receiver_module.LOG, "warning"):
            client = self.connect()
            client.sendall(payload)
            client.shutdown(socket.SHUT_WR)
            client.close()
            closed.set()
            time.sleep(.4)
        self.receiver.handle = original

    def test_early_close_latches_stop_only_for_authenticated_state_changes(self):
        self.early_close(b"garbage")
        self.early_close(self.status())
        self.early_close(canonical({**self.tests.wire(self.receiver, "restore"), "token": "e" * 64}))
        self.assertNotStopped()
        self.early_close(canonical(self.tests.wire(self.receiver, "restore", fence=2)))
        deadline = time.monotonic() + 2
        while not self.receiver.stopped and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.receiver.stopped)
        self.assertEqual(self.receiver.stop_cause["reason"], "response_transport_failed")

    def test_unexpected_handler_exception_still_answers_and_keeps_serving(self):
        self.receiver.handle = Mock(side_effect=[AttributeError("internal bug"), {"ok": True}])
        with patch.object(receiver_module.LOG, "warning") as warning:
            self.assertEqual(self.exchange(self.status()), {"error": "request_rejected"})
        self.assertEqual(self.exchange(self.status()), {"ok": True})
        self.assertIn("AttributeError", warning.call_args_list[0].args)
        self.assertNotStopped()


if __name__ == "__main__":
    unittest.main()


class StateMutationTests(unittest.TestCase):
    """ADR-028 task 12: every mutating lab command is classified and authority-gated."""

    def test_command_classification(self):
        from emulation.experimental_lab_runtime import classify_command

        cases = {
            ("ip", "-j", "rule", "show"): "readback",
            ("ip", "-j", "route", "show", "table", "all"): "readback",
            ("ip", "-j", "route", "get", "10.0.0.3", "from", "10.0.0.1"): "readback",
            ("ip", "-j", "-s", "link", "show"): "readback",
            ("tc", "-j", "-s", "qdisc", "show", "dev", "x"): "readback",
            ("vtysh", "--vty_socket", "/r", "-c", "show ip route ospf json"): "readback",
            ("sysctl", "-n", "net.ipv4.ip_forward"): "readback",
            ("ip", "route", "add", "10.0.0.3/32"): "route",
            ("ip", "rule", "del", "priority", "19110"): "route",
            ("tc", "class", "change", "dev", "x"): "state",
            ("tc", "qdisc", "del", "dev", "x", "root"): "state",
            ("ip", "link", "set", "dev", "x", "down"): "state",
            ("ip", "addr", "replace", "10.0.0.1/30", "dev", "x"): "state",
            ("ip", "neigh", "replace", "10.0.0.2"): "state",
            ("ip", "-j", "link", "set", "dev", "x", "down", "show"): "state",
            ("sysctl", "-qw", "net.ipv4.ip_forward=0"): "state",
            ("vtysh", "-c", "configure terminal"): "state",
            ("iptables", "-F"): "state",
        }
        for args, expected in cases.items():
            with self.subTest(args=args):
                self.assertEqual(classify_command(list(args)), expected)

    def runtime(self):
        runtime, _, _, _ = base.fixture()
        route_command = runtime.original_command
        lab = {"rate": "20Mbit", "net.ipv4.ip_forward": "1"}
        dispatched = []

        def command(node, args, timeout=5):
            if args[:3] == ["tc", "class", "show"]:
                return f"class htb 5:1 root rate {lab['rate']} ceil {lab['rate']} burst 1600b\n"
            if args[:3] == ["tc", "class", "change"]:
                dispatched.append(list(args))
                lab["rate"] = args[11]
                return ""
            if args[:2] == ["sysctl", "-n"]:
                return lab[args[2]] + "\n"
            if args[:2] == ["sysctl", "-qw"]:
                dispatched.append(list(args))
                for item in args[2:]:
                    name, value = item.split("=")
                    lab[name] = value
                return ""
            return route_command(node, args, timeout=timeout)

        runtime.original_command = command
        return runtime, lab, dispatched

    def change(self, rate):
        return ["tc", "class", "change", "dev", "access1-eth1", "parent", "5:0", "classid", "5:1",
                "htb", "rate", rate, "ceil", rate]

    def test_state_mutations_are_authority_checked_wal_recorded_and_restored(self):
        runtime, lab, _ = self.runtime()
        runtime.capture_baseline()
        persisted = []
        runtime.persist = lambda: persisted.append(runtime.state())
        runtime.network.command("access1", self.change("2mbit"))
        runtime.network.command("dist1", ["sysctl", "-qw", "net.ipv4.ip_forward=0"])
        self.assertEqual((lab["rate"], lab["net.ipv4.ip_forward"]), ("2mbit", "0"))
        self.assertEqual(runtime.calls["state_authority_checks"], 2)
        self.assertEqual(runtime.calls["state_mutation_completed"], 2)
        # WAL: before-state and pending command were durable before the write.
        self.assertIsNone(persisted[0]["state_transcript"][0]["completed"])
        self.assertEqual(persisted[0]["state_baseline"]["access1|tc-class|access1-eth1|5:1"]["rate"], "20Mbit")
        restored = runtime.restore()
        self.assertEqual((lab["rate"], lab["net.ipv4.ip_forward"]), ("20Mbit", "1"))
        self.assertEqual(sorted(restored["lab_state_restored"]),
                         ["access1|tc-class|access1-eth1|5:1", "dist1|sysctl|net.ipv4.ip_forward"])
        self.assertEqual(runtime.calls["state_compensations"], 2)

    def test_stop_revocation_unsupported_and_recovery_writes_never_dispatch(self):
        runtime, _, dispatched = self.runtime()
        runtime.authority = Mock(side_effect=ValueError("stopped"))
        with self.assertRaisesRegex(ValueError, "stopped"):
            runtime.network.command("access1", self.change("2mbit"))
        self.assertEqual(dispatched, [])
        self.assertIsNone(runtime.state_transcript[-1]["completed"])
        runtime.authority = Mock()
        for args in (["ip", "link", "set", "dev", "access1-eth1", "down"],
                     ["tc", "qdisc", "del", "dev", "access1-eth1", "root"],
                     ["sysctl", "-qw", "kernel.panic=1"], ["iptables", "-F"]):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "unsupported_state_mutation"):
                runtime.network.command("access1", args)
        runtime.restoring = True
        with self.assertRaisesRegex(ValueError, "recovery_cannot_mutate_lab_state"):
            runtime.network.command("access1", self.change("2mbit"))
        self.assertEqual(dispatched, [])
        runtime.authority.assert_not_called()
