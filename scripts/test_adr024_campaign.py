"""Preregistration, exact tensor lineage and strict qualification regression tests."""

import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import adr024_campaign as campaign


def report_fixture():
    metric = dict(paired_seed_count=12, mean_delta=.03, ci95=[.001, .059])
    return dict(comparable_held_out_schedules=True, paired_seed_comparisons=[
        dict(baseline="constant0", metrics={"reward": copy.deepcopy(metric)}),
        dict(baseline="constant1", metrics={"reward": copy.deepcopy(metric)}),
        dict(baseline="ospf", metrics={"goodput_mbps": copy.deepcopy(metric),
                                    "icmp_rtt_ms": dict(paired_seed_count=12, mean_delta=-3, ci95=[-5, -1])})],
        sessions=[dict(policy="ppo", reconstructed_steps=[
            dict(scenario=scenario, action=desired) for scenario, desired in (("path0", 1), ("path1", 0))
            for _ in range(24)])])


class CampaignTests(unittest.TestCase):
    def test_reserved_seeds_include_nested_failed_actual_and_planned(self):
        value = dict(seed=3001, failed={"test_seeds": [3002, 3003]},
                     candidate={"manifest": {"training_seeds": [1600]}}, value=3100)
        self.assertEqual(campaign.seed_values(value), {3001, 3002, 3003, 1600})

    def test_exact_original_writer_rebinding_changes_only_image(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            target = Path(directory)
            identity = campaign.derive(target)
            lineage = campaign.read(target / "lineage.json")
            self.assertTrue(lineage["exact_tensor_bytes_equal"])
            self.assertEqual(lineage["changed_manifest_fields"], ["lab_provenance.lab_image_id"])
            self.assertEqual(identity["manifest"]["lab_provenance"]["lab_image_id"], campaign.IMAGE)
            self.assertEqual(lineage["tensor_payload_sha256"],
                             "3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967")
            self.assertFalse(lineage["qualified"])

    def test_thresholds_are_strict_not_equal(self):
        self.assertTrue(campaign.assess(report_fixture())["qualified"])
        for index, name, field, value in (
            (0, "reward", "mean_delta", .02),
            (1, "reward", "ci95", [0, .06]),
            (2, "goodput_mbps", "ci95", [0, 1]),
            (2, "icmp_rtt_ms", "ci95", [-5, 0]),
            (0, "reward", "paired_seed_count", 11),
        ):
            report = report_fixture()
            report["paired_seed_comparisons"][index]["metrics"][name][field] = value
            self.assertFalse(campaign.assess(report)["qualified"])

    def test_direction_requires_majority_in_both_and_all_windows(self):
        for count in (12, 13):
            report = report_fixture()
            for row in report["sessions"][0]["reconstructed_steps"][:count]:
                row["action"] = 0
            self.assertFalse(campaign.assess(report)["qualified"])
        report = report_fixture()
        report["sessions"][0]["reconstructed_steps"].pop()
        self.assertFalse(campaign.assess(report)["qualified"])

    def test_matched_schedules_required(self):
        report = report_fixture()
        report["comparable_held_out_schedules"] = False
        result = campaign.assess(report)
        self.assertFalse(result["qualified"])
        self.assertFalse(result["safety_calibrated"])
        self.assertFalse(result["autonomous_activation"])


class FrozenClientImportTests(unittest.TestCase):
    """The ADR014 client is hashed against the pinned parent manifest before execution."""

    def test_tampered_client_is_refused_before_any_module_executes(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source, marker = root / "train/source", root / "executed"
            source.mkdir(parents=True)
            names = ("__init__", "artifacts", "cli", "contracts", "env", "qualification", "transport")
            for name in names:
                body = f"open({str(marker)!r}, 'w').close()\n" if name == "__init__" else ""
                (source / (name + ".py")).write_text(body)
            pins = {path.name: campaign.digest(path) for path in source.glob("*.py")}
            bundle = io.BytesIO()
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("manifest.json", json.dumps({"client_source_files": pins}))
            checkpoint = root / "checkpoint.ptz"
            checkpoint.write_bytes(bundle.getvalue())
            (source / "env.py").write_text("raise SystemExit('tampered code executed')\n")
            patches = (mock.patch.object(campaign.recovery, "TRAIN", root / "train"),
                       mock.patch.object(campaign.recovery, "CHECKPOINT", checkpoint),
                       mock.patch.object(campaign.recovery, "CHECKPOINT_HASH", campaign.digest(checkpoint)))
            cached = {n: sys.modules.pop(n) for n in list(sys.modules) if n.startswith("_adr024_frozen")}
            try:
                with patches[0], patches[1], patches[2]:
                    with self.assertRaisesRegex(ValueError, "frozen client source changed"):
                        campaign.frozen()
                    self.assertFalse(marker.exists())
                    (source / "env.py").write_text("")
                    self.assertEqual(sorted(campaign.frozen()), sorted(names[1:]))
                    self.assertTrue(marker.exists())
            finally:
                for name in [n for n in sys.modules if n.startswith("_adr024_frozen")]:
                    sys.modules.pop(name)
                sys.modules.update(cached)


class FrozenLabLaunchTests(unittest.TestCase):
    """ADR-028 C23: the privileged frozen v4 lab starts only by explicit NANFO_LAB_FROZEN=1."""

    plan = dict(campaign_id="a" * 32, image_id=campaign.IMAGE)

    def launch(self, environ, plan=None):
        calls = []

        def command(output, label, argv, timeout=30, check=True):
            calls.append(argv)
            if label.endswith("-create"):
                (output / "ppo.cid").write_text("c" * 64)
                return mock.Mock(stdout=b"c" * 64)
            if label.endswith("-inspect"):
                details = dict(Image=campaign.IMAGE, Mounts=[], HostConfig=dict(NetworkMode="none"))
                return mock.Mock(stdout=json.dumps([details]).encode())
            return mock.Mock(stdout=b"")

        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory, \
                mock.patch.object(campaign, "command", command), \
                mock.patch.dict(os.environ, environ, clear=True):
            output = Path(directory)
            try:
                campaign.start_lab(output, plan or self.plan, "ppo")
            finally:
                written = sorted(path.name for path in output.iterdir())
        return calls, written

    def test_refused_without_explicit_opt_in_before_any_write_or_docker_call(self):
        for environ, reason in (({}, "NANFO_LAB_FROZEN=1"), ({"NANFO_LAB_FROZEN": "0"}, "NANFO_LAB_FROZEN=1"),
                                ({"NANFO_LAB_FROZEN": "yes"}, "must be 1")):
            calls = []
            with self.subTest(environ=environ), mock.patch.object(campaign, "command", lambda *a, **k: calls.append(a)), \
                    tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory, \
                    mock.patch.dict(os.environ, environ, clear=True):
                with self.assertRaisesRegex(ValueError, reason):
                    campaign.start_lab(Path(directory), self.plan, "ppo")
                self.assertEqual((calls, list(Path(directory).iterdir())), ([], []))

    def test_opted_in_launch_is_the_recorded_privileged_isolated_image(self):
        calls, written = self.launch({"NANFO_LAB_FROZEN": "1"})
        create = calls[0]
        self.assertEqual(create[:2], ["docker", "create"])
        self.assertIn("--privileged", create)
        self.assertEqual(create[create.index("--network") + 1], "none")
        self.assertEqual(create[create.index("--experiment") - 1], campaign.IMAGE)
        self.assertEqual(written, ["ppo-owner.json", "ppo.cid"])
        with self.assertRaisesRegex(ValueError, "recorded frozen lab image"):
            self.launch({"NANFO_LAB_FROZEN": "1"}, dict(self.plan, image_id="sha256:" + "b" * 64))


if __name__ == "__main__":
    unittest.main()
