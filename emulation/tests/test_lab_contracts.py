"""ADR-028 shared lab contracts, C15 command MACs and 0640 publication (stdlib only)."""

import ast
import json
import os
import stat
import tarfile
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from emulation import lab_contracts as contracts
from emulation.lab_contracts import (
    ACTION_IDS,
    ACTION_PATHS,
    COMMAND_KEY_ENV,
    RESERVED_TABLES,
    ROUTE_PAIRS,
    ROUTERS,
    TOPOLOGY_ID,
    UDP_DATAGRAM_BYTES,
    action_map,
    atomic_publish,
    canonical,
    command_mac,
    expected_nodes,
    load_command_key,
    sign_command,
    validate_route_readback,
    verify_command,
)
from emulation.mailbox import Mailbox, safeRead, safeWrite
from emulation.tests.test_actions import KEY, command

ROOT = Path(__file__).resolve().parents[2]
AI_CONTRACTS = ROOT / "ai-engine/src/nanfo_routing/contracts.py"
FROZEN_TARBALL = ROOT / "emulation/frozen/adr015-prechange-v4-source.tar.gz"
FROZEN_RECOVERY = ROOT / "ai-engine/artifacts/adr024-qualified-001/recovery/emulation"


def assignments(source):
    """Literal module-level assignments of a file, without importing (read-only drift)."""
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return values


def frozen_constants(read):
    matched, ospf = assignments(read("matched.py")), assignments(read("ospf.py"))
    workloads, topology = assignments(read("workloads.py")), assignments(read("topology.py"))
    return {"tables": matched["TABLES"], "pairs": matched["PAIRS"], "paths": ospf["PATHS"],
            "routers": tuple(row["name"] for row in topology["SWITCHES"]),
            "packet_bytes": workloads["PACKET_BYTES"], "topology_id": topology["TOPOLOGY_ID"]}


class DriftTests(unittest.TestCase):
    def assertFrozen(self, frozen):
        self.assertEqual(frozen["tables"], RESERVED_TABLES)
        self.assertEqual(frozen["pairs"], ROUTE_PAIRS)
        self.assertEqual(frozen["paths"], ACTION_PATHS)
        self.assertEqual(frozen["routers"], ROUTERS)
        self.assertEqual(frozen["packet_bytes"], UDP_DATAGRAM_BYTES)
        self.assertEqual(frozen["topology_id"], TOPOLOGY_ID)

    @unittest.skipUnless(FROZEN_TARBALL.is_file(), "frozen v4 source archive not present")
    def test_frozen_v4_archive_members_match_contract(self):
        with tarfile.open(FROZEN_TARBALL) as archive:
            def read(name):
                return archive.extractfile("emulation/" + name).read().decode()

            self.assertFrozen(frozen_constants(read))

    @unittest.skipUnless(FROZEN_RECOVERY.is_dir(), "qualified v4 recovery source not present")
    def test_qualified_v4_recovery_source_matches_contract(self):
        self.assertFrozen(frozen_constants(lambda name: (FROZEN_RECOVERY / name).read_text()))

    @unittest.skipUnless(AI_CONTRACTS.is_file(), "ai-engine contracts not present")
    def test_ai_engine_routing_contract_matches(self):
        values = assignments(AI_CONTRACTS.read_text())
        self.assertEqual(values["ACTION_MAP"], [list(path) for path in ACTION_PATHS])
        self.assertEqual(values["NODES"], list(ROUTERS))
        self.assertIn(f'"topology_id": "{TOPOLOGY_ID}"', AI_CONTRACTS.read_text())

    def test_current_lab_modules_use_the_shared_contract(self):
        from emulation import (
            autonomous_contract,
            autonomous_frr,
            matched,
            ospf,
            topology,
            workloads,
        )

        self.assertEqual(matched.TABLES, RESERVED_TABLES)
        self.assertEqual(autonomous_frr.TABLES, RESERVED_TABLES)
        self.assertEqual(matched.PAIRS, ROUTE_PAIRS)
        self.assertEqual(autonomous_frr.PAIRS, ROUTE_PAIRS)
        self.assertEqual(ospf.PATHS, ACTION_PATHS)
        self.assertEqual(autonomous_contract.PATHS, ACTION_PATHS)
        self.assertEqual(autonomous_contract.action_map(), action_map())
        self.assertEqual(ospf.ROUTERS, ROUTERS)
        self.assertEqual(set(autonomous_contract.ROUTERS), set(ROUTERS))
        self.assertEqual(workloads.PACKET_BYTES, UDP_DATAGRAM_BYTES)
        self.assertEqual(topology.TOPOLOGY_ID, TOPOLOGY_ID)

    def test_contract_digest_is_versioned_and_stable(self):
        document = contracts.contract_document()
        self.assertEqual(document["version"], "nanfo.lab-contracts/v1")
        self.assertEqual(contracts.contract_sha256(), contracts.digest(document))
        self.assertEqual(ACTION_IDS, ("route0", "route1"))
        self.assertEqual(len(contracts.reserved_slots()), len(ROUTERS) * len(RESERVED_TABLES))


