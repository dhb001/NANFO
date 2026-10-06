import copy
import fcntl
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from emulation.actions import Actions, tcRead
from emulation.lab_contracts import sign_command
from emulation.mailbox import Mailbox, planHash, safeRead, safeWrite, validateEnvelope, validatePlan

KEY = b"0123456789abcdef" * 4


def publish(path, cmd, key=KEY):
    """The provisioned writer: C15-signed canonical command envelope."""
    safeWrite(path, sign_command(key, cmd))


def command():
    plan = {
        "operation": "reroute",
        "source_host": "h1",
        "destination_host": "h3",
        "paths": [["access1", "dist1", "core", "dist2", "access2"]],
        "weights": [],
        "rate_mbps": None,
        "dscp": None,
    }
    return {
        "version": 1,
        "execution_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "binding_digest": "a" * 64,
        "plan_hash": planHash(plan),
        "fence": 1,
        "deadline": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
        "dispatch_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=4)).isoformat(),
        "operation": "execute",
        "plan": plan,
    }


class ValidationTests(unittest.TestCase):
    def testExactContract(self):
        cmd = command()
        validateEnvelope(cmd, cmd["execution_id"] + ".json")
        validatePlan(cmd["plan"])
        self.assertEqual(planHash(cmd["plan"]), planHash(dict(reversed(list(cmd["plan"].items())))))
        for key, value in (
            ("version", True),
            ("fence", True),
            ("fence", 0),
            ("run_id", "../x"),
            ("deadline", "2026-09-09T01:00:00"),
            ("operation", "shell"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validateEnvelope({**cmd, key: value}, cmd["execution_id"] + ".json")
        with self.assertRaises(ValueError):
            validateEnvelope({**cmd, "inject_failure": True}, cmd["execution_id"] + ".json")

    def testPlanBounds(self):
        plan = command()["plan"]
        invalid = [
            {**plan, "operation": "vlan"},
            {**plan, "dscp": True},
            {**plan, "dscp": 64},
            {**plan, "paths": [["dist1", "access2"]]},
            {**plan, "paths": [["access1", "core", "access2"]]},
            {**plan, "paths": [["access1", "dist1", "access1", "dist2", "access2"]]},
            {**plan, "weights": [0]},
            {**plan, "rate_mbps": 5},
            {**plan, "source_host": "$(id)"},
            {**plan, "unknown": None},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validatePlan(value)
        for op in ("shape", "police"):
            for rate in (0, 21, float("nan"), True, "5"):
                with self.assertRaises(ValueError):
                    validatePlan({**plan, "operation": op, "paths": [], "rate_mbps": rate})

    def testSafeFiles(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            safeWrite(root / "value.json", {"ok": True})
            (root / "link.json").symlink_to(root / "value.json")
            with self.assertRaises(OSError):
                safeRead(root / "link.json")
            with self.assertRaises(ValueError):
                safeWrite(root / "link.json", {})
            os.link(root / "value.json", root / "hard.json")
            with self.assertRaises(ValueError):
                safeRead(root / "hard.json")
            with (
                patch(
                    "emulation.mailbox.os.fstat",
                    return_value=SimpleNamespace(st_mode=0, st_nlink=1, st_size=0),
                ),
                self.assertRaises(ValueError),
            ):
                safeRead(root / "value.json")
        with self.assertRaises(ValueError):
            json.loads(
                '{"x":1,"x":2}',
                object_pairs_hook=__import__(
                    "emulation.mailbox", fromlist=["uniqueObject"]
                ).uniqueObject,
            )

    def testPinnedTcText(self):
        with patch(
            "emulation.actions.cli",
            return_value="class htb 5:1 root leaf 10: prio 0 rate 100Mbit ceil 100Mbit burst 15337b cburst 1600b \n",
        ):
            self.assertEqual(tcRead("class", "access2-eth3")[0]["options"]["rate"], 12500000)
        with (
            patch("emulation.actions.cli", return_value="not a class"),
            self.assertRaises(ValueError),
        ):
            tcRead("class", "access2-eth3")


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.commands, self.results = root / "commands", root / "results"
        self.commands.mkdir()
        self.results.mkdir()
        self.cmd = command()
        self.driver = Mock(lab=SimpleNamespace(stopping=False))
        self.driver.prepare.return_value = {
            "before": {},
            "flows": [],
            "groups": [],
            "meters": [],
            "shapes": [],
        }
        self.driver.verify.return_value = {"actual": True}
        self.driver.rollback.return_value = {"actual": False}
        self.driver.probe.return_value = {"received": 3}
        self.driver.capture.return_value = {"before_restore": True}
        self.driver.reconcile.return_value = {"reconciled": True}
        self.box = self.newBox()

    def newBox(self):
        return Mailbox(
            self.driver,
            self.cmd["run_id"],
            self.cmd["binding_digest"],
            self.commands,
            self.results,
            command_key=KEY,
        )

    def tearDown(self):
        self.box.close()
        self.temp.cleanup()

    def testDurablePrepareDuplicateLostResultAndLateCancel(self):
        def apply(prepared, check):
            self.assertEqual(
                self.box.load()["records"][self.cmd["execution_id"]]["phase"], "applying"
            )
            check()

        self.driver.apply.side_effect = apply
        self.assertEqual(self.box.handle(self.cmd)["status"], "completed")
        (self.results / (self.cmd["execution_id"] + ".json")).unlink()
        self.box.close()
        self.box = self.newBox()
        self.assertEqual(self.box.handle({**self.cmd, "fence": 2})["status"], "completed")
        self.assertEqual(self.driver.apply.call_count, 1)
        cancelled = self.box.handle({**self.cmd, "fence": 3, "operation": "cancel"})
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(cancelled["rollback"]["verified"])
        self.assertIsNone(self.box.load()["active"])

    def testFailureAndUncertaintyBlock(self):
        self.driver.apply.side_effect = RuntimeError("injected")
        self.driver.rollback.side_effect = RuntimeError("rollback failed")
        self.assertEqual(self.box.handle(self.cmd)["status"], "uncertain")
        other = {**self.cmd, "execution_id": str(uuid.uuid4())}
        self.assertIn("uncertain", self.box.handle(other)["failure_reason"])
        self.assertEqual(self.driver.apply.call_count, 1)

    def testCrashRecoveryNeverRepeatsMutation(self):
        self.driver.apply.side_effect = SystemExit(77)
        with self.assertRaises(SystemExit):
            self.box.handle(self.cmd)
        self.box.close()
        self.box = self.newBox()
        result = self.box.handle({**self.cmd, "fence": 2})
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["rollback"]["verified"])
        self.assertEqual(self.driver.apply.call_count, 1)

    def testCancelledDuringAction(self):
        def apply(prepared, check):
            publish(
                self.commands / (self.cmd["execution_id"] + ".json"),
                {**self.cmd, "operation": "cancel", "fence": 2},
            )
            check()

        self.driver.apply.side_effect = apply
        result = self.box.handle(self.cmd)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["fence"], 2)
        self.assertTrue(result["rollback"]["verified"])

    def testImmutableFenceDeadlineRunHash(self):
        self.box.handle(self.cmd)
        for changes in (
            {"fence": 0},
            {"deadline": "2000-01-01T00:00:00Z"},
            {"run_id": str(uuid.uuid4())},
            {"plan_hash": "b" * 64},
        ):
            candidate = {**self.cmd, **changes}
            if changes.get("fence") == 0 or "deadline" in changes:
                with self.assertRaises(ValueError):
                    self.box.handle(candidate)
            else:
                self.assertEqual(self.box.handle(candidate)["status"], "failed")
        self.assertEqual(self.driver.apply.call_count, 1)

    def testConcurrentLock(self):
        other = self.newBox()
        try:
            fcntl.flock(other.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.box.handle(self.cmd)
            self.driver.apply.assert_not_called()
        finally:
            other.close()

    def testHoldDownAndRestoreSelector(self):
        self.box.handle(self.cmd)
        other = copy.deepcopy(self.cmd)
        other["execution_id"] = str(uuid.uuid4())
        self.assertIn("hold-down", self.box.handle(other)["failure_reason"])
        other["plan"].update(operation="restore", paths=[], source_host="h2")
        other["execution_id"] = str(uuid.uuid4())
        other["plan_hash"] = planHash(other["plan"])
        with patch("emulation.mailbox.HOLD_DOWN", 0):
            self.assertIn("matching", self.box.handle(other)["failure_reason"])

    def testFailedRestoreReinstatesItsBeforeImage(self):
        self.box.handle(self.cmd)
        restore = copy.deepcopy(self.cmd)
        restore["execution_id"] = str(uuid.uuid4())
        restore["plan"].update(operation="restore", paths=[])
        restore["plan_hash"] = planHash(restore["plan"])
        self.driver.rollback.side_effect = [RuntimeError("partial restore"), {"baseline": True}]
        with patch("emulation.mailbox.HOLD_DOWN", 0):
            result = self.box.handle(restore)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["rollback"]["verified"])
        self.assertEqual(self.box.load()["active"], self.cmd["execution_id"])
        self.assertEqual(self.driver.apply.call_count, 2)

    def testFreshRunNeverReappliesInterruptedRestore(self):
        self.box.handle(self.cmd)
        state = self.box.load()
        original = state["records"][self.cmd["execution_id"]]
        restoreId = str(uuid.uuid4())
        state["records"][restoreId] = {
            "command": {**self.cmd, "execution_id": restoreId},
            "phase": "rolling_back",
            "prepared": original["prepared"],
            "restores": self.cmd["execution_id"],
        }
        self.box.save(state)
        self.box.runId = str(uuid.uuid4())
        self.box.recover(self.box.load())
        self.assertEqual(self.driver.apply.call_count, 1)
        self.driver.rollback.assert_not_called()
        self.driver.reconcile.assert_called_with()
        self.assertIsNone(self.box.load()["active"])

    def testBindingMismatchRecoveryNeverMutates(self):
        self.driver.apply.side_effect = SystemExit(77)
        with self.assertRaises(SystemExit):
            self.box.handle(self.cmd)
        self.box.digest = "b" * 64
        self.driver.reconcile.side_effect = RuntimeError("owned state exists")
        self.box.recover(self.box.load())
        self.driver.rollback.assert_not_called()
        self.assertEqual(self.driver.apply.call_count, 1)
        self.assertTrue(self.box.load()["blocked"])

    def testNoMutationRejectionThenRestore(self):
        self.box.handle(self.cmd)
        other = {**self.cmd, "execution_id": str(uuid.uuid4())}
        with patch("emulation.mailbox.HOLD_DOWN", 0):
            result = self.box.handle(other)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["verification"]["no_mutation_verified"])
            restore = copy.deepcopy(other)
            restore["execution_id"] = str(uuid.uuid4())
            restore["plan"].update(operation="restore", paths=[])
            restore["plan_hash"] = planHash(restore["plan"])
            self.assertEqual(self.box.handle(restore)["status"], "completed")
            self.assertEqual(self.box.handle(other)["status"], "failed")
        self.assertEqual(self.driver.apply.call_count, 1)

    def testFirstCancelWithExpiredDeadlineCannotExecuteLater(self):
        cmd = {
            **self.cmd,
            "deadline": "2000-01-01T00:00:00Z",
            "dispatch_expires_at": "2000-01-01T00:00:00Z",
            "operation": "cancel",
        }
        result = self.box.handle(cmd)
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(result["verification"]["no_mutation_verified"])
        self.assertTrue(result["verification"]["deadline_expired"])
        self.assertEqual(self.box.handle({**cmd, "operation": "execute"})["status"], "cancelled")
        self.driver.apply.assert_not_called()

    def testNoMutationReadbackFailureBlocks(self):
        self.driver.reconcile.side_effect = RuntimeError("unknown owned state")
        result = self.box.handle({**self.cmd, "operation": "cancel"})
        self.assertEqual(result["status"], "uncertain")
        self.assertNotIn("no_mutation_verified", result["verification"])
        self.assertTrue(self.box.load()["blocked"])

    def testDispatchExpiryAfterReadbackPreventsPrepare(self):
        expires = datetime.now(timezone.utc).timestamp() + 4
        self.cmd["dispatch_expires_at"] = datetime.fromtimestamp(expires, timezone.utc).isoformat()
        with patch(
            "emulation.mailbox.time.time", side_effect=[expires - 1, expires + 1, expires + 1]
        ):
            result = self.box.handle(self.cmd)
        self.assertTrue(result["verification"]["no_mutation_verified"])
        self.driver.apply.assert_not_called()
        self.assertNotIn("prepared", self.box.load()["records"][self.cmd["execution_id"]])

    def testExpiredAndOverlongWireCannotMutate(self):
        for seconds in (-1, 6):
            cmd = {
                **self.cmd,
                "execution_id": str(uuid.uuid4()),
                "dispatch_expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=seconds)
                ).isoformat(),
            }
            result = self.box.handle(cmd)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["verification"]["no_mutation_verified"])
        self.driver.prepare.assert_not_called()
        self.driver.apply.assert_not_called()

    def testPreparedMayContinueAndReplayAfterDispatchExpiry(self):
        expires = datetime.now(timezone.utc).timestamp() + 4
        self.cmd["dispatch_expires_at"] = datetime.fromtimestamp(expires, timezone.utc).isoformat()
        with patch(
            "emulation.mailbox.time.time",
            side_effect=[expires - 2, expires - 1, expires + 1, expires + 1, expires + 1],
        ):
            self.assertEqual(self.box.handle(self.cmd)["status"], "completed")
        with patch("emulation.mailbox.time.time", return_value=expires + 2):
            self.assertEqual(self.box.handle(self.cmd)["status"], "completed")
        self.assertEqual(self.driver.apply.call_count, 1)
        changed = {
            **self.cmd,
            "dispatch_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat(),
        }
        self.assertIn("immutable", self.box.handle(changed)["failure_reason"])

    def testCancelRestoredPolicyPreservesNewPolicy(self):
        with patch("emulation.mailbox.HOLD_DOWN", 0):
            self.box.handle(self.cmd)
            restore = copy.deepcopy(self.cmd)
            restore["execution_id"] = str(uuid.uuid4())
            restore["plan"].update(operation="restore", paths=[])
            restore["plan_hash"] = planHash(restore["plan"])
            self.box.handle(restore)
            newer = {**self.cmd, "execution_id": str(uuid.uuid4())}
            self.box.handle(newer)
            calls = self.driver.rollback.call_count
            result = self.box.handle({**self.cmd, "operation": "cancel"})
            self.assertEqual(result["status"], "cancelled")
            self.assertTrue(result["verification"]["already_restored"])
            self.assertTrue(result["verification"]["no_mutation_verified"])
            self.assertEqual(self.driver.rollback.call_count, calls)
            self.assertEqual(self.box.load()["active"], newer["execution_id"])
            self.assertEqual(
                self.box.handle({**restore, "execution_id": str(uuid.uuid4())})["status"],
                "completed",
            )

    def testOldRunRecoveryThenPollPreservesProof(self):
        self.driver.apply.side_effect = SystemExit(77)
        with self.assertRaises(SystemExit):
            self.box.handle(self.cmd)
        self.box.runId = str(uuid.uuid4())
        self.box.recover(self.box.load())
        proof = safeRead(self.results / (self.cmd["execution_id"] + ".json"))
        self.assertTrue(proof["rollback"]["verified"])
        publish(self.commands / (self.cmd["execution_id"] + ".json"), self.cmd)
        self.box.poll()
        self.assertEqual(safeRead(self.results / (self.cmd["execution_id"] + ".json")), proof)

    def testRecoveredCompletedOldRunCancelFreshlyProvesNoMutation(self):
        completed = self.box.handle(self.cmd)
        self.box.runId = str(uuid.uuid4())
        self.box.recover(self.box.load())
        self.driver.reconcile.reset_mock()
        cancelled = self.box.handle({**self.cmd, "operation": "cancel", "fence": 2})
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["run_id"], self.cmd["run_id"])
        self.assertEqual(cancelled["plan_hash"], self.cmd["plan_hash"])
        self.assertEqual(cancelled["fence"], 2)
        self.assertTrue(cancelled["verification"]["no_mutation_verified"])
        self.assertEqual(cancelled["verification"]["current_run_id"], self.box.runId)
        self.assertEqual(
            cancelled["verification"]["readback_sha256"], planHash({"reconciled": True})
        )
        self.driver.reconcile.assert_called_once_with(None)
        self.driver.rollback.assert_not_called()
        record = self.box.load()["records"][self.cmd["execution_id"]]
        self.assertEqual(record["obsolete_result"], completed)
        self.box.handle({**self.cmd, "operation": "cancel", "fence": 3})
        self.assertEqual(self.driver.reconcile.call_count, 2)

    def testRecoveredOldCancelPreservesUnrelatedCurrentActivePolicy(self):
        self.box.handle(self.cmd)
        self.box.runId = str(uuid.uuid4())
        self.box.recover(self.box.load())
        newer = {**command(), "run_id": self.box.runId}
        with patch("emulation.mailbox.HOLD_DOWN", 0):
            self.assertEqual(self.box.handle(newer)["status"], "completed")
        before = self.box.load()["records"][newer["execution_id"]]
        self.driver.reconcile.reset_mock()
        cancelled = self.box.handle({**self.cmd, "operation": "cancel", "fence": 2})
        self.assertEqual(cancelled["status"], "cancelled")
        self.driver.reconcile.assert_called_once_with(before["prepared"])
        self.assertEqual(self.box.load()["active"], newer["execution_id"])
        self.assertEqual(self.box.load()["records"][newer["execution_id"]], before)
        self.assertEqual(self.driver.apply.call_count, 2)
        self.driver.rollback.assert_not_called()

    def testObsoleteCancelCannotReuseOldProofOrBypassIdentity(self):
        self.box.handle(self.cmd)
        self.box.runId = str(uuid.uuid4())
        self.box.recover(self.box.load())
        result = self.box.handle({**self.cmd, "operation": "cancel", "plan_hash": "b" * 64})
        self.assertEqual(result["status"], "failed")
        self.driver.reconcile.side_effect = RuntimeError("reserved resources remain")
        result = self.box.handle({**self.cmd, "operation": "cancel", "fence": 2})
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["verification"].get("no_mutation_verified"))
        self.assertTrue(self.box.load()["blocked"])
        self.driver.rollback.assert_not_called()

    def testCancelOnlyPollNeverDispatchesPendingExecute(self):
        publish(self.commands / (self.cmd["execution_id"] + ".json"), self.cmd)
        self.box.poll(cancel_only=True)
        self.driver.apply.assert_not_called()
        self.assertNotIn(self.cmd["execution_id"] + ".json", self.box.seen)
        self.box.poll()
        self.assertEqual(self.driver.apply.call_count, 1)

    def testPollSeparatesMetadataAndRejectsCapacityDurably(self):
        for _ in range(33):
            cmd = {**self.cmd, "execution_id": str(uuid.uuid4()), "operation": "cancel"}
            publish(self.commands / (cmd["execution_id"] + ".json"), cmd)
            safeWrite(self.commands / ("." + cmd["execution_id"] + ".lock"), {})
            safeWrite(self.commands / ("." + cmd["execution_id"] + ".tmp"), {})
        self.box.poll()
        records = self.box.load()["records"]
        self.assertEqual(len(records), 33)
        rejected = [r for r in records.values() if r["result"]["status"] == "failed"]
        self.assertEqual(len(rejected), 1)
        self.assertTrue(rejected[0]["result"]["verification"]["no_mutation_verified"])
        self.driver.apply.assert_not_called()
        for index in range(9):
            safeWrite(self.commands / f"unknown{index}", {})
        self.box.handle = Mock()
        self.box.poll()
        self.box.handle.assert_not_called()


