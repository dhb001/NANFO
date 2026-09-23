"""Offline ADR027 regression tests; generated synthetic secrets never authenticate."""

import contextlib
import bz2
import gzip
import io
import json
import lzma
import os
import subprocess
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

import evidence_hygiene as hygiene


def zip_bytes(items):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in items:
            archive.writestr(name, data)
    return stream.getvalue()


def tar_bytes(name, data=b"", kind=tarfile.REGTYPE):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        item = tarfile.TarInfo(name)
        item.type = kind
        item.size = len(data)
        if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            item.linkname = "outside"
        archive.addfile(item, io.BytesIO(data))
    return stream.getvalue()


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        self.destination = self.root / "export"
        # Clearly synthetic, deterministic, built at runtime; no real credentials.
        self.token = hygiene.safe.sha256(b"ADR027 synthetic credential regression").encode()

    def allowlist(self, files):
        for name, data in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return {"schema": hygiene.ALLOWLIST_SCHEMA,
                "files": {n: hygiene.safe.descriptor(d) for n, d in files.items()}}

    def rules(self, name, data, **kwargs):
        scanner = hygiene.Scanner(**kwargs)
        scanner.inspect(name, data)
        return {row["rule"] for row in scanner.findings}

    def test_export_selects_only_pinned_evidence_and_preserves_exact_bytes(self):
        original = b'{ "status": "failed", "measurement": 0.25 }\n'
        allowed = self.allowlist({"results/result.json": original})
        (self.source / "receiver-token").write_bytes(self.token)
        (self.source / "private-admission.json").write_bytes(b'{"authorized":true}')
        result = hygiene.export_evidence(self.source, self.destination, allowed, known_tokens=(self.token,))
        self.assertEqual(result["files"], 1)
        self.assertEqual((self.destination / "results/result.json").read_bytes(), original)
        self.assertEqual((self.source / "receiver-token").read_bytes(), self.token)
        self.assertEqual(hygiene.names(self.destination, 10), ["manifest.json", "results/result.json"])
        manifest = json.loads((self.destination / "manifest.json").read_bytes())
        self.assertEqual(manifest["files"], allowed["files"])
        for path in self.destination.rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
            if path.is_file():
                self.assertNotIn(self.token, path.read_bytes())

    def test_export_refuses_secrets_without_partial_output(self):
        for name, data in (("result.json", b'{"receiver_token":"' + self.token + b'"}'),
                           ("result.txt", self.token),
                           ("receiver-token", self.token),
                           ("private-admission.json", b"{}"),
                           ("child-config.json", b"{}"),
                           ("result.zip", zip_bytes([("x/receiver-token", self.token)])),
                           ("admissions.zip", zip_bytes([("private-admission.json", b"{}")]))):
            with self.subTest(name=name):
                allowed = self.allowlist({name: data})
                with self.assertRaises(hygiene.Error):
                    hygiene.export_evidence(self.source, self.destination, allowed, known_tokens=(self.token,))
                self.assertFalse(self.destination.exists())

    def test_export_no_clobber_and_pin_mismatch(self):
        allowed = self.allowlist({"result.json": b"{}"})
        hygiene.export_evidence(self.source, self.destination, allowed)
        before = (self.destination / "manifest.json").read_bytes()
        with self.assertRaises(hygiene.Error):
            hygiene.export_evidence(self.source, self.destination, allowed)
        self.assertEqual((self.destination / "manifest.json").read_bytes(), before)
        (self.source / "result.json").write_bytes(b"[]")
        with self.assertRaises(hygiene.Error):
            hygiene.export_evidence(self.source, self.root / "new", allowed)
        self.assertFalse((self.root / "new").exists())

    def test_export_paths_symlinks_hardlinks_and_fifo(self):
        allowed = self.allowlist({"result.json": b"{}"})
        for name in ("../result.json", "/result.json", "a/../result.json", "./result.json", "a//result.json", "a\\b", ".env"):
            with self.subTest(name=name), self.assertRaises(hygiene.Error):
                hygiene.export_evidence(self.source, self.destination,
                                        {"schema": hygiene.ALLOWLIST_SCHEMA, "files": {name: hygiene.safe.descriptor(b"{}")}})
        for kind in ("symlink", "hardlink", "fifo"):
            path = self.source / (kind + ".json")
            if kind == "symlink":
                path.symlink_to(self.source / "result.json")
            elif kind == "hardlink":
                os.link(self.source / "result.json", path)
            else:
                os.mkfifo(path)
            with self.subTest(kind=kind), self.assertRaises((hygiene.Error, OSError)):
                hygiene.read_file(self.source, path.name, 100)
        (self.root / "alias").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((hygiene.Error, OSError)):
            hygiene.export_evidence(self.source, self.root / "alias/export", allowed)

    def test_export_source_output_overlap_and_reserved_manifest(self):
        allowed = self.allowlist({"result.json": b"{}"})
        for destination in (self.source, self.source / "nested", self.root):
            with self.assertRaises(hygiene.Error):
                hygiene.export_evidence(self.source, destination, allowed)
        with self.assertRaises(hygiene.Error):
            hygiene.export_evidence(self.source, self.destination, self.allowlist({"manifest.json": b"{}"}))

    def test_extensionless_receiver_and_known_token_in_arbitrary_bytes(self):
        self.assertIn("credential_file", self.rules("run/receiver-token", self.token))
        self.assertIn("known_receiver_token", self.rules("image.bin", b"\x00" + self.token + b"\xff", known_tokens=(self.token,)))
        self.assertEqual(self.rules("checksums", self.token), set())
        self.assertEqual(self.rules("receipt.json", b'{"key_sha256":"' + self.token + b'"}'), set())

    def test_structured_escaped_and_embedded_secrets(self):
        cases = [json.dumps({"nested": {"password": "actual-short-secret"}}).encode(),
                 json.dumps({"stdout": json.dumps({"receiver_token": self.token.decode()})}).encode(),
                 b'{"receiver_\\u0074oken":"sensitive"}',
                 json.dumps({"argv": ["Bearer " + self.token.decode()]}).encode()]
        for data in cases:
            with self.subTest(size=len(data)):
                self.assertTrue(self.rules("result.json", data))
        self.assertTrue(self.rules("output", b"RECEIVER_TOKEN=" + self.token))
        self.assertIn("credential_url", self.rules("output", b"postgresql://user:actualsecret@localhost/db"))
        self.assertIn("private_key", self.rules("output", b"-----BEGIN PRIVATE KEY-----"))

    def test_placeholders_and_reviewed_synthetic_fixture_exceptions_are_narrow(self):
        self.assertEqual(self.rules("sample.json", b'{"password":"CHANGE_ME","token":"test-token"}'), set())
        data = b'{"token":"' + self.token + b'"}'
        fixture = {"fixture.json": {"sha256": hygiene.safe.sha256(data),
                                   "rules": ["secret_field", "secret_assignment"],
                                   "reason": "Deterministic synthetic token; never deployed."}}
        self.assertEqual(self.rules("fixture.json", data, fixtures=fixture), set())
        self.assertTrue(self.rules("fixture.json", data + b"\n", fixtures=fixture))
        self.assertTrue(self.rules("production.json", data, fixtures=fixture))
        self.assertIn("known_receiver_token", self.rules("fixture.json", data, fixtures=fixture, known_tokens=(self.token,)))
        path = self.root / "fixtures.json"
        path.write_text(json.dumps({"schema": hygiene.FIXTURE_SCHEMA, "files": fixture}))
        self.assertEqual(hygiene.load_fixtures(path), fixture)
        fixture["fixture.json"]["rules"].append("known_receiver_token")
        path.write_text(json.dumps({"schema": hygiene.FIXTURE_SCHEMA, "files": fixture}))
        with self.assertRaises(hygiene.Error):
            hygiene.load_fixtures(path)

    def test_nested_archives_magic_and_no_extraction(self):
        data = zip_bytes([("inner", gzip.compress(tar_bytes("run/receiver-token", self.token)))])
        self.assertIn("credential_file", self.rules("no-extension", data, limits=hygiene.Limits(ratio=1000)))
        self.assertFalse((self.root / "run").exists())
        data = gzip.compress(b'{"token":"actual-short-secret"}')
        self.assertIn("secret_field", self.rules("result.json.gz", data))
        for compress in (bz2.compress, lzma.compress):
            self.assertIn("secret_field", self.rules("result.json.xz" if compress is lzma.compress else "result.json.bz2",
                                                    compress(b'{"token":"actual-short-secret"}')))

    def test_python_references_and_backup_secret_hash_paths_are_not_credentials(self):
        self.assertEqual(self.rules("source.py", b"receiver_token = request.receiver_token\n"), set())
        self.assertTrue(self.rules("source.py", b'receiver_token = "' + self.token + b'"\n'))
        self.assertEqual(self.rules("manifest.json", b'{"postgres:/run/secrets/admin_password":"' + self.token + b'"}'), set())

    def test_known_token_in_export_filename_is_refused(self):
        allowed = self.allowlist({self.token.decode() + ".json": b"{}"})
        with self.assertRaises(hygiene.Error):
            hygiene.export_evidence(self.source, self.destination, allowed, known_tokens=(self.token,))
        self.assertFalse(self.destination.exists())

    def test_tests_directory_has_no_implicit_exemption(self):
        name = "tests/fixture.py"
        self.assertIn("secret_assignment", self.rules(name, b'password = "' + self.token + b'"'))

    def test_receiver_files_cannot_be_excepted(self):
        fixture = {"receiver-token": {"sha256": hygiene.safe.sha256(self.token),
                                      "rules": ["credential_file"],
                                      "reason": "Invalid attempt to exempt receiver authority."}}
        self.assertIn("credential_file", self.rules("receiver-token", self.token, fixtures=fixture))
        path = self.root / "policy.json"
        path.write_text(json.dumps({"schema": hygiene.FIXTURE_SCHEMA, "files": fixture}))
        with self.assertRaises(hygiene.Error):
            hygiene.load_fixtures(path)

    def test_empty_environment_secrets_do_not_capture_next_line(self):
        self.assertEqual(self.rules(".env.example", b"POSTGRES_PASSWORD=\nPOSTGRES_DB=nanfo\n"), set())

    def test_portable_git_gate_includes_new_files_and_fails_modified_exceptions(self):
        subprocess.run(["git", "init", "-q", str(self.source)], check=True, capture_output=True)
        fixture_data = b'{"password":"synthetic-policy-fixture"}'
        (self.source / "fixture.json").write_bytes(fixture_data)
        subprocess.run(["git", "-C", str(self.source), "add", "fixture.json"], check=True, capture_output=True)
        policy = {"schema": hygiene.FIXTURE_SCHEMA, "files": {
            "fixture.json": {"sha256": hygiene.safe.sha256(fixture_data),
                             "rules": ["secret_field", "secret_assignment"],
                             "reason": "Synthetic fixture for gate regression; never authenticates."}}}
        policy_path = self.root / "policy.json"
        policy_path.write_text(json.dumps(policy))
        args = ["scan", "--root", str(self.source), "--tracked", "--include-untracked", "--fixtures", str(policy_path)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hygiene.main(args), 0)
            (self.source / "fixture.json").write_bytes(fixture_data + b"\n")
            self.assertEqual(hygiene.main(args), 1)
            (self.source / "fixture.json").write_bytes(fixture_data)
            (self.source / "new-extensionless").write_bytes(b"RECEIVER_TOKEN=" + self.token)
            self.assertEqual(hygiene.main(args), 1)
        self.assertIn("new-extensionless", hygiene.tracked_names(self.source, include_untracked=True))
        self.assertNotIn("new-extensionless", hygiene.tracked_names(self.source))

    def test_archive_traversal_links_duplicates_and_corruption_fail_closed(self):
        for data in (zip_bytes([("../escape", b"x")]),
                     tar_bytes("/absolute"), tar_bytes("link", kind=tarfile.SYMTYPE),
                     tar_bytes("hard", kind=tarfile.LNKTYPE)):
            self.assertTrue(self.rules("archive", data))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            data = zip_bytes([("same", b"x"), ("same", b"y")])
        self.assertIn("duplicate_archive_member", self.rules("archive", data))
        for name, data in (("bad.zip", b"PK\x03\x04broken"), ("bad.gz", b"\x1f\x8bbroken"),
                           ("bad.tar", b"broken"), ("hidden", b"7z\xbc\xaf\x27\x1c"),
                           ("hidden-xz", b"\xfd7zXZ\x00broken")):
            self.assertTrue(self.rules(name, data))

    def test_encrypted_and_special_zip_members_are_refused(self):
        data = bytearray(zip_bytes([("member", b"payload")]))
        central = data.index(b"PK\x01\x02")
        data[central + 8] |= 1
        self.assertIn("encrypted_archive", self.rules("archive", bytes(data)))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = (0o120777 << 16)
            archive.writestr(entry, "outside")
        self.assertIn("archive_special_file", self.rules("archive", output.getvalue()))

    def test_archive_depth_ratio_entry_and_byte_budgets(self):
        nested = zip_bytes([("inner", zip_bytes([("inner", zip_bytes([("leaf", b"ok")]))]))])
        self.assertIn("archive_depth_limit", self.rules("archive", nested, limits=hygiene.Limits(depth=1)))
        self.assertTrue(self.rules("archive", zip_bytes([("large", b"x" * 100000)]), limits=hygiene.Limits(ratio=2)))
        self.assertTrue(self.rules("archive", gzip.compress(b"x" * 100000), limits=hygiene.Limits(ratio=2)))
        self.assertIn("entry_limit", self.rules("archive", zip_bytes([("a", b"1"), ("b", b"2")]), limits=hygiene.Limits(entries=2)))
        self.assertIn("file_byte_limit", self.rules("file", b"12345", limits=hygiene.Limits(file_bytes=4)))
        scanner = hygiene.Scanner(hygiene.Limits(total_bytes=6))
        scanner.inspect("a", b"1234")
        scanner.inspect("b", b"1234")
        self.assertIn("total_byte_limit", {r["rule"] for r in scanner.findings})

    def test_diagnostics_never_echo_secret_contents_or_secret_filenames(self):
        name = self.token.decode()
        (self.source / name).write_bytes(b"Bearer " + self.token)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = hygiene.main(["scan", "--root", str(self.source)])
        self.assertEqual(code, 1)
        self.assertNotIn(name, output.getvalue())
        self.assertNotIn("Bearer", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["findings"][0]["rule"], "bearer")

    def test_private_preservation_verified_permissions_no_clobber_and_tamper(self):
        artifacts = self.source / "ai-engine/artifacts"
        artifacts.mkdir(parents=True)
        name = hygiene.CAMPAIGN + "/case/receiver-token"
        path = self.source / name
        path.parent.mkdir(parents=True)
        path.write_bytes(self.token)
        destination = artifacts / "private-001"
        with patch.object(hygiene, "tracked_names", return_value=[name]), patch.object(
                hygiene.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            result = hygiene.preserve_credentials(self.source, destination, expected=1)
            self.assertEqual(result["files"], 1)
            self.assertTrue(result["source_compared"])
            self.assertEqual((destination / name).read_bytes(), self.token)
            self.assertEqual(path.read_bytes(), self.token)
            with self.assertRaises(hygiene.Error):
                hygiene.preserve_credentials(self.source, destination, expected=1)
        (destination / name).chmod(0o644)
        with self.assertRaises(hygiene.Error):
            hygiene.verify_private(destination)
        (destination / name).chmod(0o600)
        (destination / name).write_bytes(b"tampered")
        with self.assertRaises(hygiene.Error):
            hygiene.verify_private(destination)


if __name__ == "__main__":
    unittest.main()
