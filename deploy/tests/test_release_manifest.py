"""Offline integrity/security tests; never deployment acceptance or Docker tests."""

import importlib.util
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "release_manifest", Path(__file__).parents[1] / "release_manifest.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.builds = self.base / "builds"
        self.run = self.base / "run"
        self.output = self.base / "durable"
        for directory in (self.root, self.builds, self.run / "evidence", self.output):
            directory.mkdir(parents=True, mode=0o700)
        for index, name in enumerate(release.LOCKS):
            self.write(self.root / name, f"lock-{index}\n".encode())
        self.write(self.root / "backend/app/main.py", b"print('exact source')\n")
        self.record = {
            "image_id": "sha256:" + "a" * 64,
            "source_sha256": {
                "backend/app/main.py": release.sha256(b"print('exact source')\n"),
                **{
                    name: release.sha256(f"lock-{index}\n".encode())
                    for index, name in enumerate(release.LOCKS)
                },
            },
        }
        self.write(self.builds / "build.json", release.canonical(self.record))
        self.result = {
            "cases": {
                "campaign": {"status": "failed", "detail": "Bearer PRIVATE_CANARY"},
                "cleanup": {
                    "status": "passed",
                    "detail": {"password": "PRIVATE_CANARY"},
                },
                "lab_congestion": {"status": "blocked", "detail": "not run"},
            },
            "failure": "PRIVATE_CANARY",
            "evidence_directory": "/private/PRIVATE_CANARY",
            "counts": {"passed": 999},
            "all_green": False,
            "step15_complete": False,
            "authorization": "PRIVATE_CANARY",
        }
        self.write(self.run / "evidence/result.json", release.canonical(self.result))

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def manifest(self):
        return release.create_manifest(self.root, self.builds, ["build.json"])

    def export(self, name="evidence.tar"):
        manifest = self.output / "release.json"
        if not manifest.exists():
            release.publish(manifest, release.canonical(self.manifest()))
        target = self.output / name
        digest = release.export_bundle(manifest, self.run, target)
        return target.read_bytes(), digest

    @staticmethod
    def members(raw):
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            return {item.name: archive.extractfile(item).read() for item in archive}

    def test_exact_bytes_roundtrip_and_deterministic_manifest(self):
        first = self.manifest()
        release.verify_manifest(first, self.root, self.builds)
        os.utime(self.root / "backend/app/main.py", (10, 10))
        os.chmod(self.root / "backend/app/main.py", 0o600)
        self.assertEqual(release.canonical(first), release.canonical(self.manifest()))
        self.assertEqual(
            first["build_records"]["build.json"]["record"]["sha256"],
            release.sha256((self.builds / "build.json").read_bytes()),
        )

    def test_source_tamper_and_missing_source_refused(self):
        manifest = self.manifest()
        source = self.root / "backend/app/main.py"
        source.write_bytes(b"changed")
        with self.assertRaises(release.EvidenceError):
            release.verify_manifest(manifest, self.root, self.builds)
        source.unlink()
        with self.assertRaises(OSError):
            release.verify_manifest(manifest, self.root, self.builds)

    def test_lock_tamper_refused(self):
        manifest = self.manifest()
        (self.root / "ai-engine/uv.lock").write_bytes(b"different lock")
        with self.assertRaises(release.EvidenceError):
            release.verify_manifest(manifest, self.root, self.builds)

    def test_summary_without_lock_coverage_is_not_full_build_evidence(self):
        del self.record["source_sha256"]["frontend/package-lock.json"]
        self.write(self.builds / "build.json", release.canonical(self.record))
        with self.assertRaises(release.EvidenceError):
            self.manifest()

    def test_build_record_whitespace_is_significant(self):
        manifest = self.manifest()
        (self.builds / "build.json").write_text(json.dumps(self.record, indent=4))
        with self.assertRaises(release.EvidenceError):
            release.verify_manifest(manifest, self.root, self.builds)

    def test_conflicting_build_inputs_refused(self):
        second = {**self.record, "source_sha256": {"backend/app/main.py": "b" * 64}}
        self.write(self.builds / "second.json", release.canonical(second))
        with self.assertRaises(release.EvidenceError):
            release.create_manifest(
                self.root, self.builds, ["second.json", "build.json"]
            )

    def test_record_and_explicit_source_order_do_not_change_manifest(self):
        self.write(self.builds / "second.json", release.canonical(self.record))
        self.write(self.root / "deploy/verify.py", b"host verifier")
        first = release.create_manifest(
            self.root,
            self.builds,
            ["second.json", "build.json"],
            ["deploy/verify.py", "backend/app/main.py"],
        )
        second = release.create_manifest(
            self.root,
            self.builds,
            ["build.json", "second.json"],
            ["backend/app/main.py", "deploy/verify.py"],
        )
        self.assertEqual(release.canonical(first), release.canonical(second))

    def test_secret_paths_traversal_and_absolute_paths_refused(self):
        for name in (
            "../outside",
            "/etc/passwd",
            "a/../b",
            "a//b",
            "a/./b",
            "a\\b",
            ".env",
            "secrets/password",
            "keys/key",
            "backup/payload",
            "app/key.pem",
            "app/key.key",
            "a\nfile",
        ):
            with self.subTest(name=name), self.assertRaises(release.EvidenceError):
                release.read_relative(self.root, name)

    def test_symlink_ancestors_files_and_hardlinks_refused(self):
        self.write(self.base / "outside.py", b"outside")
        target = self.root / "backend/app/main.py"
        target.unlink()
        target.symlink_to(self.base / "outside.py")
        with self.assertRaises(OSError):
            self.manifest()
        target.unlink()
        os.link(self.base / "outside.py", target)
        with self.assertRaises(release.EvidenceError):
            self.manifest()
        (self.base / "alias").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            release.read_relative(self.base / "alias", "backend/poetry.lock")

    def test_fifo_refused_without_blocking(self):
        os.mkfifo(self.root / "pipe")
        with self.assertRaises(release.EvidenceError):
            release.read_relative(self.root, "pipe")

    def test_export_allowlist_excludes_secrets_and_projects_arbitrary_details(self):
        for name in (
            "secrets/password",
            "keys/backup.key",
            "backup/archive.enc",
            "restore/secret",
            "binding/binding.json",
            "models/private",
            "evidence/token.json",
            "evidence/lab-failure.log",
            "evidence/deployment.env",
        ):
            self.write(self.run / name, b"PRIVATE_CANARY")
        raw, digest = self.export()
        self.assertNotIn(b"PRIVATE_CANARY", raw)
        self.assertNotIn(b"Bearer", raw)
        members = self.members(raw)
        self.assertEqual(
            set(members), {"release.json", "checksums.json", "evidence/result.json"}
        )
        result = json.loads(members["evidence/result.json"])
        self.assertEqual(result["cases"]["campaign"], {"status": "failed"})
        self.assertEqual(
            result["counts"], {"passed": 1, "failed": 1, "blocked": 1, "pending": 0}
        )
        self.assertFalse(result["reported_flags"]["all_green"])
        self.assertTrue(release.verify_bundle_bytes(raw, digest)["integrity_verified"])

    def test_export_survives_deleted_run_and_is_byte_deterministic(self):
        first, digest = self.export()
        os.utime(self.run / "evidence/result.json", (50, 50))
        second, second_digest = self.export("second.tar")
        self.assertEqual(first, second)
        self.assertEqual(digest, second_digest)
        shutil.rmtree(self.run)
        self.assertTrue(
            release.verify_bundle_bytes(first, digest)["integrity_verified"]
        )

    def test_archived_0019_and_current_0021_results_remain_exportable(self):
        for case in ("migration_0019", "migration_0021"):
            result = release.project_result(
                release.canonical({"cases": {case: {"status": "passed"}}})
            )
            self.assertEqual(json.loads(result)["cases"][case]["status"], "passed")

    def test_valid_resource_ledger_retained_and_untyped_content_refused(self):
        name = "resources-" + "f" * 32 + ".json"
        project = "nanfo-deploy-verify-" + "c" * 32
        ledger = {
            "containers": {"d" * 64: project},
            "networks": {"e" * 12: project},
            "volumes": {project + "_reports": project},
        }
        self.write(self.run / "evidence" / name, release.canonical(ledger))
        raw, _ = self.export()
        self.assertEqual(json.loads(self.members(raw)["evidence/" + name]), ledger)
        ledger["volumes"]["PRIVATE_CANARY"] = project
        self.write(self.run / "evidence" / name, release.canonical(ledger))
        with self.assertRaises(release.EvidenceError):
            self.export("bad.tar")
        self.assertFalse((self.output / "bad.tar").exists())

    def test_evidence_symlink_refused(self):
        result = self.run / "evidence/result.json"
        result.unlink()
        result.symlink_to(self.builds / "build.json")
        with self.assertRaises(OSError):
            self.export()

    def test_atomic_output_no_clobber_and_private_permissions(self):
        target = self.output / "atomic.json"
        release.publish(target, b"original")
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            release.publish(target, b"replacement")
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()), ["atomic.json"]
        )
        self.output.chmod(0o755)
        with self.assertRaises(release.EvidenceError):
            release.publish(self.output / "other.json", b"data")

    def test_fsync_failure_leaves_no_published_or_partial_output(self):
        with (
            patch.object(release.os, "fsync", side_effect=OSError("disk error")),
            self.assertRaises(OSError),
        ):
            release.publish(self.output / "atomic.json", b"new data")
        self.assertEqual(list(self.output.iterdir()), [])

    def test_output_inside_temporary_run_refused(self):
        manifest = self.output / "release.json"
        release.publish(manifest, release.canonical(self.manifest()))
        with self.assertRaises(release.EvidenceError):
            release.export_bundle(manifest, self.run, self.run / "evidence.tar")

    def test_input_and_archive_bounds(self):
        with (
            patch.object(release, "MAX_TOTAL", 10),
            self.assertRaises(release.EvidenceError),
        ):
            self.export()
        with self.assertRaises(release.EvidenceError):
            release.read_relative(self.root, "backend/poetry.lock", limit=1)
        with (
            patch.object(release, "MAX_ENTRIES", 2),
            self.assertRaises(release.EvidenceError),
        ):
            self.export()

    def test_archive_tamper_truncation_and_trailing_bytes_refused(self):
        raw, digest = self.export()
        for changed in (
            raw.replace(b'"failed"', b'"passed"', 1),
            raw[:1500],
            raw + b"PRIVATE_CANARY",
        ):
            with (
                self.subTest(size=len(changed)),
                self.assertRaises(release.EvidenceError),
            ):
                release.verify_bundle_bytes(changed)
        with self.assertRaises(release.EvidenceError):
            release.verify_bundle_bytes(raw, "0" * 64)
        self.assertTrue(release.verify_bundle_bytes(raw, digest)["integrity_verified"])

    def test_archive_traversal_links_duplicates_and_nonallowlisted_members(self):
        raw, _ = self.export()
        members = self.members(raw)
        for name, kind in (
            ("../escape", tarfile.REGTYPE),
            ("/escape", tarfile.REGTYPE),
            ("secrets/password", tarfile.REGTYPE),
            ("evidence/result.json", tarfile.SYMTYPE),
            ("evidence/result.json", tarfile.LNKTYPE),
            ("evidence/result.json", tarfile.FIFOTYPE),
            ("evidence/result.json", tarfile.REGTYPE),
        ):
            buffer = io.BytesIO()
            with tarfile.open(
                fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT
            ) as archive:
                for existing, data in members.items():
                    entry = tarfile.TarInfo(existing)
                    entry.mode, entry.size = 0o600, len(data)
                    archive.addfile(entry, io.BytesIO(data))
                entry = tarfile.TarInfo(name)
                entry.type, entry.mode = kind, 0o600
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    entry.linkname = "../outside"
                archive.addfile(entry)
            with (
                self.subTest(name=name, kind=kind),
                self.assertRaises(release.EvidenceError),
            ):
                release.verify_bundle_bytes(buffer.getvalue())
        self.assertFalse((self.base / "escape").exists())

    def test_rechecks_secret_projection_even_with_recomputed_checksums(self):
        raw, _ = self.export()
        members = self.members(raw)
        result = json.loads(members["evidence/result.json"])
        result["cases"]["campaign"]["detail"] = "PRIVATE_CANARY"
        members["evidence/result.json"] = release.canonical(result)
        checks = json.loads(members["checksums.json"])
        checks["files"]["evidence/result.json"] = release.descriptor(
            members["evidence/result.json"]
        )
        members["checksums.json"] = release.canonical(checks)
        with self.assertRaises(release.EvidenceError):
            release.verify_bundle_bytes(release.pack(members))

    def test_duplicate_json_nonfinite_unknown_cases_and_invalid_flags_refused(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(release.EvidenceError):
                release.parse_json(raw)
        for value in (
            {"cases": {"PRIVATE_CANARY": {"status": "passed"}}},
            {"cases": {"campaign": {"status": "PRIVATE_CANARY"}}},
            {
                "cases": {"campaign": {"status": "passed"}},
                "all_green": "PRIVATE_CANARY",
            },
        ):
            with self.assertRaises(release.EvidenceError):
                release.project_result(release.canonical(value))

    def test_cli_refusal_hides_untrusted_paths_and_contents(self):
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            code = release.main(
                [
                    "verify-archive",
                    "--archive",
                    str(self.base / "PRIVATE_CANARY"),
                    "--sha256",
                    "0" * 64,
                ]
            )
        self.assertEqual(code, 1)
        self.assertNotIn("PRIVATE_CANARY", stderr.getvalue())

    def test_cli_create_verify_export_archive_roundtrip(self):
        manifest = self.output / "release.json"
        archive = self.output / "cli.tar"
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(
                release.main(
                    [
                        "create",
                        "--root",
                        str(self.root),
                        "--build-root",
                        str(self.builds),
                        "--build-record",
                        "build.json",
                        "--output",
                        str(manifest),
                    ]
                ),
                0,
            )
            self.assertEqual(
                release.main(
                    [
                        "verify",
                        "--root",
                        str(self.root),
                        "--build-root",
                        str(self.builds),
                        "--manifest",
                        str(manifest),
                    ]
                ),
                0,
            )
            self.assertEqual(
                release.main(
                    [
                        "export",
                        "--manifest",
                        str(manifest),
                        "--run-dir",
                        str(self.run),
                        "--output",
                        str(archive),
                    ]
                ),
                0,
            )
            self.assertEqual(
                release.main(
                    [
                        "verify-archive",
                        "--archive",
                        str(archive),
                        "--sha256",
                        release.sha256(archive.read_bytes()),
                    ]
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
