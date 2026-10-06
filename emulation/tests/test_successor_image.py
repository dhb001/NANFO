"""ADR-028 C23 successor image/compose/launcher contract (static; no Docker)."""

import hashlib
import os
import re
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emulation import control
from emulation.controller_main import APPS, ARGUMENTS, main
from emulation.ospf import FRR_PRIVILEGES
from emulation.runner import CAPABILITIES, capabilityStatus, requireSuccessorProfile

EMULATION = Path(__file__).resolve().parents[1]
FROZEN_TARBALL = EMULATION / "frozen/adr015-prechange-v4-source.tar.gz"
FROZEN_SHA256 = {
    "Dockerfile.frozen": "ccb51b29779e436726ebc5246476954f03524884f3d3981dc9740d0c204f838e",
    "requirements.frozen.txt": "a5c31f09953e22b84658e44f0b9cef0e860df3be11881cba06451066be058016",
    "apt-sources.list": "1b39437ed24df2a63b6739f4e5d2510e31b139e79eb3f71dfa65655e4215113e",
}
MINIMUM = {"eventlet": (0, 40), "dnspython": (2, 6), "webob": (1, 8, 8), "msgpack": (1, 1),
           "requests": (2, 32, 4), "idna": (3, 10), "urllib3": (2, 5), "os-ken": (4, 2)}


def requirements(name):
    text = (EMULATION / name).read_text()
    pins = {}
    for block in re.split(r"\n(?=[a-z0-9])", text.strip()):
        if block.startswith("#"):
            continue
        head = block.split()[0]
        package, version = head.split("==")
        pins[package] = (version, re.findall(r"--hash=sha256:([0-9a-f]{64})", block))
    return text, pins


def status(*names, no_new_privs=True):
    mask = sum(1 << CAPABILITIES[name] for name in names)
    return f"Name:\tpython\nCapEff:\t{mask:016x}\nCapBnd:\t{mask:016x}\nNoNewPrivs:\t{int(no_new_privs)}\n"


class FrozenRecipeTests(unittest.TestCase):
    def test_frozen_recipe_is_byte_identical_to_the_recorded_eol_files(self):
        for name, expected in FROZEN_SHA256.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((EMULATION / name).read_bytes()).hexdigest(), expected)

    @unittest.skipUnless(FROZEN_TARBALL.is_file(), "frozen v4 source archive not present")
    def test_frozen_recipe_equals_the_preserved_v4_archive_members(self):
        with tarfile.open(FROZEN_TARBALL) as archive:
            for copy, member in (("Dockerfile.frozen", "Dockerfile"),
                                 ("requirements.frozen.txt", "requirements.txt"),
                                 ("apt-sources.list", "apt-sources.list")):
                with self.subTest(copy=copy):
                    original = archive.extractfile("emulation/" + member).read()
                    self.assertEqual((EMULATION / copy).read_bytes(), original)


