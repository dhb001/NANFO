"""ADR-028 task 4: frozen sources are hashed before they execute (fresh interpreters)."""

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from emulation.experimental_lab_contract import IMAGE, SOURCE
from emulation.experimental_lab_runtime import (
    FROZEN_PACKAGE_INIT_SHA256,
    FROZEN_SOURCE_FILES,
    source_digest,
)
from emulation.tests import frozen_v4

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = frozen_v4.ARCHIVE
PROGRAM = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import experimental_lab_runtime as runtime
report = {}
try:
    module = runtime.load_original(sys.argv[2])
    report["file"] = module.__file__
    report["loaded"] = sorted(name for name in sys.modules if name.startswith("emulation"))
    try:
        __import__("emulation.mailbox")
        report["unverified"] = "imported"
    except ImportError as exc:
        report["unverified"] = str(exc)
except ValueError as exc:
    report["error"] = str(exc)
report["executed_before_check"] = "NANFO_TAMPER_MARK" in sys.modules
print(json.dumps(report))
"""


def run(source, environ=None, prelude=""):
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env.update({"NANFO_LAB_IMAGE_ID": IMAGE, **(environ or {})})
    result = subprocess.run([sys.executable, "-B", "-c", prelude + PROGRAM, str(ROOT / "emulation"), str(source)],
                            capture_output=True, text=True, timeout=60, env=env, cwd=str(ROOT / "emulation"))
    if result.returncode:
        raise AssertionError(result.stderr[-2000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(frozen_v4.available(), "tracked frozen v4 source archive not present")
class VerifiedFrozenImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.copy = Path(self.temp.name) / "emulation"
        shutil.copytree(frozen_v4.frozen_emulation(), self.copy,
                        ignore=shutil.ignore_patterns("__pycache__", "tests"))

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_frozen_source_loads_only_from_verified_bytes(self):
        report = run(self.copy)
        self.assertNotIn("error", report)
        self.assertEqual(Path(report["file"]).resolve(), (self.copy / "experiment.py").resolve())
        self.assertIn("emulation.matched", report["loaded"])
        self.assertIn("unverified_frozen_module:emulation.mailbox", report["unverified"])

    def test_tampered_source_is_rejected_before_any_frozen_code_executes(self):
        path = self.copy / "ospf.py"
        path.write_text("import sys\nsys.modules['NANFO_TAMPER_MARK'] = sys\n" + path.read_text())
        report = run(self.copy)
        self.assertEqual(report["error"], "frozen_source_mismatch")
        self.assertFalse(report["executed_before_check"])
        (self.copy / "__init__.py").write_text("import sys\nsys.modules['NANFO_TAMPER_MARK'] = sys\n")
        self.assertEqual(run(self.copy)["error"], "frozen_package_mismatch")

    def test_symlinked_source_image_mismatch_and_preloaded_package_fail_closed(self):
        target = self.copy / "matched.py"
        moved = self.copy.parent / "matched.py"
        target.rename(moved)
        target.symlink_to(moved)
        self.assertEqual(run(self.copy)["error"], "frozen_source_unavailable")
        target.unlink()
        moved.rename(target)
        self.assertEqual(run(self.copy, {"NANFO_LAB_IMAGE_ID": "sha256:" + "0" * 64})["error"],
                         "image_binding_mismatch")
        prelude = "import types, sys\nsys.modules['emulation'] = types.ModuleType('emulation')\n"
        self.assertEqual(run(self.copy, prelude=prelude)["error"], "emulation_package_already_imported")


class FrozenListDriftTests(unittest.TestCase):
    @unittest.skipUnless(frozen_v4.available(), "tracked frozen v4 source archive not present")
    def test_pinned_frozen_file_list_package_init_and_digest(self):
        with tarfile.open(ARCHIVE) as archive:
            files = {name: archive.extractfile("emulation/" + name).read()
                     for name in ("experiment.py", "__init__.py", *FROZEN_SOURCE_FILES)}
        tree = ast.parse(files["experiment.py"])
        listed = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                      and getattr(node.targets[0], "id", None) == "SOURCE_FILES")
        self.assertEqual(tuple(listed), FROZEN_SOURCE_FILES)
        self.assertEqual(hashlib.sha256(files["__init__.py"]).hexdigest(), FROZEN_PACKAGE_INIT_SHA256)
        hashes = {name: hashlib.sha256(files[name]).hexdigest() for name in FROZEN_SOURCE_FILES}
        self.assertEqual(source_digest(hashes), SOURCE)


if __name__ == "__main__":
    unittest.main()


class TrackedArchiveEquivalenceTests(unittest.TestCase):
    RECOVERY = ROOT / "ai-engine/artifacts/adr024-qualified-001/recovery/emulation"

    @unittest.skipUnless(RECOVERY.is_dir() and frozen_v4.available(), "private recovery copy not present")
    def test_private_recovery_copy_equals_the_tracked_archive_members(self):
        """Justifies replacing the private copy: every recovered file is an archive member byte-for-byte."""
        extracted = frozen_v4.frozen_emulation()
        compared = 0
        for path in sorted(self.RECOVERY.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(self.RECOVERY)
            with self.subTest(file=str(relative)):
                self.assertEqual((extracted / relative).read_bytes(), path.read_bytes())
            compared += 1
        self.assertGreaterEqual(compared, len(FROZEN_SOURCE_FILES))