class RouteValidatorTests(unittest.TestCase):
    def test_expected_nodes_and_exact_readback(self):
        self.assertEqual(expected_nodes(1, "h1", "h3"), ["h1", "access1", "dist2", "access2", "h3"])
        self.assertEqual(expected_nodes(1, "h3", "h1"), ["h3", "access2", "dist2", "access1", "h1"])
        paths = {f"{a}->{b}": {"action": 0, "nodes": expected_nodes(0, a, b)} for a, b in (("h1", "h3"), ("h3", "h1"))}
        self.assertTrue(validate_route_readback(paths, 0))
        self.assertFalse(validate_route_readback(paths, 1))
        wrong = {**paths, "h3->h1": {"action": 0, "nodes": list(reversed(paths["h3->h1"]["nodes"]))}}
        self.assertFalse(validate_route_readback(wrong, 0))
        self.assertFalse(validate_route_readback(None, 0))
        for action in (True, 2, -1, "0"):
            with self.assertRaises(ValueError):
                expected_nodes(action, "h1", "h3")
        with self.assertRaises(ValueError):
            expected_nodes(0, "h2", "h4")


class CanonicalTests(unittest.TestCase):
    def test_canonical_is_sorted_compact_ascii_and_strict(self):
        value = {"b": [1, 2.5, None], "a": "\u00e9", "c": {"z": True, "y": False}}
        self.assertEqual(canonical(value), b'{"a":"\\u00e9","b":[1,2.5,null],"c":{"y":false,"z":true}}')
        with self.assertRaises(ValueError):
            canonical({"x": float("nan")})


class KeyFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def key(self, data=b"k" * 64, mode=0o400, name="lab_command_key"):
        path = self.root / name
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def test_protected_key_file_and_single_trailing_newline(self):
        self.assertEqual(load_command_key(str(self.key())), b"k" * 64)
        self.assertEqual(load_command_key(str(self.key(b"x" * 32 + b"\n", 0o600, "b"))), b"x" * 32)
        with patch.dict(os.environ, {COMMAND_KEY_ENV: str(self.key(name="c"))}):
            self.assertEqual(load_command_key(), b"k" * 64)

    def test_unprotected_short_linked_or_unconfigured_keys_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "unconfigured"):
            load_command_key()
        for mode in (0o640, 0o644, 0o440, 0o700, 0o604):
            with self.subTest(mode=oct(mode)), self.assertRaisesRegex(ValueError, "unprotected"):
                load_command_key(str(self.key(mode=mode, name=f"m{mode}")))
        # Unreadable for a normal user; a root build step can open it but it is still unprotected.
        with self.assertRaisesRegex(ValueError, "unavailable|unprotected"):
            load_command_key(str(self.key(mode=0o200, name="write-only")))
        with self.assertRaisesRegex(ValueError, "unprotected"):
            load_command_key(str(self.key(b"k" * 31, name="short")))
        with self.assertRaisesRegex(ValueError, "invalid"):
            load_command_key(str(self.key(b"k" * 31 + b"\n", name="short-newline")))
        with self.assertRaisesRegex(ValueError, "invalid"):
            load_command_key(str(self.key(b"k" * 20 + b"\n" + b"k" * 20, name="inner-newline")))
        target = self.key(name="target")
        (self.root / "link").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            load_command_key(str(self.root / "link"))
        os.link(target, self.root / "hard")
        with self.assertRaisesRegex(ValueError, "unprotected"):
            load_command_key(str(target))
        with self.assertRaisesRegex(ValueError, "not_absolute"):
            load_command_key("relative/key")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            load_command_key(str(self.root / "missing"))

    def test_foreign_owner_key_is_refused(self):
        path = self.key(name="foreign")
        with patch.object(contracts.os, "geteuid", return_value=os.geteuid() + 1), \
                self.assertRaisesRegex(ValueError, "unprotected"):
            load_command_key(str(path))


