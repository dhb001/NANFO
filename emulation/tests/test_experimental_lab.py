"""Offline exact frozen-code action-path and receiver safety tests. No lab/network."""

import contextlib
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "ai-engine/artifacts/adr024-qualified-001/recovery/emulation"
# Load the original MatchedRouting bytes directly, without touching its source.
spec = importlib.util.spec_from_file_location("_adr025_original_matched", FROZEN / "matched.py")
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)

from emulation.experimental_lab_contract import (  # noqa: E402
    IMAGE,
    MODEL,
    POLICY_VERSION,
    SOURCE,
    VERSION,
    Request,
    atomic_write,
    canonical,
    load_policy,
    wrapper_digest,
)
from emulation.experimental_lab_receiver import Receiver  # noqa: E402
from emulation.experimental_lab_runtime import GuardedRuntime  # noqa: E402
from emulation.ospf import PATHS, OSPFNetwork  # noqa: E402


def fixture(authority=lambda: None, persist=lambda: None):
    network = OSPFNetwork()
    lab = SimpleNamespace(network=network, checkController=Mock())
    routing = original.MatchedRouting(lab)
    rules, routes, commands = {}, {}, []

    def command(node, args, timeout=5):
        commands.append((node, list(args)))
        if args[1:3] == ["-j", "rule"]:
            return json.dumps([r for (n, _), r in rules.items() if n == node])
        if args[1:3] == ["-j", "route"]:
            return json.dumps([r for (n, _), r in routes.items() if n == node])
        table = int(args[args.index("table") + 1])
        target = rules if args[1] == "rule" else routes
        if args[2] == "del":
            del target[node, table]
        elif args[1] == "rule":
            target[node, table] = dict(table=table, priority=table,
                src=args[args.index("from") + 1], dst=args[args.index("to") + 1])
        else:
            target[node, table] = dict(table=table, dst=args[3], protocol="static", flags=["onlink"],
                dev=args[args.index("dev") + 1], gateway=args[args.index("via") + 1])
        return ""

    def path(source, destination):
        action = routing.action if source in ("h1", "h3") and routing.action is not None else 0
        nodes = PATHS[action] if source < destination else tuple(reversed(PATHS[action]))
        return {"nodes": [source, *nodes, destination], "action": action}

    network.command = command
    network.routePath = path
    exp = SimpleNamespace(lab=lab, routing=routing, index=3, done=False, episode=None)
    runtime = GuardedRuntime(exp, authority, persist)
    return runtime, rules, routes, commands