class DriverTests(unittest.TestCase):
    def testReconcileCurrentPolicyRejectsAdditionalReservedResources(self):
        prepared = {"flows": [["access1", "expected"]], "groups": [], "meters": [], "shapes": []}
        actual = {
            "switches": {
                "access1": {
                    "flows": "cookie=0x4e414e4600000001,expected",
                    "groups": "",
                    "meters": "",
                }
            },
            "queues": {"access1-eth3": {"class": [], "qdisc": [], "filter": []}},
        }
        driver = Actions(None)
        driver.verify = Mock(return_value=actual)
        self.assertEqual(driver.reconcile(prepared), actual)
        for fault in ("flow", "group", "queue"):
            bad = copy.deepcopy(actual)
            if fault == "flow":
                bad["switches"]["access1"]["flows"] += "\ncookie=0x4e414e4600000001,old"
            elif fault == "group":
                from emulation.actions import RESOURCE

                bad["switches"]["access1"]["groups"] = f"group_id={RESOURCE}"
            else:
                bad["queues"]["access1-eth3"]["filter"] = [{"pref": 30000}]
            driver.verify.return_value = bad
            with self.assertRaises(RuntimeError):
                driver.reconcile(prepared)

    def testDscpMustMatchSameConcreteFilter(self):
        shape = {"src": "10.77.0.1", "dst": "10.77.0.3", "dscp": 10}
        row = {
            "kind": "flower",
            "protocol": "ip",
            "pref": 30000,
            "options": {
                "handle": 1,
                "classid": "5:100",
                "keys": {
                    "eth_type": "ipv4",
                    "src_ip": "10.77.0.1",
                    "dst_ip": "10.77.0.3",
                    "ip_tos": 40,
                    "ip_tos_mask": 252,
                },
            },
        }
        Actions.verifySelector([row], shape)
        for key, value in (
            ("ip_tos", 44),
            ("ip_tos_mask", 255),
            ("src_ip", "10.77.0.10"),
            ("dst_ip", "10.77.0.30"),
        ):
            wrong = copy.deepcopy(row)
            wrong["options"]["keys"][key] = value
            with self.assertRaises(RuntimeError):
                Actions.verifySelector([wrong], shape)
        with self.assertRaises(RuntimeError):
            Actions.verifySelector([row, copy.deepcopy(row)], shape)

    def testRollbackOwnsOnlyDedicatedCookie(self):
        driver = Actions(None)
        driver.of = Mock()
        driver.verify = Mock(return_value={})
        driver.rollback(
            {"flows": [["access1", "ignored"]], "groups": [], "meters": [], "shapes": []}
        )
        self.assertIn("cookie=0x4e414e4600000001/-1", driver.of.call_args.args[2])
