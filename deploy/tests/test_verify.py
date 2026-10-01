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
PERMISSIONS = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


def backend_service(secret_volume="runtime_secrets_worker", role="worker"):
    """Minimal rendered backend service satisfying the ADR-028 C24 role policy."""
    return {
        "environment": {"APP_ENV": "production", "NANFO_SERVICE_ROLE": role, "REDIS_USERNAME": "nanfo"},
        "volumes": [{"type": "volume", "source": secret_volume, "target": "/run/secrets", "read_only": True}],
    }


def config():
    services = {name: {} for name in verify.STORES}
    services.update({name: backend_service() for name in verify.APPLICATION})
    services["api"] = backend_service("runtime_secrets_api", "api")
    services["gateway"] = {
        "environment": {"NANFO_GATEWAY_TRUSTED_HOP": "172.31.87.1"},
        "networks": {"proxy": {"ipv4_address": "172.30.27.254"}, "gateway": None},
    }
    return {
        "services": services,
        "volumes": {
            name: {"name": PROJECT + "_" + name}
            for name in ("postgres", "runtime_secrets_api", "runtime_secrets_worker", "execution_secrets", "lab_secrets")
        },
        "networks": {
            "default": {"name": PROJECT + "_default"},
            "gateway": {"name": PROJECT + "_gateway",
                        "ipam": {"config": [{"subnet": "172.31.87.0/24", "gateway": "172.31.87.1"}]}},
        },
    }


def successor_lab():
    return {
        "profiles": ["lab"], "network_mode": "none", "cap_drop": ["ALL"],
        "cap_add": ["NET_ADMIN", "NET_RAW", "SYS_ADMIN"], "security_opt": ["no-new-privileges:true"],
        "read_only": True, "tmpfs": ["/run:rw,exec,nosuid,nodev,size=64m", "/tmp:rw,exec,nosuid,nodev,size=64m"],
        "volumes": [{"type": "volume", "source": "lab_secrets", "target": "/run/nanfo-lab-key", "read_only": True}],
    }


def gateway_response(status=200, content_type="text/html", body=b"", **extra):
    headers = {**verify.GATEWAY_HEADERS, "Permissions-Policy": PERMISSIONS, "Content-Type": content_type, **extra}
    return status, headers, body


def rendered(*names, environ=None):
    """Approximate `docker compose config --format json` of shipped files (no Docker CLI)."""
    import re
    import yaml

    environ = environ or {}

    def interpolate(value):
        if isinstance(value, str):
            return re.sub(
                r"\$\{([A-Z0-9_]+)(?:(:?[-?])([^}]*))?\}",
                lambda match: environ.get(match.group(1))
                or (match.group(3) if match.group(2) in (":-", "-") else "placeholder"),
                value,
            )
        if isinstance(value, list):
            return [interpolate(item) for item in value]
        if isinstance(value, dict):
            return {key: interpolate(item) for key, item in value.items()}
        return value

    services, volumes, networks = {}, {}, {}
    for name in names:
        document = interpolate(yaml.safe_load((verify.ROOT / "deploy" / name).read_text()))
        services.update(document.get("services", {}))
        volumes.update(document.get("volumes") or {})
        networks.update(document.get("networks") or {})
    for service in services.values():
        mounts = []
        for mount in service.get("volumes", []):
            if isinstance(mount, str):
                source, target, *mode = mount.split(":")
                mount = {"type": "volume", "source": source, "target": target, "read_only": mode == ["ro"]}
            mounts.append(mount)
        service["volumes"] = mounts
        if isinstance(service.get("networks"), list):
            service["networks"] = {network: None for network in service["networks"]}
    return {
        "services": services,
        "volumes": {name: {"name": PROJECT + "_" + name} for name in volumes},
        "networks": {name: {**(value or {}), "name": PROJECT + "_" + name} for name, value in networks.items()},
    }