class RuntimeTests(unittest.TestCase):
    def test_original_frozen_bytes_and_path_equivalence(self):
        self.assertEqual(hashlib.sha256((FROZEN / "matched.py").read_bytes()).hexdigest(),
                         "da13903064be198d52485a06593528d6d11d313bb2f4202e9137c5b1f9bb18fc")
        wrapped, _, _, actual = fixture()
        plain, _, _, expected = fixture()
        plain.network.command = plain.original_command
        for action in (0, 0, 1, 1, 0):
            wrapped.routing.change(action)
            plain.routing.change(action)
        def mutations(calls):
            return [(node, args) for node, args in calls
                    if args[:2] in (["ip", "rule"], ["ip", "route"])]
        self.assertEqual(mutations(actual), mutations(expected))
        self.assertEqual(wrapped.calls["mutation_completed"], 60)
        self.assertEqual(wrapped.calls["authority_checks"], 60)
        self.assertEqual(wrapped.calls["original_change_calls"], 5)

    def test_stop_every_mutation_prefix_restores_prior_route(self):
        for prefix in range(25):
            runtime, rules, routes, _ = fixture()
            baseline = runtime.capture_baseline()
            runtime.routing.change(0)
            count = 0

            def authority(prefix=prefix):
                nonlocal count
                count += 1
                if count > prefix:
                    raise ValueError("stopped")

            runtime.authority = authority
            with contextlib.suppress(ValueError):
                runtime.routing.change(1)
            restored = runtime.restore()
            self.assertEqual(restored["readback"], baseline)
            self.assertEqual(len(rules), 0)
            self.assertEqual(len(routes), 0)
            self.assertIsNone(runtime.routing.action)

    def test_foreign_state_not_deleted(self):
        runtime, rules, _, _ = fixture()
        runtime.capture_baseline()
        runtime.routing.change(0)
        rules["access1", 19110]["src"] = "192.0.2.55"
        with self.assertRaisesRegex((RuntimeError, ValueError), "foreign"):
            runtime.restore()
        self.assertEqual(rules["access1", 19110]["src"], "192.0.2.55")

    def test_complete_foreign_cleanup_semantics_refused_before_any_delete(self):
        variants = [
            ("rule", "fwmark", "0x123"), ("rule", "fwmask", "0xff"),
            ("rule", "iif", "access1-eth1"), ("rule", "oif", "access1-eth2"),
            ("rule", "uidrange", "1-2"), ("rule", "ipproto", "tcp"),
            ("rule", "sport", 80), ("rule", "suppress_prefixlength", 0),
            ("rule", "flags", ["not"]), ("rule", "table", "20000"),
            ("route", "multipath", [{"gateway": "192.0.2.1"}]),
            ("route", "nhid", 2), ("route", "encap", {}), ("route", "metric", 10),
            ("route", "table", "20000"), ("route", "flags", ["onlink", "linkdown"]),
            ("route", "flags", []),
            ("route", "type", "blackhole"), ("route", "scope", "link"),
            ("route", "tos", 1), ("route", "unknown", False),
        ]
        for kind, key, value in variants:
            with self.subTest(kind=kind, key=key):
                runtime, rules, routes, commands = fixture()
                runtime.capture_baseline()
                runtime.routing.change(0)
                target = rules if kind == "rule" else routes
                target["access1", 19110][key] = value
                before = len(commands)
                with self.assertRaisesRegex(ValueError, "foreign"):
                    runtime.restore()
                self.assertFalse(any(args[:3] in (["ip", "rule", "del"], ["ip", "route", "del"])
                                     for _, args in commands[before:]))
                self.assertTrue(runtime.routing.owned)

    def test_exact_kernel_defaults_accepted_foreign_extra_slots_refused(self):
        runtime, rules, routes, _ = fixture()
        runtime.capture_baseline()
        runtime.routing.change(0)
        for row in rules.values():
            row.update(flags=[], action="to_tbl", protocol="boot", tos=0)
        for row in routes.values():
            row.update(flags=["onlink"], type="unicast", scope="global", tos=0)
        runtime.restore()
        self.assertFalse(rules or routes)

        runtime, rules, routes, commands = fixture()
        runtime.capture_baseline()
        runtime.routing.change(0)
        rules["dist2", 19110] = dict(rules["access1", 19110])
        before = len(commands)
        with self.assertRaisesRegex(ValueError, "foreign_unowned"):
            runtime.restore()
        self.assertFalse(any(args[2:3] == ["del"] for _, args in commands[before:]))

    def test_cleanup_revalidates_after_journal_and_hook_wait(self):
        runtime, rules, routes, commands = fixture()
        runtime.capture_baseline()
        runtime.routing.change(0)

        def boundary(when, entry):
            if when == "before" and entry["argv"][2] == "del":
                table = int(entry["argv"][entry["argv"].index("table") + 1])
                rules[entry["node"], table]["fwmark"] = "0x123"

        runtime.boundary = boundary
        before = len(commands)
        with self.assertRaisesRegex(ValueError, "foreign_policy_rule"):
            runtime.restore()
        self.assertFalse(any(args[2:3] == ["del"] for _, args in commands[before:]))
        self.assertTrue(rules and routes)

    def test_state_snapshot_has_no_nested_live_references(self):
        runtime, _, _, _ = fixture()
        runtime.capture_baseline()
        runtime.routing.change(0)
        state = runtime.state()
        saved = canonical(state)
        runtime.restore()
        self.assertEqual(canonical(state), saved)
        state["transcript"][0]["argv"].append("caller-change")
        state["baseline"]["tables"].clear()
        self.assertNotIn("caller-change", runtime.transcript[0]["argv"])
        self.assertTrue(runtime.baseline["tables"])

    def test_duplicate_kernel_rows_refused(self):
        runtime, _, _, commands = fixture()
        runtime.capture_baseline()
        runtime.routing.change(0)
        inventory = runtime.routing.inventory

        def duplicate(node, table):
            rules, routes = inventory(node, table)
            return (rules + rules, routes) if node == "access1" and table == 19110 else (rules, routes)

        runtime.routing.inventory = duplicate
        before = len(commands)
        with self.assertRaisesRegex(ValueError, "foreign_duplicate"):
            runtime.restore()
        self.assertFalse(any(args[2:3] == ["del"] for _, args in commands[before:]))

    def test_after_write_failure_compensates_without_readding_or_measurement(self):
        runtime, rules, routes, commands = fixture()
        baseline = runtime.capture_baseline()
        fired = False

        def boundary(when, entry):
            nonlocal fired
            if when == "after" and not fired:
                fired = True
                raise RuntimeError("injected_after_first_native_write")

        runtime.boundary = boundary
        with self.assertRaisesRegex(RuntimeError, "injected_after_first_native_write"):
            runtime.routing.change(1)
        self.assertFalse(rules or routes)
        runtime.frame = Mock(side_effect=AssertionError("recovery must not measure"))
        result = runtime.restore()
        self.assertEqual(result["readback"], baseline)
        self.assertEqual(sum(args[:3] == ["ip", "route", "add"] for _, args in commands), 1)
        self.assertFalse(runtime.routing.owned)

    def test_wal_precedes_every_command(self):
        writes = []
        runtime, _, _, commands = fixture(persist=lambda: writes.append(len(commands)))
        runtime.routing.change(0)
        self.assertEqual(len(writes), 24)
        self.assertTrue(all(b == a + 1 for a, b in zip(writes[::2], writes[1::2])))

    def test_revocation_during_wal_blocks_add_at_last_boundary(self):
        runtime, rules, routes, commands = fixture()
        runtime.capture_baseline()
        revoked = False

        def persist():
            nonlocal revoked
            if runtime.transcript:
                revoked = True

        def authority():
            if revoked:
                raise ValueError("revoked_during_fsync")

        runtime.persist, runtime.authority = persist, authority
        with self.assertRaisesRegex(ValueError, "revoked_during_fsync"):
            runtime.routing.change(1)
        self.assertFalse(rules or routes)
        self.assertFalse(any(args[:3] in (["ip", "route", "add"], ["ip", "rule", "add"])
                             for _, args in commands))

    def test_full_preserved_source_import_and_original_command_equivalence(self):
        program = r'''
import sys
sys.path.insert(0, sys.argv[1])
from emulation.experiment import environmentSpec
from emulation.tests.test_matched import MatchedTests
sys.path.insert(0, sys.argv[2])
from experimental_lab_runtime import GuardedRuntime
from types import SimpleNamespace
assert environmentSpec('matched')[0]['source_sha256'] == '08c312c64154c9aedcd3b22eeb3573783590e0eb7183bc999cb8ef39b958dbbd'
plain, _, plain_routes = MatchedTests().routing()
routing, rules, routes = MatchedTests().routing()
for driver, table_rows in ((plain, plain_routes), (routing, routes)):
 original_transport = driver.network.command.side_effect
 def kernel(node,args,original_transport=original_transport,table_rows=table_rows):
  result=original_transport(node,args)
  if args[:3] == ['ip','route','add']:
   table_rows[node,int(args[args.index('table')+1])]['flags']=['onlink']
  return result
 driver.network.command.side_effect=kernel
transport = routing.network.command
routing.network.command = lambda node,args,timeout=5: transport(node,args)
runtime = GuardedRuntime(SimpleNamespace(lab=routing.lab,routing=routing), lambda:None, lambda:None)
baseline = runtime.capture_baseline()
transport.reset_mock()
for action in (0,1,0):
 plain.change(action)
 runtime.routing.change(action)
def mutations(calls):
 return [c for c in calls if c.args[1][:2] in (['ip','rule'],['ip','route'])]
assert mutations(plain.network.command.call_args_list) == mutations(transport.call_args_list)
restored = runtime.restore()
assert restored['readback'] == baseline and not rules and not routes
assert not runtime.routing.owned
'''
        subprocess.run([sys.executable, "-B", "-c", program, str(FROZEN.parent), str(ROOT / "emulation")],
                       check=True, capture_output=True, timeout=20)