class SuccessorDockerfileTests(unittest.TestCase):
    def setUp(self):
        self.text = (EMULATION / "Dockerfile").read_text()

    def test_supported_digest_pinned_base_and_no_eol_sources(self):
        base = re.search(r"^FROM (\S+)$", self.text, re.M).group(1)
        self.assertRegex(base, r"^python:3\.12\.\d+-slim-(bookworm|trixie)@sha256:[0-9a-f]{64}$")
        self.assertNotIn("bullseye", self.text)
        self.assertNotIn("apt-sources.list", self.text)
        for pin in ("mininet=", "openvswitch-switch=", "frr="):
            self.assertIn(pin, self.text)

    def test_every_apt_package_is_version_pinned_from_one_dated_snapshot(self):
        logical = self.text.replace("\\\n", " ")
        copy = logical.index("COPY debian-snapshot.sources /etc/apt/sources.list.d/debian.sources")
        self.assertLess(copy, logical.index("apt-get update"))
        installs = re.findall(r"apt-get install ([^&]*)", logical)
        self.assertEqual(len(installs), 1)
        packages = [token for token in installs[0].split() if not token.startswith("-")]
        self.assertGreaterEqual(len(packages), 10)
        for token in packages:
            with self.subTest(package=token):  # hadolint DL3008
                self.assertRegex(token, r"^[a-z0-9][a-z0-9.+-]*=[0-9A-Za-z.+:~-]+$")
        pins = dict(token.split("=", 1) for token in packages)
        self.assertEqual(pins["frr"], "10.3-3+deb13u1")
        self.assertEqual(pins["openvswitch-switch"], "3.5.0-1+b1")
        self.assertEqual(pins["mininet"], "2.3.0-1.1")
        self.assertEqual(set(pins) - {"mininet", "openvswitch-switch", "frr"},
                         {"iproute2", "iputils-ping", "iperf3", "tcpdump", "procps", "tini", "ca-certificates"})

    def test_snapshot_sources_are_signed_https_and_share_one_timestamp(self):
        text = (EMULATION / "debian-snapshot.sources").read_text()
        stanzas = [dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith("#"))
                   for block in text.strip().split("\n\n")]
        stamps, suites = set(), set()
        for stanza in stanzas:
            match = re.fullmatch(r"https://snapshot\.debian\.org/archive/(debian|debian-security)/"
                                 r"(\d{8}T\d{6}Z)/", stanza["URIs"])
            self.assertIsNotNone(match, stanza["URIs"])
            stamps.add(match.group(2))
            suites |= set(stanza["Suites"].split())
            self.assertEqual(stanza["Types"], "deb")
            self.assertEqual(stanza["Components"], "main")
            self.assertEqual(stanza["Signed-By"], "/usr/share/keyrings/debian-archive-keyring.gpg")
            self.assertEqual(stanza["Check-Valid-Until"], "no")
            self.assertNotIn("Trusted", stanza)
        self.assertEqual(len(stamps), 1)
        self.assertEqual(suites, {"trixie", "trixie-updates", "trixie-security"})
        from emulation.experiment import SOURCE_FILES

        self.assertIn("debian-snapshot.sources", SOURCE_FILES)

    def test_hash_pinned_install_without_unpinned_build_dependencies(self):
        logical = self.text.replace("\\\n", " ")
        installs = [part for part in re.split(r"&&|\n", logical) if "pip install" in part]
        self.assertEqual(len(installs), 2)
        for command in installs:
            self.assertIn("--require-hashes", command)
            self.assertIn("--no-deps", command)
        self.assertIn("--no-build-isolation", installs[1])
        self.assertRegex(installs[1], r"--only-binary=:all:\s+--no-binary=ovs")
        self.assertIn("pip check", self.text)

    def test_successor_identity_and_no_privilege_in_the_image(self):
        self.assertIn("NANFO_LAB_PROFILE=successor", self.text)
        self.assertIn('org.nanfo.lab.frozen="false"', self.text)
        self.assertNotIn("privileged", self.text.lower().replace("no privileged mode", ""))
        self.assertIn("usermod -a -G frrvty root", self.text)
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "emulation.runner"]', self.text)

    def test_build_time_test_modules_exist(self):
        modules = re.findall(r"emulation\.tests\.(test_\w+)", self.text)
        self.assertIn("test_successor_image", modules)
        for module in modules:
            self.assertTrue((EMULATION / "tests" / (module + ".py")).is_file(), module)


class RequirementsTests(unittest.TestCase):
    def test_every_requirement_is_exact_and_hash_pinned(self):
        for name in ("requirements.txt", "requirements-build.txt"):
            text, pins = requirements(name)
            self.assertNotIn("ryu", pins)
            for package, (version, hashes) in pins.items():
                with self.subTest(file=name, package=package):
                    self.assertRegex(version, r"^[0-9][0-9A-Za-z.]*$")
                    self.assertTrue(hashes)
            lines = [line for line in text.splitlines() if line and not line.lstrip().startswith(("#", "--hash"))]
            self.assertTrue(all(re.fullmatch(r"[a-z0-9-]+==\S+ \\", line) for line in lines), lines)

    def test_maintained_controller_and_current_security_relevant_versions(self):
        _, pins = requirements("requirements.txt")
        for package, minimum in MINIMUM.items():
            with self.subTest(package=package):
                version = tuple(int(part) for part in pins[package][0].split(".")[: len(minimum)])
                self.assertGreaterEqual(version, minimum)

    def test_build_backend_pin_matches_the_runtime_closure(self):
        _, runtime = requirements("requirements.txt")
        _, build = requirements("requirements-build.txt")
        self.assertEqual(set(build), {"setuptools"})
        self.assertEqual(build["setuptools"][0], runtime["setuptools"][0])
        self.assertEqual(set(build["setuptools"][1]), set(runtime["setuptools"][1]))


