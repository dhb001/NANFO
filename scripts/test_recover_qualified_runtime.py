"""Recovery security and frozen-validator boundaries; never starts a lab."""

import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

import recover_qualified_runtime as recovery


def archive(*members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as target:
        for name, kind in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = 0
            target.addfile(member, io.BytesIO())
    return buffer.getvalue()


class RecoveryTests(unittest.TestCase):
    def test_archive_rejects_traversal_absolute_links_and_duplicates(self):
        for members in (
            (("emulation/../../outside", tarfile.REGTYPE),),
            (("/emulation/file", tarfile.REGTYPE),),
            (("foreign/file", tarfile.REGTYPE),),
            (("emulation/link", tarfile.SYMTYPE),),
            (("emulation/link", tarfile.LNKTYPE),),
            (("emulation/device", tarfile.CHRTYPE),),
            (("emulation/a", tarfile.REGTYPE), ("emulation/a", tarfile.REGTYPE)),
        ):
            with self.subTest(members=members), self.assertRaises(ValueError):
                recovery.archive_files(archive(*members))

    def test_archive_rejects_oversized_member_before_read(self):
        buffer = io.BytesIO()
        member = tarfile.TarInfo("emulation/large")
        member.size = 9 * 1024**2
        with tarfile.open(fileobj=buffer, mode="w:gz") as target:
            target.addfile(member, io.BytesIO(b"\0" * member.size))
        with self.assertRaisesRegex(ValueError, "oversized"):
            recovery.archive_files(buffer.getvalue())

    def test_outputs_never_overwrite_prior_attempt(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            path = Path(directory) / "result"
            recovery.write(path, b"original")
            with self.assertRaises(FileExistsError):
                recovery.write(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_scratch_root_is_parameterized_not_a_fixed_tmp_path(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory, \
                mock.patch.dict(os.environ, {"NANFO_RESEARCH_SCRATCH": directory}):
            self.assertEqual(recovery.scratch_root(), Path(directory))
        with mock.patch.dict(os.environ, {"NANFO_RESEARCH_SCRATCH": ""}):
            self.assertEqual(recovery.scratch_root(), Path(tempfile.gettempdir()))
        for value in ("relative/dir", "/nonexistent-nanfo-scratch"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"NANFO_RESEARCH_SCRATCH": value}), \
                    self.assertRaisesRegex(ValueError, "NANFO_RESEARCH_SCRATCH"):
                recovery.scratch_root()

    def test_tracked_archive_is_the_pinned_historical_archive(self):
        content = recovery.ARCHIVE.read_bytes()
        self.assertEqual(recovery.ARCHIVE.relative_to(recovery.ROOT), Path("emulation/frozen/adr015-prechange-v4-source.tar.gz"))
        self.assertEqual(recovery.sha(content), recovery.ARCHIVE_HASH)
        files = recovery.archive_files(content)
        self.assertEqual(len(files), 36)
        self.assertIn("emulation/tests/test_experiment.py", files)

    def test_original_archive_and_checkpoint_are_exact(self):
        manifest, files, report = recovery.audit()
        self.assertEqual(report["environment_version"], 4)
        self.assertEqual(len(report["lab_source_files"]), 13)
        self.assertEqual(len(report["client_source_files"]), 14)
        self.assertEqual(len(report["historical_sessions"]), 5)
        self.assertFalse(report["live_qualified"])
        self.assertEqual(manifest["lab_provenance"]["source_sha256"], report["lab_source_sha256"])
        self.assertIn("emulation/tests/test_experiment.py", files)

    def test_dependency_mismatch_rejected(self):
        files = {"emulation/requirements.txt": b"ryu==4.34\n"}
        probe = dict(python="3.9.23", packages={"ryu": "4.35"}, dpkg="")
        with self.assertRaisesRegex(ValueError, "base dependency mismatch: ryu"):
            recovery.verify_dependencies(probe, files)
        probe["python"] = "3.9.24"
        with self.assertRaisesRegex(ValueError, "lab Python differs"):
            recovery.verify_dependencies(probe, files)

    def test_registry_template_does_not_fabricate_installation(self):
        manifest, _, _ = recovery.audit()
        registry = recovery.registry_template(manifest)
        self.assertNotIn("qualified", registry)
        self.assertEqual(registry["installed_at"], "REPLACE_AWARE_INSTALL_TIME")
        self.assertEqual(registry["scopes"][0]["network_id"], "REPLACE_NETWORK_UUID")
        self.assertEqual(registry["checkpoint"]["sha256"], recovery.CHECKPOINT_HASH)
        self.assertEqual(registry["source_sha256"], manifest["client_source_files"])

    def test_actual_frozen_validator_rejects_distinct_image_source_and_spec(self):
        result = subprocess.run(
            [str(recovery.AI / ".venv/bin/python"), "-B", recovery.__file__, "boundaries",
             "--image-id", "sha256:" + "0" * 64],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        cases = json.loads(result.stdout)["cases"]
        self.assertEqual(cases["original"]["returncode"], 0)
        for name in ("rebuilt_image", "wrong_source", "wrong_spec"):
            self.assertEqual(cases[name]["returncode"], 1)
        self.assertIn("inference image/source provenance differs", cases["rebuilt_image"]["stderr"])


if __name__ == "__main__":
    unittest.main()
