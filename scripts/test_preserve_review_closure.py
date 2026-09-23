"""Credential refusal, immutable preservation and source-drift boundary regressions."""

import hashlib
import hmac
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import preserve_review_closure as preserve

hygiene = preserve.hygiene
safe = preserve.safe


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        self.destination = self.root / "published"

    def plan(self, data=b'{"status":"passed"}\n'):
        hygiene.publish(self.source, "result.json", data)
        return {"schema": "nanfo-review-closure-selection-v1", "files": {
            "lane/result.json": {"source": str(self.source / "result.json"), **safe.descriptor(data)}}}

    def test_exact_bytes_portable_verification_and_no_clobber(self):
        data = b'{ "status": "passed", "count": 5 }\n'
        plan = self.plan(data)
        result = preserve.export(plan, self.destination)
        self.assertEqual(result["evidence_files"], 1)
        self.assertEqual((self.destination / "lane/result.json").read_bytes(), data)
        with self.assertRaises(safe.EvidenceError):
            preserve.export(plan, self.destination)
        (self.source / "result.json").unlink()
        self.assertEqual(preserve.verify(self.destination)["status"], "passed")

    def test_stale_pin_refused_before_creation(self):
        plan = self.plan()
        (self.source / "result.json").write_bytes(b"{}")
        with self.assertRaises(safe.EvidenceError):
            preserve.export(plan, self.destination)
        self.assertFalse(self.destination.exists())

    def test_credentials_and_known_values_refused_before_creation(self):
        data = safe.canonical({"password": "example" + "-fixture-only"})
        plan = self.plan(data)
        with self.assertRaises(safe.EvidenceError):
            preserve.export(plan, self.destination)
        self.assertFalse(self.destination.exists())
        (self.source / "result.json").unlink()
        marker = b"known-fixture-marker-only"
        plan = self.plan(safe.canonical({"detail": marker.decode()}))
        with self.assertRaises(safe.EvidenceError):
            preserve.export(plan, self.destination, (marker,))
        self.assertFalse(self.destination.exists())

    def test_unsafe_names_and_links_refused(self):
        plan = self.plan()
        item = plan["files"].pop("lane/result.json")
        for name in ("../result.json", "secrets/result.json", "raw.tar.gcm"):
            with self.subTest(name=name), self.assertRaises(safe.EvidenceError):
                preserve.export({**plan, "files": {name: item}}, self.destination)
        (self.source / "result.json").rename(self.source / "original.json")
        (self.source / "result.json").symlink_to(self.source / "original.json")
        with self.assertRaises(OSError):
            preserve.export({**plan, "files": {"result.json": item}}, self.destination)

    def test_tampering_and_extra_file_fail_portable_verification(self):
        preserve.export(self.plan(), self.destination)
        hygiene.publish(self.destination, "extra.json", b"{}")
        with self.assertRaises(safe.EvidenceError):
            preserve.verify(self.destination)
        (self.destination / "extra.json").unlink()
        (self.destination / "lane/result.json").write_bytes(b"{}")
        with self.assertRaises(safe.EvidenceError):
            preserve.verify(self.destination)

    def test_comparison_never_equates_tests_dependencies_and_runtime(self):
        paths = {"backend/app/a.py": b"app", "backend/tests/a.py": b"test",
                 "backend/poetry.lock": b"lock", "README.md": b"docs", "missing.py": b"missing"}
        for name, data in paths.items():
            if name != "missing.py":
                hygiene.publish(self.source, name, data)
        frozen = {n: safe.sha256(d) for n, d in paths.items()}
        (self.source / "backend/poetry.lock").write_bytes(b"new lock")
        (self.source / "backend/tests/a.py").write_bytes(b"new test")
        result = preserve.compare(self.source, frozen)
        self.assertEqual(result["matched"], 2)
        self.assertEqual(set(result["changed"]), {"backend/poetry.lock", "backend/tests/a.py"})
        self.assertEqual(result["missing"], ["missing.py"])
        self.assertFalse(result["additional_paths_examined"])

    def test_private_copy_no_clobber_and_link_refusal(self):
        source = self.source / "archive.gcm"
        source.write_bytes(b"synthetic encrypted archive stand-in")
        source.chmod(0o600)
        destination = self.root / "copied.gcm"
        pin = preserve.copy_private(source, destination, max_bytes=1024)
        self.assertEqual(pin, safe.descriptor(source.read_bytes()))
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            preserve.copy_private(source, destination, max_bytes=1024)
        source.unlink()
        source.symlink_to(destination)
        with self.assertRaises(OSError):
            preserve.copy_private(source, self.root / "new.gcm", max_bytes=1024)

    def test_authenticated_backup_separate_key_ignored_and_originals_retained(self):
        import backup_restore

        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("ai-engine/artifacts/\n")
        artifacts = self.root / "ai-engine/artifacts"
        artifacts.mkdir(parents=True)
        key = os.urandom(32)
        key_file = self.root / "original.key"
        key_file.write_bytes(key)
        key_file.chmod(0o600)
        archive = b"synthetic ciphertext; only manifest authentication tested"
        hygiene.publish(self.source, "volume-0000.tar.gcm", archive)
        manifest = {"format": 1, "complete": True, "project": "nanfo-deploy-fixture",
                    "volumes": [{"file": "volume-0000.tar.gcm", "sha256": safe.sha256(archive)}]}
        raw = backup_restore.canonical(manifest)
        hygiene.publish(self.source, "manifest.json", raw)
        hygiene.publish(self.source, "manifest.hmac", hmac.new(key, raw, hashlib.sha256).hexdigest().encode())
        destination, keys = artifacts / "backup-copy", artifacts / "separate-keys"
        receipt = preserve.preserve_backup(self.root, self.source, destination, key_file, keys)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual((keys / "backup.key").read_bytes(), key_file.read_bytes())
        self.assertTrue((self.source / "volume-0000.tar.gcm").exists())
        self.assertFalse((destination / "backup.key").exists())
        with self.assertRaises(safe.EvidenceError):
            preserve.preserve_backup(self.root, self.source, destination, key_file, keys)
        self.assertEqual((destination / "volume-0000.tar.gcm").read_bytes(), archive)


if __name__ == "__main__":
    unittest.main()
