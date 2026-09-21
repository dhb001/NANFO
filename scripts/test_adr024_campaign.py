"""Preregistration, exact tensor lineage and strict qualification regression tests."""

import copy
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
