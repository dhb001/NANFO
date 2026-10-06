"""Preservation boundaries; deterministic local files only, never services or a lab."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import preserve_qualification_evidence as preservation


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_forbidden_paths_and_links(self):
        (self.root / "original.json").write_bytes(b"{}")
        (self.root / "alias.json").symlink_to(self.root / "original.json")
        for name in ("../original.json", "/original.json", "nested/../original.json",
                     ".env", "signing.key", "alias.json"):
            with self.subTest(name=name), self.assertRaises((OSError, preservation.safe.EvidenceError)):
                preservation.safe.read_relative(self.root, name)
        (self.root / "ancestor").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            preservation.safe.read_relative(self.root / "ancestor", "original.json")

    def test_hardlinks_and_special_files_refused(self):
        (self.root / "original.json").write_bytes(b"{}")
        os.link(self.root / "original.json", self.root / "hardlink.json")
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.safe.read_relative(self.root, "hardlink.json")
        os.mkfifo(self.root / "pipe")
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.names(self.root)

    def test_secret_values_and_nested_transcripts_refused(self):
        for data in (
            {"password": "private"}, {"Env": ["PRIVATE=value"]},
            {"nested": [{"admission_token": "private"}]},
            {"stdout": json.dumps({"private_key": "private"})},
            {"argv": ["Bearer abcdefgh123456"]},
            {"argv": ["POSTGRES_PASSWORD=abcdef123456"]},
            {"url": "postgresql://user:private@localhost/db"},
            {"key": "-----BEGIN PRIVATE KEY-----"},
        ):
            with self.subTest(data=data), self.assertRaises(preservation.safe.EvidenceError):
                preservation.screen("result.json", json.dumps(data).encode())
        preservation.screen("result.json", b'{"admission_sha256":"abc","environment":"isolated-emulation"}')

    def test_dynamic_allowlist_excludes_private_and_generic_files(self):
        for group, name in (("live", "path0/admission.json"), ("live", "path0/expired-admission.json"),
                            ("live", "path0/producer.log"), ("native", "container.json"),
                            ("native", "action0/manual.json"), ("native", "action0/STOP-0/secrets.json"),
                            ("evaluation", "ppo-inspect.stdout")):
            self.assertFalse(preservation.dynamic_allowed(group, name))
        self.assertTrue(preservation.dynamic_allowed("live", "path0/feed/evidence.jsonl"))
        self.assertTrue(preservation.dynamic_allowed("native", "action0/STOP-12/prepared.json"))

    def test_no_clobber_and_protected_copies(self):
        preservation.publish(self.root, "nested/result.json", b'{"ok":true}')
        with self.assertRaises(FileExistsError):
            preservation.publish(self.root, "nested/result.json", b"replacement")
        self.assertEqual((self.root / "nested/result.json").read_bytes(), b'{"ok":true}')
        self.assertEqual((self.root / "nested").stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "nested/result.json").stat().st_mode & 0o777, 0o600)
        (self.root / "loose").mkdir(mode=0o755)
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.publish(self.root, "loose/result.json", b"{}")

    def test_output_parent_symlink_refused(self):
        (self.root / "redirect").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            preservation.publish(self.root, "redirect/result.json", b"{}")

    def test_registry_is_closed_and_digest_checked_after_relocation(self):
        data = b"model-bytes"
        registry = {"checkpoint": {"path": "checkpoint.ptz", "size_bytes": len(data),
                                    "sha256": preservation.safe.sha256(data)},
                    "source_directory": "source", "source_sha256": {"cli.py": preservation.safe.sha256(b"source")}}
        files = {"checkpoint.ptz": data, "source/cli.py": b"source"}
        self.assertEqual(preservation.check_references(registry, files.__getitem__), 1)
        files["checkpoint.ptz"] = b"changed"
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.check_references(registry, files.__getitem__)
        registry["checkpoint"]["path"] = "../outside"
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.check_references(registry, files.__getitem__)

    def test_unpinned_model_and_duplicate_json_refused(self):
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.screen("checkpoint.ptz", b"arbitrary binary")
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.screen("result.json", b'{"ok":true,"ok":false}')

    def test_temporary_destination_refused(self):
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.output_roots(self.root / "artifacts", self.root / "documents")

    def test_large_file_rejected_before_copy(self):
        (self.root / "large.json").write_bytes(b"12345")
        with self.assertRaises(preservation.safe.EvidenceError):
            preservation.safe.read_relative(self.root, "large.json", limit=4)

    def test_finalize_only_publishes_missing_identical_markers(self):
        artifacts, documents = self.root / "artifacts", self.root / "documents"
        artifacts.mkdir(mode=0o700)
        documents.mkdir(mode=0o700)
        preservation.publish(documents, "checksums.json", b"{}")
        with patch.object(preservation, "verify", return_value={"status": "passed"}) as verify:
            preservation.finalize(artifacts, documents)
            first = (documents / "preservation-complete.json").read_bytes()
            preservation.finalize(artifacts, documents)
            self.assertEqual(verify.call_count, 2)
            self.assertEqual((artifacts / "preservation-complete.json").read_bytes(), first)
            (artifacts / "preservation-complete.json").write_bytes(b"changed")
            with self.assertRaises(preservation.safe.EvidenceError):
                preservation.finalize(artifacts, documents)
            self.assertEqual((artifacts / "preservation-complete.json").read_bytes(), b"changed")

    def test_acquisition_roots_are_parameterized_but_repository_is_fixed(self):
        roots = preservation.source_roots([f"evaluation={self.root}", f"review={self.root / 'reviews'}"])
        self.assertEqual((roots["evaluation"], roots["review"]), (self.root, self.root / "reviews"))
        self.assertEqual(roots["repository"], preservation.ROOT)
        self.assertEqual(roots["live"], preservation.SOURCES["live"])
        self.assertEqual(preservation.source_roots(None), preservation.SOURCES)
        for value in ("repository=/tmp/x", "unknown=/tmp/x", "evaluation", "evaluation=relative",
                      "evaluation=/tmp/../etc"):
            with self.subTest(value=value), self.assertRaises(preservation.safe.EvidenceError):
                preservation.source_roots([value])


if __name__ == "__main__":
    unittest.main()