class ComposeTests(unittest.TestCase):
    def test_default_dev_compose_is_the_c23_successor_profile(self):
        text = (EMULATION / "compose.yaml").read_text()
        self.assertIn("cap_drop: [ALL]", text)
        self.assertIn("cap_add: [NET_ADMIN, NET_RAW, SYS_ADMIN]", text)
        self.assertIn("security_opt: [no-new-privileges:true]", text)
        self.assertIn("read_only: true", text)
        self.assertIn("network_mode: none", text)
        self.assertNotIn("privileged: true", text)
        tmpfs = re.findall(r"^      - (/\S+):(\S+)$", text, re.M)
        self.assertTrue(tmpfs)
        for target, options in tmpfs:
            with self.subTest(target=target):
                self.assertIn("nosuid", options.split(","))
                self.assertIn("nodev", options.split(","))

    def test_frozen_privileged_compose_requires_the_explicit_acknowledgement(self):
        text = (EMULATION / "compose.frozen.yaml").read_text()
        self.assertIn("privileged: true", text)
        self.assertIn("${NANFO_LAB_FROZEN:?", text)
        self.assertIn("${NANFO_EMULATION_IMAGE:?", text)
        self.assertNotIn("build:", text)
        self.assertNotIn("NANFO_LAB_COMMAND_KEY_FILE", text)

    def test_control_overlay_mounts_only_the_c15_key_directory_read_only(self):
        text = (EMULATION / "compose.control.yaml").read_text()
        self.assertIn("target: /run/nanfo-lab-key", text)
        self.assertIn("read_only: true", text)
        self.assertIn("${NANFO_LAB_COMMAND_KEY_DIR:?", text)


class ControlLauncherTests(unittest.TestCase):
    def test_privileged_frozen_compose_only_with_explicit_frozen_flag_and_image_id(self):
        root = EMULATION
        self.assertEqual(control.composeFiles(root, {}), [root / "compose.yaml"])
        self.assertEqual(control.composeFiles(root, {"EMULATION_CONTROL_ENABLED": "true"}),
                         [root / "compose.yaml", root / "compose.control.yaml"])
        with self.assertRaisesRegex(ValueError, "recorded id"):
            control.composeFiles(root, {"NANFO_LAB_FROZEN": "1"})
        with self.assertRaisesRegex(ValueError, "recorded id"):
            control.composeFiles(root, {"NANFO_LAB_FROZEN": "1", "NANFO_EMULATION_IMAGE": "latest"})
        with self.assertRaisesRegex(ValueError, "must be 1"):
            control.composeFiles(root, {"NANFO_LAB_FROZEN": "yes"})
        image = "sha256:" + "9" * 64
        self.assertEqual(control.composeFiles(root, {"NANFO_LAB_FROZEN": "1", "NANFO_EMULATION_IMAGE": image}),
                         [root / "compose.frozen.yaml"])

    def test_source_digest_tracks_image_sources_and_ignores_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "runner.py").write_text("a")
            (root / "output").mkdir()
            (root / "output" / "snapshot.json").write_text("{}")
            first = control.sourceDigest(root)
            (root / "output" / "snapshot.json").write_text('{"changed": true}')
            (root / "frozen").mkdir()
            (root / "frozen" / "x.tar.gz").write_bytes(b"x")
            self.assertEqual(control.sourceDigest(root), first)
            (root / "runner.py").write_text("b")
            self.assertNotEqual(control.sourceDigest(root), first)

    def test_successor_preflight_requires_lab_owned_output_and_writer_commands(self):
        # Ownership is simulated so the result never depends on the uid running the test.
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for directory in ("output", "results", "commands"):
                (root / directory).mkdir(mode=0o750)
            real = os.lstat

            def layout(**owners):
                def lstat(path):
                    info = real(path)
                    uid, gid, mode = owners.get(Path(path).name, (info.st_uid, info.st_gid, 0o40750))
                    return os.stat_result((mode, *info[1:4], uid, gid, *info[6:]))
                return lambda self: lstat(self)

            good = dict(output=(0, 1000, 0o40750), results=(0, 1000, 0o40750), commands=(1000, 1000, 0o40750))
            with patch.object(Path, "lstat", layout(**good)):
                self.assertEqual(control.successorPreflight(root, {}), "1000")
                with self.assertRaisesRegex(ValueError, "numeric"):
                    control.successorPreflight(root, {"NANFO_LAB_READER_GID": "users"})
            cases = {
                "output_not_root": {**good, "output": (1000, 1000, 0o40750)},
                "results_group_writable": {**good, "results": (0, 1000, 0o40770)},
                "output_other_group": {**good, "output": (0, 5, 0o40750)},
            }
            for case, owners in cases.items():
                with self.subTest(case=case), patch.object(Path, "lstat", layout(**owners)), \
                        self.assertRaisesRegex(ValueError, "must be root:"):
                    control.successorPreflight(root, {})
            with patch.object(Path, "lstat", layout(**{**good, "commands": (0, 1000, 0o40750)})), \
                    self.assertRaisesRegex(ValueError, "not root"):
                control.successorPreflight(root, {})
            with patch.object(Path, "lstat", layout(**{**good, "commands": (1000, 1000, 0o40770)})), \
                    self.assertRaisesRegex(ValueError, "writer group"):
                control.successorPreflight(root, {})


