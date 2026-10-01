"""Frozen live-feed inputs are pin-verified before any byte is imported or loaded (ADR-028)."""

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

import live_feed_evaluate as feed

MODULES = ("__init__", "artifacts", "cli", "contracts", "env", "transport")


def sha(data):
    return hashlib.sha256(data).hexdigest()


class VerifiedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.root = Path(self.directory.name)
        self.marker = self.root / "executed"
        self.source = self.root / "frozen"
        self.source.mkdir()
        pins = {}
        for name in MODULES:
            body = f"from pathlib import Path\nPath({str(self.marker)!r}).touch()\n" if name == "__init__" else ""
            data = f'"""frozen {name}"""\n{body}'.encode()
            (self.source / (name + ".py")).write_bytes(data)
            pins[name + ".py"] = sha(data)
        (self.root / "checkpoint.ptz").write_bytes(b"pinned checkpoint bytes")
        self.plan = dict(source_directory=str(self.source), client_source_sha256=pins,
                         checkpoint=str(self.root / "checkpoint.ptz"),
                         checkpoint_sha256=sha(b"pinned checkpoint bytes"))
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(lambda: [sys.modules.pop(name) for name in list(sys.modules)
                                 if name.startswith("_live_acceptance_frozen")])

    def snapshot(self, plan=None):
        destination = self.root / ("private-" + str(len(list(self.root.glob("private-*")))))
        destination.mkdir(mode=0o700)
        return feed.verified_snapshot(plan or self.plan, destination)

    def test_exact_verified_bytes_are_the_only_ones_imported(self):
        package, checkpoint = self.snapshot()
        self.assertFalse(self.marker.exists())
        for name in self.plan["client_source_sha256"]:
            self.assertEqual((package / name).read_bytes(), (self.source / name).read_bytes())
        self.assertEqual(checkpoint.read_bytes(), b"pinned checkpoint bytes")
        loaded = feed.modules(package)
        self.assertTrue(self.marker.exists())
        self.assertEqual(Path(loaded["artifacts"].__file__).parent, package)

    def test_tampered_extra_or_linked_source_is_refused_before_execution(self):
        (self.source / "env.py").write_bytes(b"raise SystemExit('tampered code executed')\n")
        with self.assertRaisesRegex(ValueError, "frozen_source_changed"):
            self.snapshot()
        (self.source / "env.py").unlink()
        (self.source / "env.py").symlink_to(self.source / "cli.py")
        self.plan["client_source_sha256"]["env.py"] = self.plan["client_source_sha256"]["cli.py"]
        with self.assertRaises(OSError):
            self.snapshot()
        (self.source / "env.py").unlink()
        (self.source / "env.py").write_bytes((self.source / "cli.py").read_bytes())
        (self.source / "extra.py").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "inventory_changed"):
            self.snapshot()
        self.assertFalse(self.marker.exists())

    def test_checkpoint_and_pin_shapes_fail_closed(self):
        for plan, reason in ((dict(self.plan, checkpoint_sha256="0" * 64), "checkpoint_pin_mismatch"),
                             (dict(self.plan, checkpoint_sha256=None), "checkpoint_pin_mismatch"),
                             (dict(self.plan, client_source_sha256={}), "pins_invalid"),
                             (dict(self.plan, client_source_sha256={"../x.py": "0" * 64}), "pins_invalid")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.snapshot(plan)
        os.mkfifo(self.root / "fifo.ptz")
        with self.assertRaisesRegex(ValueError, "not_regular"):
            self.snapshot(dict(self.plan, checkpoint=str(self.root / "fifo.ptz")))
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