class CommandMacTests(unittest.TestCase):
    def test_mac_covers_every_field_of_the_canonical_envelope(self):
        cmd = command()
        signed = sign_command(KEY, cmd)
        self.assertEqual(set(signed), {*cmd, "hmac_sha256"})
        self.assertEqual(verify_command(KEY, signed), cmd)
        reordered = dict(reversed(list(signed.items())))
        self.assertEqual(verify_command(KEY, reordered), cmd)
        self.assertEqual(signed["hmac_sha256"], command_mac(KEY, dict(reversed(list(cmd.items())))))
        for key, value in (("fence", 2), ("operation", "cancel"), ("run_id", str(uuid.uuid4())),
                           ("plan", {**cmd["plan"], "dscp": 10}), ("extra", True)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "command_mac_invalid"):
                verify_command(KEY, {**signed, key: value})
        with self.assertRaisesRegex(ValueError, "command_mac_invalid"):
            verify_command(b"z" * 32, signed)
        for mac in (None, "", "A" * 64, "0" * 63, 7):
            with self.subTest(mac=mac), self.assertRaisesRegex(ValueError, "command_mac_missing"):
                verify_command(KEY, {**cmd, "hmac_sha256": mac})
        with self.assertRaisesRegex(ValueError, "command_mac_missing"):
            verify_command(KEY, cmd)
        with self.assertRaises(ValueError):
            command_mac(b"short", cmd)
        with self.assertRaises(ValueError):
            command_mac(KEY, signed)