class ContractTests(unittest.TestCase):
    def receiver(self, directory, receiver_class=Receiver):
        policy = dict(version=POLICY_VERSION, image_id=IMAGE, source_sha256=SOURCE, model_sha256=MODEL,
            container_id="c" * 64, owner_label="test-owner", seed=9001, scenario="path0",
            expires_at=time.time() + 100, max_duration_seconds=30, heartbeat_seconds=10,
            min_dwell_seconds=0, max_observation_age_seconds=30, min_goodput_mbps=0,
            max_loss_fraction=1, max_rtt_ms=1000, wrapper_sha256=wrapper_digest(),
            controller_policy_sha256=None)
        atomic_write(directory / "policy.json", policy)
        sha = hashlib.sha256((directory / "policy.json").read_bytes()).hexdigest()
        (directory / "token").write_text("b" * 64)
        (directory / "token").chmod(0o600)
        runtime, rules, routes, commands = fixture()
        # Receiver must wrap original object exactly once, as production composition does.
        runtime.network.command = runtime.original_command
        runtime.experiment.lab.checkController = Mock()
        receiver = receiver_class(directory, directory / "policy.json", sha,
                            directory / "token", runtime.experiment)
        return receiver, rules, routes, commands

    def test_stop_during_bootstrap_admission_read_denies_original_write(self):
        from emulation import experimental_lab_receiver as receiver_module

        for stop_kind in ("latch", "file"):
            with self.subTest(stop_kind=stop_kind), tempfile.TemporaryDirectory() as root:
                receiver, rules, routes, commands = self.receiver(Path(root))
                receiver.runtime.capture_baseline()
                request = self.wire(receiver, "bootstrap")
                receiver.current = Request.parse(canonical(request))
                receiver.phase = "bootstrapping"
                receiver.bootstrap_request_id = request["request_id"]
                atomic_write(Path(root) / "bootstrap-admission.json", {
                    "policy_sha256": receiver.policy_hash, "request_id": request["request_id"],
                    "expires_at": time.time() + 60, "authorized": True})
                entered, release = threading.Event(), threading.Event()
                original_read = receiver_module.protected_read
                failures = []

                def blocked_read(path, *args, original_read=original_read, entered=entered, release=release):
                    raw = original_read(path, *args)
                    if Path(path).name == "bootstrap-admission.json":
                        entered.set()
                        if not release.wait(2):
                            raise RuntimeError("test_read_barrier_timeout")
                    return raw

                def writer(receiver=receiver, failures=failures):
                    try:
                        with receiver.lock:
                            receiver.runtime.routing.change(0)
                    except Exception as exc:
                        failures.append(exc)

                with patch.object(receiver_module, "protected_read", side_effect=blocked_read):
                    worker = threading.Thread(target=writer)
                    worker.start()
                    try:
                        self.assertTrue(entered.wait(2))
                        # WAL must already describe this exact pending mutation.
                        journal = json.loads((Path(root) / "journal.json").read_bytes())
                        self.assertIsNone(journal["runtime"]["transcript"][-1]["completed"])
                        if stop_kind == "latch":
                            receiver.latch_stop("test_during_admission_read", request["request_id"])
                        else:
                            atomic_write(Path(root) / "STOP", {"reason": "external_operator"})
                    finally:
                        release.set()
                        worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(failures), 1)
                self.assertIn("bootstrap_authority_changed_during_read", str(failures[0]))
                self.assertFalse(rules or routes)
                self.assertFalse(any(args[:3] in (["ip", "route", "add"], ["ip", "rule", "add"])
                                     for _, args in commands))
                os.close(receiver.claim)

    def wire(self, receiver, operation, fence=1):
        return {**self.request(), "policy_sha256": receiver.policy_hash,
                "operation": operation, "action": None, "duration_seconds": 0, "fence": fence}

    def test_execute_receipt_and_failed_frame_survive_cleanup_and_replay(self):
        with tempfile.TemporaryDirectory() as root:
            receiver, _, _, _ = self.receiver(Path(root))
            receiver.runtime.capture_baseline()
            receiver.phase = "observed"
            receiver.last_frame = {"completed_at": time.time()}
            receiver.authority = lambda: None
            receiver.runtime.authority = lambda: None
            receiver.runtime.dispatch_authority = lambda entry: None

            def frame(action):
                receiver.runtime.routing.change(action)
                return {"frame": {"fixture_only": True}, "completed_at": time.time()}

            receiver.runtime.frame = frame
            receiver.runtime.thresholds = lambda *_: True
            request = {**self.wire(receiver, "execute"), "action": 1, "duration_seconds": 10}
            response = receiver.handle(canonical(request))
            saved = canonical(response)
            self.assertEqual(response["status"], "ok")
            failed = {"request": {"command": "step"}, "response": {"data": {
                "evidence": {"measurement_complete": False, "error": "fixture original error"}}}}

            def fail(_):
                receiver.runtime.frames.append(failed)
                raise ValueError("original_measurement_failed")

            receiver.runtime.frame = fail
            receiver.runtime.experiment.index = 1
            rejected = receiver.handle(canonical(self.wire(receiver, "verify", 2)))
            self.assertEqual(rejected["evidence"]["failed_frame"], failed)
            journal = json.loads(receiver.journal_path.read_bytes())
            self.assertEqual(journal["frames"][-1], failed)
            self.assertEqual(canonical(journal["receipts"][request["request_id"]]["response"]), saved)
            self.assertEqual(canonical(receiver.handle(canonical(request))), saved)
            response["evidence"]["action_paths"]["transcript"][0]["argv"].append("corrupt")
            self.assertEqual(canonical(receiver.handle(canonical(request))), saved)
            os.close(receiver.claim)

    def test_stopped_heartbeat_has_bound_rejection_not_malformed_response(self):
        with tempfile.TemporaryDirectory() as root:
            receiver, _, _, _ = self.receiver(Path(root))
            receiver.latch_stop("measurement_failure", "fixture")
            request = self.wire(receiver, "heartbeat")
            response = receiver.handle(canonical(request))
            self.assertEqual(response["status"], "rejected")
            for key in ("version", "request_id", "fence", "policy_sha256"):
                self.assertEqual(response[key], request[key])
            self.assertEqual(response["evidence"]["reason"], "heartbeat_denied")
            self.assertFalse((Path(root) / "authority.json").exists())
            os.close(receiver.claim)

    def test_bootstrap_captures_before_image_and_observe_is_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            receiver, rules, routes, commands = self.receiver(Path(root))
            request = self.wire(receiver, "bootstrap")
            atomic_write(Path(root) / "bootstrap-admission.json", {
                "policy_sha256": receiver.policy_hash, "request_id": request["request_id"],
                "expires_at": time.time() + 60, "authorized": True})
            episode = str(uuid4())

            def frame():
                self.assertTrue(receiver.runtime.baseline)
                self.assertTrue(all(not v["rules"] and not v["routes"]
                                    for v in receiver.runtime.baseline["tables"].values()))
                receiver.runtime.routing.change(0)
                receiver.runtime.experiment.episode = episode
                return {"frame": {"fixture_only": True}, "completed_at": time.time()}

            receiver.runtime.frame = frame
            boot = receiver.handle(canonical(request))
            self.assertEqual(boot["status"], "ok")
            self.assertEqual(boot["evidence"]["episode_id"], episode)
            original_receipt = canonical(boot)
            before = len(commands)
            self.assertEqual(receiver.handle(canonical(request)), boot)
            self.assertEqual(len(commands), before)
            with self.assertRaisesRegex(ValueError, "request_id_reused"):
                receiver.handle(canonical({**request, "fence": 2}))
            binding = {"receiver_policy_sha256": receiver.policy_hash,
                       "controller_policy_sha256": "d" * 64, "run_id": episode,
                       "baseline_sha256": boot["evidence"]["baseline_sha256"]}
            atomic_write(Path(root) / "controller-binding.json", binding)
            self.assertEqual(receiver.handle(canonical(self.wire(receiver, "bind", 2)))["status"], "ok")
            heartbeat = self.wire(receiver, "heartbeat", 3)
            heartbeat["expires_at"] = time.time() + 9
            receiver.handle(canonical(heartbeat))
            observed = receiver.handle(canonical(self.wire(receiver, "observe", 4)))
            self.assertEqual(observed["status"], "ok")
            self.assertEqual(len(commands), before)
            restored = receiver.handle(canonical(self.wire(receiver, "recover", 5)))
            self.assertEqual(restored["status"], "ok")
            self.assertFalse(rules or routes)
            self.assertTrue(restored["evidence"]["restoration"]["original_forwarding_verified"])
            self.assertFalse(json.loads((Path(root) / "journal.json").read_bytes())["runtime"]["owned"])
            self.assertEqual(canonical(boot), original_receipt)
            self.assertEqual(canonical(receiver.handle(canonical(request))), original_receipt)
            journal = json.loads((Path(root) / "journal.json").read_bytes())
            self.assertEqual(canonical(journal["receipts"][request["request_id"]]["response"]), original_receipt)
            boot["evidence"]["action_paths"]["owned"].clear()
            replay = receiver.handle(canonical(request))
            self.assertEqual(canonical(replay), original_receipt)
            replay["evidence"]["baseline"]["tables"].clear()
            self.assertEqual(canonical(receiver.handle(canonical(request))), original_receipt)
            os.close(receiver.claim)

    def test_pause_boundary_stop_ack_is_prompt_and_prevents_original_add(self):
        with tempfile.TemporaryDirectory() as root:
            receiver, rules, routes, commands = self.receiver(Path(root))
            receiver.runtime.capture_baseline()
            receiver.phase = "executing"
            receiver.current = Request.parse(canonical({**self.request(), "policy_sha256": receiver.policy_hash}))
            receiver.operation_start = 0
            atomic_write(Path(root) / "authority.json", {"policy_sha256": receiver.policy_hash,
                "fence": 2, "expires_at": time.time() + 9, "authorized": True})
            atomic_write(Path(root) / "failpoint.json", {"policy_sha256": receiver.policy_hash,
                "operation": "execute", "ordinal": 1, "when": "before", "effect": "pause", "timeout_seconds": 2})
            failures = []

            def apply():
                with receiver.lock:
                    try:
                        receiver.runtime.routing.change(1)
                    except ValueError as exc:
                        failures.append(str(exc))

            worker = threading.Thread(target=apply)
            worker.start()
            deadline = time.monotonic() + 2
            while not (Path(root) / "boundary.json").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            began = time.monotonic()
            stopped = receiver.handle(canonical(self.wire(receiver, "stop", 10)))
            self.assertLess(time.monotonic() - began, .2)
            self.assertTrue(stopped["evidence"]["stop_latched"])
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(failures)
            self.assertFalse(rules or routes)
            self.assertFalse(any(args[:3] == ["ip", "route", "add"] for _, args in commands))
            os.close(receiver.claim)

    def request(self, **changes):
        return dict(version=VERSION, request_id=str(uuid4()), fence=1,
                    policy_sha256="a" * 64, expires_at=time.time() + 10,
                    operation="execute", action=1, duration_seconds=10, token="b" * 64, **changes)

    def test_strict_request_no_boolean_actions_or_duplicate_fields(self):
        request = self.request()
        Request.parse(canonical(request))
        for key, value in (("action", True), ("fence", True), ("duration_seconds", float("inf")),
                           ("expires_at", "tomorrow"), ("unexpected", "field")):
            with self.assertRaises((ValueError, TypeError)):
                Request.parse(json.dumps({**request, key: value}).encode())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            Request.parse(b'{"version":1,"version":2}')

    def test_receiver_persisted_replay_and_restart_fence(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            policy = dict(version=POLICY_VERSION, image_id=IMAGE, source_sha256=SOURCE, model_sha256=MODEL,
                container_id="c" * 64, owner_label="test-owner", seed=9001, scenario="path0",
                expires_at=time.time() + 100, max_duration_seconds=30, heartbeat_seconds=10,
                min_dwell_seconds=0, max_observation_age_seconds=30, min_goodput_mbps=0,
                max_loss_fraction=1, max_rtt_ms=1000, wrapper_sha256=wrapper_digest(),
                controller_policy_sha256="d" * 64)
            atomic_write(directory / "policy.json", policy)
            sha = hashlib.sha256((directory / "policy.json").read_bytes()).hexdigest()
            (directory / "token").write_text("b" * 64)
            (directory / "token").chmod(0o600)
            runtime, _, _, _ = fixture()
            receiver = Receiver(directory, directory / "policy.json", sha,
                                directory / "token", runtime.experiment)
            request = {**self.request(), "policy_sha256": sha, "operation": "stop",
                       "action": None, "duration_seconds": 0}
            result = receiver.handle(canonical(request))
            self.assertEqual(receiver.handle(canonical(request)), result)
            self.assertTrue((directory / "STOP").exists())
            self.assertTrue(result["evidence"]["stop_latched"])
            self.assertEqual(load_policy(directory / "policy.json", sha), policy)
            os.close(receiver.claim)

    def test_expiry_watchdog_restores_without_controller_request(self):
        runtime, _, _, _ = fixture()
        baseline = runtime.capture_baseline()
        runtime.routing.change(1)
        # Receiver lifecycle logic with disk publication captured separately; the
        # real original matched action and readback run against offline kernel fixture.
        receiver = Receiver.__new__(Receiver)
        receiver.runtime = runtime
        receiver.lock = threading.RLock()
        receiver.shutdown = threading.Event()
        receiver.active_until = time.time() - 1
        receiver.stopped = False
        receiver.latch_stop = lambda *_: setattr(receiver, "stopped", True)
        receiver.restoration = None
        receiver.phase = "holding"
        receiver.persist = Mock()
        receiver.authority = Mock(side_effect=ValueError("action_expired"))
        worker = threading.Thread(target=receiver.watchdog)
        worker.start()
        try:
            deadline = time.monotonic() + 2
            while receiver.active_until is not None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIsNone(receiver.active_until)
            self.assertEqual(receiver.phase, "restored")
            self.assertEqual(receiver.restoration["readback"], baseline)
            self.assertTrue(receiver.stopped)
        finally:
            receiver.shutdown.set()
            worker.join(2)


if __name__ == "__main__":
    unittest.main()
