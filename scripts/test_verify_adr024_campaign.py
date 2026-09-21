"""Independent raw-metric verifier rejects a tampered reported confidence interval."""

import copy
from pathlib import Path
import unittest

import adr024_campaign as campaign
import verify_adr024_campaign as verifier


class IndependentVerifierTests(unittest.TestCase):
    def test_completed_raw_reconstruction_and_tampered_report_rejection(self):
        root = Path("/tmp/opencode/nanfo-adr024-evaluation-002")
        if not (root / "test-report.json").exists():
            self.skipTest("actual campaign evidence not installed")
        plan = campaign.read(root / "plan.json")
        report = campaign.read(root / "test-report.json")
        metrics = verifier.independent_metrics(root, plan, report)
        self.assertGreater(metrics["constant0"]["reward"]["ci95"][0], 0)
        self.assertLess(metrics["ospf"]["icmp_rtt_ms"]["ci95"][1], 0)
        tampered = copy.deepcopy(report)
        tampered["paired_seed_comparisons"][0]["metrics"]["reward"]["ci95"][0] += .001
        with self.assertRaisesRegex(ValueError, "independent CI mismatch"):
            verifier.independent_metrics(root, plan, tampered)


if __name__ == "__main__":
    unittest.main()