class SafetyTests(unittest.TestCase):
    def test_stage_failure_reports_only_typed_codes_and_keeps_private_log(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (
            b"",
            json.dumps(
                {
                    "status": "refused",
                    "stage": "backup_stop_stores",
                    "error_type": "OperationError",
                    "reason": "secret-canary",
                }
            ).encode(),
        )
        with tempfile.TemporaryDirectory() as directory:
            diagnostic = Path(directory) / "operator.private.log"
            with (
                patch.object(verify.subprocess, "Popen", return_value=process),
                self.assertRaises(verify.VerificationError) as error,
            ):
                verify.run(
                    ["operator"], safe_errors=("known",), private_diagnostic=diagnostic
                )
            self.assertIn("backup_stop_stores (OperationError)", str(error.exception))
            self.assertNotIn("secret-canary", str(error.exception))
            self.assertEqual(diagnostic.stat().st_mode & 0o777, 0o600)

    def test_encrypted_backup_checks_exact_magic_length(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"NANFO-GCM-2\0" + b"ciphertext"
            path = root / "volume-0000.tar.gcm"
            verify.private_write(path, payload)
            key = root / "key"
            verify.private_write(key, b"x" * 32)
            manifest = {
                "format": 2,
                "project": PROJECT,
                "complete": True,
                "volumes": [
                    {
                        "logical": "db",
                        "file": path.name,
                        "sha256": verify.digest(payload),
                    }
                ],
                "checkpoint": {"neo4j_graph": {}},
            }
            raw = json.dumps(manifest).encode()
            verify.private_write(root / "manifest.json", raw)
            # The verifier's independent HKDF derivation equals the delivered tool's.
            from deploy import backup_restore

            mac_key = verify.backup_mac_key(b"x" * 32, 2)
            self.assertEqual(mac_key, backup_restore.backup_keys(b"x" * 32, 2).mac)
            self.assertNotEqual(mac_key, b"x" * 32)
            verify.private_write(
                root / "manifest.hmac",
                verify.hmac.new(mac_key, raw, verify.hashlib.sha256)
                .hexdigest()
                .encode(),
            )
            stack = Mock(project=PROJECT)
            stack.registry.volumes = {PROJECT + "_db": PROJECT}
            stack.inspect_service.return_value = {"State": {"Running": False}}

            def backup(*, runs):
                return (
                    patch.object(
                        verify,
                        "operator_tool",
                        side_effect=[
                            {"status": "backed_up", "writers": "stopped"},
                            {"status": "authenticated"},
                        ],
                    ),
                    patch.object(
                        verify,
                        "run",
                        side_effect=runs,
                    ),
                )

            volumes = json.dumps([{"Labels": {"com.docker.compose.volume": "db"}}]).encode()
            first, second = backup(runs=[b"", volumes])
            with first, second:
                result = verify.encrypted_backup(stack, root, key)
            self.assertEqual((result["encrypted_volumes"], result["format"]), (1, 2))
            checked = {call.args[0] for call in stack.inspect_service.call_args_list}
            self.assertTrue(set(verify.SUPERVISED) <= checked)
            # A v1 payload magic under a v2 manifest is refused.
            path.unlink()
            verify.private_write(path, b"NANFO-GCM-1\0ciphertext")
            manifest["volumes"][0]["sha256"] = verify.digest(path.read_bytes())
            raw = json.dumps(manifest).encode()
            (root / "manifest.json").unlink()
            (root / "manifest.hmac").unlink()
            verify.private_write(root / "manifest.json", raw)
            verify.private_write(root / "manifest.hmac", verify.hmac.new(mac_key, raw, verify.hashlib.sha256).hexdigest().encode())
            first, second = backup(runs=[b"", volumes])
            with first, second, self.assertRaises(verify.VerificationError) as caught:
                verify.encrypted_backup(stack, root, key)
            self.assertIn("segmented GCM", str(caught.exception))

    def test_current_tool_backup_must_be_format_2(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "key"
            verify.private_write(key, b"x" * 32)
            raw = json.dumps({"project": PROJECT, "complete": True, "volumes": []}).encode()
            verify.private_write(root / "manifest.json", raw)
            verify.private_write(root / "manifest.hmac", verify.hmac.new(b"x" * 32, raw, verify.hashlib.sha256).hexdigest().encode())
            stack = Mock(project=PROJECT)
            stack.inspect_service.return_value = {"State": {"Running": False}}
            with (
                patch.object(verify, "operator_tool", return_value={"status": "backed_up", "writers": "stopped"}),
                patch.object(verify, "run", return_value=b""),
                self.assertRaises(verify.VerificationError) as caught,
            ):
                verify.encrypted_backup(stack, root, key)
            self.assertIn("format 2", str(caught.exception))

    def test_profile_inventory_is_complete_without_enabling_lifecycle_profiles(self):
        stack = verify.Stack(PROJECT, [Path("/tmp/compose.json")], {}, Mock(directory=Path("/tmp")))
        with patch.object(verify, "run", return_value=b"{}") as command:
            stack.compose("config", "--format", "json")
            self.assertIn("--profile", command.call_args.args[0])
            stack.compose("up", "-d", "api")
            self.assertNotIn("--profile", command.call_args.args[0])

    def test_operator_diagnostic_only_accepts_exact_allowlisted_reason(self):
        for reason, expected in (
            ("Known refusal", "Operator refused: Known refusal"),
            ("secret-canary", "output withheld"),
        ):
            process = Mock(returncode=1)
            process.communicate.return_value = (
                b"",
                json.dumps({"status": "refused", "reason": reason}).encode(),
            )
            with (
                patch.object(verify.subprocess, "Popen", return_value=process),
                self.assertRaises(verify.VerificationError) as error,
            ):
                verify.run(["operator"], safe_errors=("Known refusal",))
            self.assertIn(expected, str(error.exception))
            self.assertNotIn("secret-canary", str(error.exception))

    def test_current_schema_requires_single_0030(self):
        stack = Mock()
        for value in (b"0019\n", b"0024\n", b"0026\n", b"0027\n", b"0028\n", b"0029\n",
                      b"0030\n0029\n", b""):
            stack.compose.return_value = value
            with self.subTest(value=value), self.assertRaises(verify.VerificationError):
                verify.installed_schema(stack)
        stack.compose.return_value = b"0030\n"
        self.assertEqual(verify.installed_schema(stack), "0030")
        self.assertIn("migration_0030", verify.CASES)
        for historical in ("migration_0029", "migration_0028", "migration_0027", "migration_0019"):
            self.assertNotIn(historical, verify.CASES)

    def test_network_publisher_required_for_verifier_lifecycle(self):
        self.assertIn("network-outbox-worker", verify.WORKERS)
        del self.config["services"]["network-outbox-worker"]
        with self.assertRaises(verify.VerificationError):
            self.validate()

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
        result = self.validate()
        self.assertEqual(result["volumes"], sorted(value["name"] for value in self.config["volumes"].values()))
        self.assertEqual(result["policy"]["lab"], "absent")
        self.assertIn("stream-retention", result["policy"]["backend_services"])

    def test_every_store_and_worker_must_be_present(self):
        for name in ("alert-worker", "stream-retention", "telemetry-retention", "asset-gc"):
            self.setUp()
            del self.config["services"][name]
            with self.subTest(name=name), self.assertRaises(verify.VerificationError):
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

    def test_privilege_only_in_acknowledged_frozen_disconnected_opt_in_lab(self):
        self.config["services"]["lab"] = {
            "privileged": True,
            "profiles": ["lab"],
            "network_mode": "none",
        }
        with self.assertRaises(verify.VerificationError) as caught:
            self.validate()
        self.assertIn("frozen overlay acknowledgement", str(caught.exception))
        self.config["services"]["lab"]["labels"] = {"org.nanfo.lab.frozen-acknowledged": "1"}
        self.assertEqual(self.validate()["policy"]["lab"], "frozen")
        self.config["services"]["lab"]["network_mode"] = "host"
        with self.assertRaises(verify.VerificationError):
            self.validate()

    def test_successor_lab_requires_the_c23_least_privilege_profile(self):
        self.config["services"]["lab"] = successor_lab()
        self.assertEqual(self.validate()["policy"]["lab"], "successor")
        for field, value in (
            ("cap_add", ["NET_ADMIN", "SYS_PTRACE"]),
            ("cap_drop", []),
            ("security_opt", []),
            ("read_only", False),
            ("tmpfs", ["/run:rw,exec,size=64m"]),
            ("volumes", [{"type": "volume", "source": "runtime_secrets_worker", "target": "/run/secrets"}]),
            ("volumes", [{"type": "bind", "source": "/tmp/private/x", "target": "/x"}]),
            ("profiles", []),
        ):
            self.config["services"]["lab"] = {**successor_lab(), field: value}
            with self.subTest(field=field, value=value), self.assertRaises(verify.VerificationError):
                self.validate()

    def test_shipped_compose_files_satisfy_the_verifier_policy(self):
        base = rendered("compose.yaml")
        policy = verify.validate_runtime_policy(base)
        self.assertEqual(policy["lab"], "absent")
        self.assertTrue(verify.BACKEND_SERVICES - {"api2", "fleet-worker"} <= set(policy["backend_services"]))
        for name, service in base["services"].items():
            self.assertLessEqual(set(service.get("cap_add") or []), verify.CAPABILITIES.get(name, frozenset()), name)
        successor = rendered("compose.yaml", "compose.lab.yaml")
        self.assertEqual(verify.validate_runtime_policy(successor)["lab"], "successor")
        frozen = rendered("compose.yaml", "compose.lab.frozen.yaml")
        with self.assertRaises(verify.VerificationError):
            verify.validate_runtime_policy(frozen)  # unacknowledged
        frozen = rendered("compose.yaml", "compose.lab.frozen.yaml", environ={"NANFO_LAB_FROZEN": "1"})
        self.assertEqual(verify.validate_runtime_policy(frozen)["lab"], "frozen")

    def test_role_secret_and_acl_policy_is_enforced_per_service(self):
        cases = (
            ("report-worker", lambda svc: svc["volumes"][0].update(source="runtime_secrets_api")),
            ("report-worker", lambda svc: svc["environment"].update(NANFO_SERVICE_ROLE="api")),
            ("stream-retention", lambda svc: svc["environment"].pop("APP_ENV")),
            ("asset-gc", lambda svc: svc["environment"].pop("REDIS_USERNAME")),
            ("api", lambda svc: svc["volumes"][0].update(source="runtime_secrets_worker")),
            ("api", lambda svc: svc["environment"].update(JWT_SECRET_KEY="inline")),
            ("alert-worker", lambda svc: svc["volumes"].append(
                {"type": "volume", "source": "execution_secrets", "target": "/run/nanfo-lab-key"})),
            ("simulation-worker", lambda svc: svc.update(cap_add=["NET_ADMIN"])),
            ("redis", lambda svc: svc.update(cap_add=["SYS_ADMIN"])),
            ("gateway", lambda svc: svc["environment"].update(NANFO_GATEWAY_TRUSTED_HOP="172.31.87.9")),
            ("gateway", lambda svc: svc["networks"].update(private=None)),
        )
        for name, mutate in cases:
            self.setUp()
            mutate(self.config["services"][name])
            with self.subTest(name=name), self.assertRaises(verify.VerificationError):
                self.validate()
        self.setUp()
        self.config["services"]["execution-worker"]["volumes"].append(
            {"type": "volume", "source": "execution_secrets", "target": "/run/nanfo-lab-key", "read_only": True})
        self.config["services"]["redis"]["cap_add"] = ["CHOWN", "DAC_OVERRIDE", "SETUID", "SETGID"]
        self.validate()

    def test_fixed_container_name_and_host_pid_refused(self):
        for field, value in (
            ("container_name", "oldlab"),
            ("pid", "host"),
            ("privileged", True),
        ):
            self.setUp()
            self.config["services"]["api"][field] = value
            with self.subTest(field=field), self.assertRaises(verify.VerificationError):
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
            redis_image="sha256:" + "e" * 64,
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
        self.assertIn(args.redis_image, str(caught.exception))
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
        # The ACL-entrypoint Redis image (Dockerfile.redis) is pinned as well.
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            verify.parse_args([*base, *images])
        images += ["--redis-image", "sha256:" + "e" * 64]
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
            "deploy/manage.py",
        ):
            self.assertFalse(verify.runtime_source(path))
        for path in (
            "deploy/maintenance.py",
            "deploy/backup_restore.py",
            "deploy/supervise.py",
            "deploy/secret_rotation.py",
            "deploy/Dockerfile.redis",
            "deploy/Dockerfile.backend.dockerignore",
            "deploy/nginx-security-headers.conf",
            "deploy/gateway-entrypoint.sh",
            "deploy/compose.lab.frozen.yaml",
            "backend/app/core/config.py",
            "frontend/src/main.tsx",
        ):
            self.assertTrue(verify.runtime_source(path))

    def test_installed_parity_expects_exactly_the_image_sources(self):
        sources = verify.image_runtime_sources()
        self.assertIn("deploy/entrypoint.py", sources)
        self.assertIn("deploy/supervise.py", sources)
        self.assertIn("backend/scripts/stream_retention.py", sources)
        self.assertIn("emulation/runner.py", sources)
        for name in sources:
            parts = Path(name).parts
            self.assertNotIn("tests", parts)
            self.assertNotIn("__pycache__", parts)
            if parts[:2] == ("backend", "scripts"):
                self.assertEqual(len(parts), 3, name)  # top-level scripts only (.dockerignore)
                self.assertIsNone(verify.BACKEND_EXCLUDED_SCRIPTS.fullmatch(parts[2]), name)
            if parts[0] in {"deploy", "emulation"}:
                self.assertEqual(len(parts), 2, name)
        for host_only in ("deploy/verify.py", "deploy/manage.py", "deploy/gateway_config.py",
                          "backend/scripts/review_fullstack.py", "backend/scripts/verify_execution.py"):
            self.assertNotIn(host_only, sources)

    def test_fresh_secrets_match_the_volume_init_allowlist(self):
        from deploy import volume_init
        from app.modules.autonomy.health_secret import load_signing_key, load_verify_key

        with tempfile.TemporaryDirectory() as directory:
            secrets_dir = Path(directory) / "secrets"
            password = verify.initialize_secrets(secrets_dir)
            self.assertEqual({path.name for path in secrets_dir.iterdir()}, set(volume_init.SOURCE_SECRETS))
            self.assertEqual(password, (secrets_dir / "bootstrap_password").read_text())
            self.assertNotEqual((secrets_dir / "redis_password").read_bytes(),
                                (secrets_dir / "redis_admin_password").read_bytes())
            receiver = Path(directory) / verify.RECEIVER_DIRECTORY
            signer = load_signing_key(receiver / verify.RECEIVER_PRIVATE_KEY)
            self.assertEqual(signer.key_id, load_verify_key(secrets_dir / verify.RECEIVER_PUBLIC_KEY).key_id)
            for path in [*secrets_dir.iterdir(), *receiver.iterdir()]:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

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
        self.assertFalse(verify.ready_envelope(503, {"success": False}))
        self.assertFalse(verify.ready_envelope(200, None))
        with self.assertRaises(verify.VerificationError):
            verify.ready_envelope(200, {"success": True, "data": {"ready": True, "checks": {"redis": "down"}}})
        self.assertTrue(verify.ready_envelope(200, {"success": True, "data": {"ready": True, "checks": {"redis": "ok"}}}))

    def test_private_readiness_is_probed_inside_the_api_container(self):
        stack = Mock()
        body = json.dumps({"success": False, "data": {"checks": {"postgres": "unavailable"}}})
        stack.compose.return_value = json.dumps({"status": 503, "body": body}).encode()
        status, value = verify.api_readiness(stack, "api2")
        self.assertEqual((status, value["data"]["checks"]["postgres"]), (503, "unavailable"))
        args = stack.compose.call_args.args
        self.assertEqual(args[:5], ("exec", "-T", "api2", "python", "-c"))
        self.assertIn("http://127.0.0.1:8000/ready", args[5])
        stack.compose.side_effect = verify.VerificationError("Command failed")
        self.assertEqual(verify.api_readiness(stack), (0, None))

    def test_application_readiness_requires_the_gateway_to_hide_ready(self):
        stack, api = Mock(), Mock()
        envelope = {"success": True, "data": {"ready": True, "checks": {"postgres": "ok"}}}
        stack.config = {"services": {"api": {}}}
        stack.compose.return_value = json.dumps({"status": 200, "body": json.dumps(envelope)}).encode()
        responses = {"/health": (200, {}, b""), "/ready": (404, {}, b"")}
        api.raw.side_effect = lambda method, path, **kwargs: responses[path]
        self.assertTrue(verify.application_ready(stack, api))
        responses["/health"] = (0, {}, b"")
        self.assertFalse(verify.application_ready(stack, api))
        responses.update({"/health": (200, {}, b""), "/ready": (200, {}, b"{}")})
        with self.assertRaises(verify.VerificationError) as caught:
            verify.application_ready(stack, api)
        self.assertIn("publicly", str(caught.exception))

    def test_redis_acl_proof_runs_through_the_credential_entrypoint(self):
        stack = Mock()
        good = {"anonymous": "AuthenticationError", "default_user": "AuthenticationError",
                "whoami": "nanfo", "dangerous": "NoPermissionError"}
        stack.compose.return_value = json.dumps(good).encode()
        self.assertEqual(verify.redis_acl(stack), good)
        self.assertIn("/opt/nanfo/deploy/entrypoint.py", stack.compose.call_args.args)
        for field, value in (("anonymous", "ok"), ("default_user", "ok"), ("whoami", "default"),
                             ("dangerous", "allowed")):
            stack.compose.return_value = json.dumps({**good, field: value}).encode()
            with self.subTest(field=field), self.assertRaises(verify.VerificationError):
                verify.redis_acl(stack)

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
            gateway_response(body=b'<div id="root"></div><script src="/assets/main.js"></script>',
                             **{"Cache-Control": "no-cache"}),
            gateway_response(body=b"fallback" * 100),
        ]
        with self.assertRaises(verify.VerificationError) as caught:
            verify.frontend_smoke(api)
        self.assertIn("fallback HTML", str(caught.exception))

    def smoke_responses(self, **overrides):
        shell = b'<div id="root"></div><script src="/assets/main.js"></script>'
        responses = {
            "/": gateway_response(body=shell, **{"Cache-Control": "no-cache"}),
            "/assets/main.js": gateway_response(content_type="text/javascript", body=b"x" * 200,
                                                **{"Cache-Control": "public, max-age=31536000, immutable"}),
            "/health": gateway_response(content_type="application/json", body=b"{}"),
            "/ready": gateway_response(404),
            "/api/docs": gateway_response(404),
            "/api/openapi.json": gateway_response(404),
        }
        responses.update(overrides)

        def raw(method, path, **kwargs):
            if path.startswith("/assets/missing-"):
                return gateway_response(404)
            return responses[path]

        api = Mock()
        api.raw.side_effect = raw
        return api

    def test_gateway_security_headers_and_hidden_endpoints_are_verified(self):
        result = verify.frontend_smoke(self.smoke_responses())
        self.assertEqual(result["hidden_endpoints"], ["/ready", "/api/docs", "/api/openapi.json"])
        self.assertIn("review_fullstack.py", result["browser_execution"])
        self.assertIn("Content-Security-Policy", result["security_headers"])
        weakened = {**verify.GATEWAY_HEADERS, "Content-Security-Policy": "default-src *"}
        for overrides in (
            {"/assets/main.js": (200, {**weakened, "Content-Type": "text/javascript",
                                       "Permissions-Policy": PERMISSIONS, "Cache-Control": "immutable"}, b"x" * 200)},
            {"/health": (200, {"Content-Type": "application/json"}, b"{}")},
            {"/ready": gateway_response(200)},
            {"/api/docs": gateway_response(200)},
            {"/": gateway_response(body=b'<div id="root"></div><script src="/assets/main.js"></script>')},
        ):
            with self.subTest(overrides=list(overrides)), self.assertRaises(verify.VerificationError):
                verify.frontend_smoke(self.smoke_responses(**overrides))
        csp = (verify.ROOT / "deploy/nginx-security-headers.conf").read_text()
        self.assertIn(f'Content-Security-Policy "{verify.CONTENT_SECURITY_POLICY}" always;', csp)

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
