"""Verifier control-plane tests. These do not count as live acceptance evidence."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    "deploy_verify", Path(__file__).parents[1] / "verify.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
PROJECT = "nanfo-deploy-verify-" + "a" * 32


def config():
    return {
        "services": {
            name: {} for name in (*verify.STORES, *verify.WORKERS, "api", "gateway")
        },
        "volumes": {"postgres": {"name": PROJECT + "_postgres"}},
        "networks": {"default": {"name": PROJECT + "_default"}},
    }


class SafetyTests(unittest.TestCase):
    def test_disk_preflight_blocks_below_one_gib_without_mutations(self):
        with (
            patch.object(verify, "run", return_value=b"/var/lib/docker\n") as command,
            patch.object(
                verify.shutil,
                "disk_usage",
                side_effect=[Mock(free=868573184), Mock(free=7936704512)],
            ),
            self.assertRaises(verify.Blocked) as caught,
        ):
            verify.disk_capacity(Path("/tmp/opencode"))
        self.assertIn("1073741824", str(caught.exception))
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0][:2], ["docker", "info"])

    def test_disk_preflight_accepts_boundary(self):
        with (
            patch.object(verify, "run", return_value=b"/var/lib/docker\n"),
            patch.object(verify.shutil, "disk_usage", return_value=Mock(free=1024**3)),
        ):
            self.assertEqual(
                verify.disk_capacity(Path("/tmp/opencode"))["minimum_bytes"], 1024**3
            )

    def test_protected_docker_root_uses_kernel_containing_mount(self):
        with (
            patch.object(verify, "run", return_value=b"/home/.system-data/docker\n"),
            patch.object(
                verify.Path,
                "read_text",
                return_value="1 0 1:1 / / rw - ext4 root rw\n2 1 1:2 / /home rw - ext4 home rw\n",
            ),
            patch.object(
                verify.shutil,
                "disk_usage",
                side_effect=[PermissionError(), Mock(free=2**32), Mock(free=2**32)],
            ) as usage,
        ):
            result = verify.disk_capacity(Path("/tmp/opencode"))
        self.assertEqual(result["capacity_filesystem"], "/home")
        self.assertEqual(usage.call_args_list[1].args[0], Path("/home"))

    def setUp(self):
        self.config = config()
        self.config["services"]["gateway"]["ports"] = [
            {"host_ip": "127.0.0.1", "published": "0", "target": 8080}
        ]

    def validate(self):
        return verify.validate_compose(self.config, PROJECT, Path("/tmp/private"))

    def test_full_internal_stack_random_loopback_is_accepted(self):
        self.assertEqual(self.validate()["volumes"], [PROJECT + "_postgres"])

    def test_every_store_and_worker_must_be_present(self):
        del self.config["services"]["alert-worker"]
        with self.assertRaises(verify.VerificationError):
            self.validate()

    def test_existing_project_names_refused(self):
        for project in (
            "nanfo",
            "nanfo-emulation",
            PROJECT + "-restore",
            "nanfo-deploy-verify-x",
        ):
            with (
                self.subTest(project=project),
                self.assertRaises(verify.VerificationError),
            ):
                verify.validate_compose(self.config, project, Path("/tmp/private"))

    def test_store_host_port_refused_even_loopback(self):
        self.config["services"]["postgres"]["ports"] = [
            {"host_ip": "127.0.0.1", "published": "0"}
        ]
        with self.assertRaises(verify.VerificationError):
            self.validate()

    def test_gateway_fixed_or_public_port_refused(self):
        for port in (
            {"host_ip": "0.0.0.0", "published": "0"},
            {"host_ip": "127.0.0.1", "published": "8080"},
        ):
            self.config["services"]["gateway"]["ports"] = [port]
            with self.assertRaises(verify.VerificationError):
                self.validate()

    def test_external_or_host_volume_refused(self):
        for volume in (
            {"name": "old_lab"},
            {"name": PROJECT + "_db", "external": True},
            {"name": PROJECT + "_db", "driver_opts": {"device": "/var/lib"}},
        ):
            self.config["volumes"]["postgres"] = volume
            with self.assertRaises(verify.VerificationError):
                self.validate()

    def test_anonymous_volume_refused(self):
        self.config["services"]["api"]["volumes"] = [
            {"type": "volume", "target": "/state"}
        ]
        with self.assertRaises(verify.VerificationError):
            self.validate()

    def test_source_or_socket_mount_refused(self):
        for path in (
            "/var/run/docker.sock",
            str(verify.ROOT),
            "/tmp/private/../oldlab",
        ):
            self.config["services"]["api"]["volumes"] = [
                {"type": "bind", "source": path}
            ]
            with self.assertRaises(verify.VerificationError):
                self.validate()

    def test_privilege_only_in_disconnected_opt_in_lab(self):
        self.config["services"]["lab"] = {
            "privileged": True,
            "profiles": ["lab"],
            "network_mode": "none",
        }
        self.validate()
        self.config["services"]["lab"]["network_mode"] = "host"
        with self.assertRaises(verify.VerificationError):
            self.validate()

    def test_fixed_container_name_and_host_pid_refused(self):
        for field, value in (
            ("container_name", "oldlab"),
            ("pid", "host"),
            ("privileged", True),
        ):
            self.config["services"]["api"] = {field: value}
            with self.assertRaises(verify.VerificationError):
                self.validate()

    def test_private_write_exclusive_and_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            verify.private_write(path, b"protected")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                verify.private_write(path, b"overwrite")

    def test_private_write_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.symlink_to(Path(directory) / "other")
            with self.assertRaises(FileExistsError):
                verify.private_write(path, b"protected")

    def test_subprocess_redacts_failures_and_drops_host_settings(self):
        failure = Mock(returncode=1)
        failure.communicate.return_value = (b"password-do-not-print", b"secret")
        with (
            patch.dict(
                os.environ,
                {
                    "POSTGRES_PASSWORD": "secret",
                    "PYTHONPATH": "host-env",
                    "COMPOSE_PROJECT_NAME": "old",
                },
            ),
            patch.object(verify.subprocess, "Popen", return_value=failure) as command,
        ):
            with self.assertRaises(verify.VerificationError) as caught:
                verify.run(["docker", "version"])
            self.assertNotIn("secret", str(caught.exception))
            env = command.call_args.kwargs["env"]
            self.assertNotIn("POSTGRES_PASSWORD", env)
            self.assertNotIn("PYTHONPATH", env)
            self.assertNotIn("COMPOSE_PROJECT_NAME", env)

    def test_command_timeout_is_redacted(self):
        process = Mock(pid=999)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["secret"], 1),
            (b"", b""),
        ]
        with (
            patch.object(verify.subprocess, "Popen", return_value=process),
            patch.object(verify.os, "killpg") as kill,
        ):
            with self.assertRaises(verify.VerificationError) as caught:
                verify.run(["docker", "version"])
            self.assertNotIn("secret", str(caught.exception))
        kill.assert_called_once_with(999, verify.signal.SIGKILL)


class MatrixTests(unittest.TestCase):
    def test_sensitive_runtime_result_is_never_recorded(self):
        matrix = verify.Matrix()
        value = matrix.case(
            "bootstrap_login", lambda: {"access_token": "secret"}, record=False
        )
        self.assertEqual(value["access_token"], "secret")
        self.assertNotIn("secret", json.dumps(matrix.result()))

    def test_pending_is_not_passed(self):
        matrix = verify.Matrix()
        result = matrix.result()
        self.assertFalse(result["core_passed"])
        self.assertFalse(result["step15_complete"])
        self.assertEqual(result["counts"]["pending"], len(verify.CASES))

    def test_optional_blocked_is_never_all_green(self):
        matrix = verify.Matrix()
        for name in verify.CASES:
            matrix.case(name, lambda: "actual test")
        matrix.block("model_diagnostic", "Frozen image unavailable")
        self.assertTrue(matrix.result()["step15_complete"])
        self.assertFalse(matrix.result()["all_green"])
        matrix.block("lab_congestion", "Profile not configured")
        self.assertFalse(matrix.result()["step15_complete"])

    def test_cleanup_failure_invalidates_completion(self):
        matrix = verify.Matrix()
        for name in verify.CASES:
            matrix.case(name, lambda: "actual test")
        with self.assertRaises(verify.VerificationError):
            matrix.case("cleanup", lambda: verify.check(False, "Cleanup failed"))
        self.assertFalse(matrix.result()["core_passed"])

    def test_untrusted_exception_text_not_recorded(self):
        matrix = verify.Matrix()
        with self.assertRaises(ValueError):
            matrix.case(
                "bootstrap_login", Mock(side_effect=ValueError("password=secret"))
            )
        self.assertNotIn("secret", json.dumps(matrix.result(final=True)))
        self.assertEqual(matrix.result(final=True)["counts"]["pending"], 0)


class RegistryTests(unittest.TestCase):
    def test_existing_resources_prevent_registration(self):
        registry = verify.Registry(Path("/tmp/private"))
        with (
            patch.object(verify, "run", return_value=b"existing"),
            self.assertRaises(verify.VerificationError),
        ):
            registry.fresh(PROJECT)
        self.assertNotIn(PROJECT, registry.projects)

    def test_cleanup_exact_ids_only_and_no_prune(self):
        registry = verify.Registry(Path("/tmp/private"))
        registry.projects.add(PROJECT)
        registry.containers["owned-id"] = PROJECT
        registry.volumes[PROJECT + "_db"] = PROJECT

        def command(args, **kwargs):
            if "ls" in args:
                return b"owned-id\n"
            if "inspect" in args:
                return json.dumps(
                    [
                        {
                            "Config": {
                                "Labels": {"com.docker.compose.project": PROJECT}
                            },
                            "Labels": {"com.docker.compose.project": PROJECT},
                        }
                    ]
                ).encode()
            return b""

        with patch.object(verify, "run", side_effect=command) as run:
            registry.cleanup()
        calls = [call.args[0] for call in run.call_args_list]
        self.assertIn(["docker", "container", "rm", "-f", "owned-id"], calls)
        self.assertIn(["docker", "volume", "rm", PROJECT + "_db"], calls)
        self.assertFalse(any("prune" in call or "down" in call for call in calls))

    def test_changed_ownership_is_not_removed(self):
        registry = verify.Registry(Path("/tmp/private"))
        registry.projects.add(PROJECT)
        registry.containers["owned-id"] = PROJECT
        with (
            patch.object(
                verify,
                "run",
                side_effect=[
                    b"owned-id\n",
                    json.dumps(
                        [
                            {
                                "Config": {
                                    "Labels": {"com.docker.compose.project": "old-lab"}
                                }
                            }
                        ]
                    ).encode(),
                ],
            ) as command,
            self.assertRaises(verify.VerificationError),
        ):
            registry.cleanup()
        self.assertEqual(command.call_count, 2)

    def test_already_removed_container_is_not_cleanup_failure(self):
        registry = verify.Registry(Path("/tmp/private"))
        registry.projects.add(PROJECT)
        registry.containers["old-id"] = PROJECT
        with patch.object(verify, "run", return_value=b"") as command:
            registry.cleanup()
        self.assertEqual(command.call_count, 1)

    def test_cleanup_deadline_is_total_not_per_resource(self):
        registry = verify.Registry(Path("/tmp/private"))
        registry.containers["owned-id"] = PROJECT
        with (
            patch.object(verify.time, "monotonic", side_effect=[0, 121]),
            patch.object(verify, "run") as command,
            self.assertRaises(verify.VerificationError),
        ):
            registry.cleanup(timeout=120)
        command.assert_not_called()


class APIAndWorkflowTests(unittest.TestCase):
    def test_missing_pinned_images_block_before_any_container_creation(self):
        args = Mock(
            reuse_build_record=Path("record.json"),
            backend_image="sha256:" + "a" * 64,
            frontend_image="sha256:" + "b" * 64,
            neo4j_image="sha256:" + "c" * 64,
            lab=True,
            lab_image="sha256:" + "d" * 64,
            ai_image=None,
        )
        record = {
            "image_id": args.backend_image,
            "host_site_packages_used": False,
            "dependency_install": "poetry check --lock && poetry install --only main",
        }
        registry = Mock()
        with (
            patch.object(
                verify.Path, "read_bytes", return_value=json.dumps(record).encode()
            ),
            patch.object(
                verify.Path,
                "read_text",
                return_value="npm ci " + args.frontend_image + " " + args.neo4j_image,
            ),
            patch.object(verify, "run", return_value=b"") as command,
            self.assertRaises(verify.Blocked) as caught,
        ):
            verify.referenced_build(args, registry)
        self.assertIn(args.lab_image, str(caught.exception))
        registry.fresh.assert_not_called()
        self.assertEqual(
            command.call_args.args[0], ["docker", "image", "ls", "-q", "--no-trunc"]
        )

    def test_reuse_refuses_implicit_ai_and_lab_builds(self):
        base = ["--live", "--agents-idle", "--reuse-build-record", "deploy/README.md"]
        for flags in (base, [*base, "--backend-image", "tag"]):
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                verify.parse_args(flags)
        images = [
            "--backend-image",
            "sha256:" + "a" * 64,
            "--frontend-image",
            "sha256:" + "b" * 64,
            "--neo4j-image",
            "sha256:" + "c" * 64,
        ]
        for flag in ("--model", "--lab"):
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                verify.parse_args([*base, *images, flag])
        self.assertTrue(verify.parse_args([*base, *images]).reuse_build_record)
        args = verify.parse_args(
            [*base, *images, "--model", "--ai-image", "sha256:" + "d" * 64]
        )
        self.assertEqual(args.ai_image, "sha256:" + "d" * 64)

    def test_runtime_fingerprint_excludes_build_records_not_runtime(self):
        for path in (
            "deploy/core-build-new.json",
            "deploy/README.md",
            "deploy/tests/test_verify.py",
            "deploy/verify.py",
        ):
            self.assertFalse(verify.runtime_source(path))
        for path in (
            "deploy/maintenance.py",
            "deploy/backup_restore.py",
            "backend/app/core/config.py",
            "frontend/src/main.tsx",
        ):
            self.assertTrue(verify.runtime_source(path))

    def test_missing_ai_image_blocks_without_building_or_changing_stack(self):
        source, target = Mock(), Mock()
        source.env = {"NANFO_AI_IMAGE": "sha256:" + "d" * 64}
        with (
            patch.object(verify.Path, "is_file", return_value=True),
            patch.object(verify, "run", return_value=b""),
            self.assertRaises(verify.Blocked),
        ):
            verify.diagnose_model(
                source, target, Mock(), "network", Path("/tmp/new"), Mock()
            )
        source.compose.assert_not_called()

    def test_operator_cli_invokes_delivered_tool_and_registers_even_failure(self):
        stack = verify.Stack(
            PROJECT,
            [Path("/tmp/private/compose.json")],
            {"NANFO_PROJECT": PROJECT},
            Mock(),
        )
        with (
            patch.object(verify.Path, "is_file", return_value=True),
            patch.object(
                verify, "run", side_effect=verify.VerificationError("Command failed")
            ) as command,
            self.assertRaises(verify.VerificationError),
        ):
            verify.operator_tool(
                stack,
                "backup",
                Path("/tmp/private/backup"),
                Path("/tmp/private/keys/key"),
            )
        argv = command.call_args.args[0]
        self.assertIn(str(verify.ROOT / "deploy/backup_restore.py"), argv)
        self.assertIn("--encryption-key-file", argv)
        self.assertNotIn("--password", argv)
        stack.registry.register.assert_called_once_with(PROJECT)

    def test_restore_rejects_source_project_before_operator(self):
        source = Mock(project=PROJECT)
        target = Mock(project=PROJECT)
        with (
            patch.object(verify, "operator_tool") as tool,
            self.assertRaises(verify.VerificationError),
        ):
            verify.restore_stack(target, source, Path("/tmp/backup"), Path("/tmp/key"))
        tool.assert_not_called()

    def test_restore_requires_real_operator_success_and_distinct_volumes(self):
        project2 = "nanfo-deploy-verify-" + "b" * 32
        registry = Mock(volumes={PROJECT + "_db": PROJECT, project2 + "_db": project2})
        source = Mock(project=PROJECT)
        target = Mock(project=project2, registry=registry)
        with (
            patch.object(
                verify,
                "operator_tool",
                return_value={
                    "status": "restored_verified",
                    "writers": "stopped",
                    "verification": {"neo4j_graph": {"nodes": 10}},
                },
            ),
            patch.object(
                verify.Path,
                "read_bytes",
                return_value=b'{"checkpoint":{"neo4j_graph":{"nodes":10}}}',
            ),
        ):
            result = verify.restore_stack(
                target, source, Path("/tmp/backup"), Path("/tmp/key")
            )
        self.assertEqual(result["fresh_distinct_volumes"], 1)
        with (
            patch.object(
                verify,
                "operator_tool",
                return_value={"status": "restored", "writers": "running"},
            ),
            self.assertRaises(verify.VerificationError),
        ):
            verify.restore_stack(target, source, Path("/tmp/backup"), Path("/tmp/key"))

    def test_live_and_agents_idle_are_both_mandatory(self):
        for flags in ([], ["--live"], ["--agents-idle"]):
            with (
                self.subTest(flags=flags),
                patch("sys.stderr"),
                self.assertRaises(SystemExit),
            ):
                verify.parse_args(flags)
        args = verify.parse_args(["--live", "--agents-idle", "--lab", "--model"])
        self.assertTrue(args.live and args.agents_idle and args.lab and args.model)

    def test_parse_args_has_no_docker_side_effects(self):
        with patch.object(verify, "run") as command:
            verify.parse_args(["--live", "--agents-idle"])
        command.assert_not_called()

    def test_api_refuses_remote_or_credential_url(self):
        for url in (
            "http://example.com",
            "http://127.0.0.1:80@evil",
            "https://127.0.0.1:80",
            "http://127.0.0.1:80/path",
        ):
            with self.assertRaises(verify.VerificationError):
                verify.API(url)

    def test_canonical_success_is_required(self):
        api = verify.API("http://127.0.0.1:12345")
        with (
            patch.object(
                api, "raw", return_value=(200, {}, b'{"success":false,"data":{}}')
            ),
            self.assertRaises(verify.VerificationError),
        ):
            api.request("GET", "/ready")

    def test_readiness_503_is_not_transient_success(self):
        api = verify.API("http://127.0.0.1:12345")
        with patch.object(api, "raw", return_value=(503, {}, b'{"success":false}')):
            self.assertFalse(api.ready())

    def test_report_download_rejects_tamper(self):
        api = Mock()
        api.request.return_value = {
            "status": "generated",
            "artifacts": [
                {
                    "size_bytes": 4,
                    "checksum_sha256": verify.digest(b"good"),
                    "media_type": "text/csv",
                }
            ],
        }
        api.raw.return_value = (
            200,
            {"Content-Length": "4", "Content-Type": "text/csv"},
            b"evil",
        )
        with self.assertRaises(verify.VerificationError):
            verify.download_report(api, "workspace", {"report_id": "report"}, "csv")

    def test_actual_pdf_stream_content_is_required(self):
        import base64
        import zlib

        for text, valid in (
            (b"(simulation /loss_pct | 45.0) Tj", True),
            (b"(placeholder) Tj", False),
        ):
            content = (
                b"%PDF-1.3\n/Type /Page\nstream\n"
                + base64.a85encode(zlib.compress(text))
                + b"~>endstream\n%%EOF\n"
            )
            api = Mock()
            api.request.return_value = {
                "report_id": "report",
                "snapshot_sha256": "frozen",
                "status": "generated",
                "artifacts": [
                    {
                        "size_bytes": len(content),
                        "checksum_sha256": verify.digest(content),
                        "media_type": "application/pdf",
                    }
                ],
            }
            api.raw.return_value = (
                200,
                {
                    "Content-Length": str(len(content)),
                    "Content-Type": "application/pdf",
                },
                content,
            )
            if valid:
                self.assertEqual(
                    verify.download_report(
                        api, "workspace", {"report_id": "report"}, "pdf"
                    )["sha256"],
                    verify.digest(content),
                )
            else:
                with self.assertRaises(verify.VerificationError):
                    verify.download_report(
                        api, "workspace", {"report_id": "report"}, "pdf"
                    )

    def test_binding_reads_installed_manifest_and_uses_only_api_inventory(self):
        stack, api = Mock(), Mock()
        stack.project = PROJECT
        manifest = json.dumps(
            {
                "topology_id": "campus-small-v1",
                "switches": [{"name": "s1", "dpid": "0000000000000001"}],
                "hosts": [],
                "port_capacities_mbps": {},
            }
        ).encode()
        canonical = {
            "version": 1,
            "topology_id": "campus-small-v1",
            "switches": {"0000000000000001": "device"},
            "hosts": {},
            "actor_user_id": "actor",
            "workspace_id": "workspace",
            "network_id": "network",
            "port_capacities_mbps": {"0000000000000001:1": 10.0},
        }
        stack.compose.side_effect = [manifest, json.dumps(canonical).encode()]
        api.request.side_effect = [
            {"user_id": "actor"},
            {"org_id": "org"},
            {"workspace_id": "workspace"},
            {"network_id": "network"},
            {"device_id": "device"},
        ]
        binding = verify.bind_lab(stack, api)
        self.assertEqual(binding["switches"], {"0000000000000001": "device"})
        self.assertEqual(binding["actor_user_id"], "actor")
        self.assertEqual(api.request.call_count, 5)
        self.assertEqual(binding, canonical)
        self.assertIn(
            "EmulationBinding.model_validate_json", stack.compose.call_args.args[-1]
        )

    def test_real_worker_pid_not_tini_receives_sigstop(self):
        stack = verify.Stack(PROJECT, [], {}, Mock())
        with (
            patch.object(stack, "inspect_service"),
            patch.object(stack, "compose") as command,
        ):
            stack.signal("report-worker", "SIGSTOP")
        script = command.call_args.args[-1]
        self.assertIn("WORKER_HEARTBEAT_PATH", script)
        self.assertIn("pid>1", script)
        self.assertIn("signal.SIGSTOP", script)

    def test_frontend_fallback_html_is_not_asset_success(self):
        api = Mock()
        api.raw.side_effect = [
            (
                200,
                {"Content-Type": "text/html"},
                b'<div id="root"></div><script src="/assets/main.js"></script>',
            ),
            (200, {"Content-Type": "text/html"}, b"fallback" * 100),
        ]
        with self.assertRaises(verify.VerificationError):
            verify.frontend_smoke(api)

    def test_worker_always_continues_after_failed_stale_check(self):
        stack = Mock()
        with (
            patch.object(
                verify, "until", side_effect=verify.VerificationError("Deadline")
            ),
            self.assertRaises(verify.VerificationError),
        ):
            verify.heartbeat_outage(stack)
        self.assertEqual(
            stack.signal.call_args_list[-1].args, ("report-worker", "SIGCONT")
        )

    def test_database_always_restarts_after_failed_negative_probe(self):
        stack, api = Mock(), Mock()
        with (
            patch.object(
                verify, "until", side_effect=verify.VerificationError("Deadline")
            ),
            self.assertRaises(verify.VerificationError),
        ):
            verify.database_outage(stack, api)
        self.assertEqual(stack.compose.call_args_list[-1].args, ("start", "postgres"))


if __name__ == "__main__":
    unittest.main()