class RunnerProfileTests(unittest.TestCase):
    def test_exact_successor_profile_is_accepted(self):
        profile = requireSuccessorProfile(status=status("CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_SYS_ADMIN"))
        self.assertTrue(profile["no_new_privs"])

    def test_privileged_extra_missing_or_new_privilege_profiles_are_refused(self):
        privileged = "CapEff:\t000001ffffffffff\nCapBnd:\t000001ffffffffff\nNoNewPrivs:\t0\n"
        cases = {
            "privileged": privileged,
            "extra_bind_in_default_mode": status("CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_SYS_ADMIN",
                                                 "CAP_NET_BIND_SERVICE"),
            "missing_sys_admin": status("CAP_NET_ADMIN", "CAP_NET_RAW"),
            "new_privileges_allowed": status("CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_SYS_ADMIN",
                                             no_new_privs=False),
        }
        for case, text in cases.items():
            with self.subTest(case=case), self.assertRaisesRegex(RuntimeError, "C23"):
                requireSuccessorProfile(status=text)
        with self.assertRaisesRegex(RuntimeError, "Capability status"):
            capabilityStatus("Name:\tpython\n")

    def test_frr_modes_add_only_net_bind_service(self):
        frr = status("CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_SYS_ADMIN", "CAP_NET_BIND_SERVICE")
        requireSuccessorProfile(frr=True, status=frr)
        with self.assertRaisesRegex(RuntimeError, "NET_BIND_SERVICE"):
            requireSuccessorProfile(frr=True, status=status("CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_SYS_ADMIN"))
        self.assertEqual(FRR_PRIVILEGES, ("-u", "root", "-g", "root"))

    def test_frozen_flag_is_never_honoured_by_the_successor(self):
        with patch.dict(os.environ, {"NANFO_LAB_FROZEN": "1"}), self.assertRaisesRegex(RuntimeError, "frozen"):
            requireSuccessorProfile(status=status("CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_SYS_ADMIN"))


class ControllerLauncherTests(unittest.TestCase):
    def test_fixed_launcher_matches_the_frozen_manager_argv_and_accepts_no_arguments(self):
        self.assertEqual(ARGUMENTS, ("--observe-links", "--ofp-listen-host", "127.0.0.1",
                                     "--ofp-tcp-listen-port", "6653", "--log-config-file",
                                     "/opt/nanfo/emulation/logging.conf"))
        self.assertEqual(APPS, ("emulation.controller",))
        with patch("sys.stderr"):
            self.assertEqual(main(["--ofp-listen-host", "0.0.0.0"]), 2)

    def test_producer_lock_is_private(self):
        runner = (EMULATION / "runner.py").read_text()
        self.assertIn('".producer.lock"), os.O_CREAT | os.O_RDWR, 0o600', runner)


if __name__ == "__main__":
    unittest.main()


class ProvenanceTests(unittest.TestCase):
    def test_provenance_comes_from_docker_inspect_and_must_match_the_pin(self):
        from types import SimpleNamespace

        image = "sha256:" + "a" * 64
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(stdout=f'"{"c" * 64}" "{image}"\n')

        self.assertEqual(control.containerProvenance("nanfo-experiment", image, run=run),
                         {"container_id": "c" * 64, "image_id": image})
        self.assertEqual(calls[0][:3], ["docker", "inspect", "--format"])
        with self.assertRaisesRegex(ValueError, "differs from the pinned image"):
            control.containerProvenance("nanfo-experiment", "sha256:" + "b" * 64, run=run)
        for output in ('"short" "latest"', "", '"' + "c" * 64 + '" "nanfo:tag"'):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "identity"):
                control.containerProvenance("x", run=lambda argv, output=output, **kw: SimpleNamespace(stdout=output))