class PublicationTests(unittest.TestCase):
    def test_publication_is_0640_with_the_parent_group_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            safeWrite(root / "result.json", {"ok": True})
            info = (root / "result.json").stat()
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o640)
            self.assertEqual(info.st_gid, root.stat().st_gid)
            (root / "link.json").symlink_to(root / "result.json")
            with self.assertRaises(ValueError):
                atomic_publish(root / "link.json", b"{}")
            with self.assertRaises(ValueError):
                atomic_publish(root / "big.json", b"x" * 10, limit=5)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["link.json", "result.json"])

    def test_foreign_parent_group_is_assigned_and_failure_is_not_silent(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            real = os.stat(str(root))
            fake = os.stat_result((*real[:5], real.st_gid + 7, *real[6:]))
            calls = []
            with patch.object(contracts.os, "stat", return_value=fake), \
                    patch.object(contracts.os, "fchown", side_effect=lambda fd, uid, gid: calls.append((uid, gid))):
                atomic_publish(root / "a.json", b"{}")
            self.assertEqual(calls, [(-1, real.st_gid + 7)])
            with patch.object(contracts.os, "stat", return_value=fake), \
                    patch.object(contracts.os, "fchown", side_effect=PermissionError("EPERM")), \
                    self.assertRaises(PermissionError):
                atomic_publish(root / "b.json", b"{}")
            self.assertFalse((root / "b.json").exists())
            self.assertEqual([p.name for p in root.iterdir()], ["a.json"])


class MailboxAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.commands, self.results = root / "commands", root / "results"
        self.commands.mkdir()
        self.results.mkdir()
        self.cmd = command()
        self.box = Mailbox(Mock(lab=Mock(stopping=False)), self.cmd["run_id"], "a" * 64,
                           self.commands, self.results, command_key=KEY)
        self.box.handle = Mock(return_value={"status": "completed"})
        self.path = self.commands / (self.cmd["execution_id"] + ".json")

    def tearDown(self):
        self.box.close()
        self.temp.cleanup()

    def write(self, value):
        self.path.write_bytes(json.dumps(value).encode())
        self.path.chmod(0o640)

    def test_unsigned_forged_or_wrong_key_commands_get_no_result(self):
        for value in (self.cmd, {**sign_command(KEY, self.cmd), "fence": 9},
                      sign_command(b"w" * 32, self.cmd), {**self.cmd, "hmac_sha256": "0" * 64}):
            with self.subTest(value=sorted(value)):
                self.write(value)
                with patch("builtins.print") as printed:
                    self.box.poll()
                self.box.handle.assert_not_called()
                self.assertIn("command_mac", printed.call_args[0][0])
                self.assertFalse((self.results / self.path.name).exists())

    def test_signed_command_is_verified_and_passed_without_its_mac(self):
        self.write(sign_command(KEY, self.cmd))
        self.box.poll()
        self.box.handle.assert_called_once_with(self.cmd)

    def test_group_writable_or_foreign_owner_command_rejected(self):
        self.write(sign_command(KEY, self.cmd))
        self.path.chmod(0o660)
        with patch("builtins.print"):
            self.box.poll()
        self.box.handle.assert_not_called()
        self.path.chmod(0o640)
        real = os.lstat

        def lstat(path, *args, **kwargs):
            info = real(path, *args, **kwargs)
            if str(path) == str(self.commands):
                return os.stat_result((*info[:4], info.st_uid + 1, *info[5:]))
            return info

        with patch("emulation.mailbox.os.lstat", side_effect=lstat), patch("builtins.print") as printed:
            self.box.poll()
        self.box.handle.assert_not_called()
        self.assertIn("provisioned mailbox writer", printed.call_args[0][0])

    def test_mailbox_refuses_to_start_without_a_protected_key(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "unconfigured"):
            Mailbox(Mock(), self.cmd["run_id"], "a" * 64, self.commands, self.results)
        with self.assertRaisesRegex(ValueError, "C15"):
            Mailbox(Mock(), self.cmd["run_id"], "a" * 64, self.commands, self.results, command_key=b"s")
        key = self.commands.parent / "key"
        key.write_bytes(KEY)
        key.chmod(0o400)
        with patch.dict(os.environ, {COMMAND_KEY_ENV: str(key)}):
            box = Mailbox(Mock(), self.cmd["run_id"], "a" * 64, self.commands, self.results)
        self.assertEqual(box.key, KEY)
        box.close()

    def test_cancel_during_action_requires_an_authenticated_update(self):
        self.write(sign_command(KEY, self.cmd))
        self.assertEqual(self.box.readCommand(self.path), self.cmd)
        self.write({**self.cmd, "operation": "cancel", "fence": 2})
        with self.assertRaisesRegex(ValueError, "command_mac_missing"):
            self.box.readCommand(self.path)
        self.assertEqual(safeRead(self.path)["operation"], "cancel")


class StdlibOnlyTests(unittest.TestCase):
    def test_contract_module_parses_as_python39_and_imports_only_stdlib(self):
        source = (ROOT / "emulation/lab_contracts.py").read_text()
        tree = ast.parse(source, feature_version=(3, 9))
        modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                   for alias in node.names}
        modules |= {node.module.split(".")[0] for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module}
        self.assertLessEqual(modules, {"hashlib", "hmac", "json", "os", "re", "stat", "tempfile", "pathlib"})


if __name__ == "__main__":
    unittest.main()
