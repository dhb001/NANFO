"""Independent raw-metric verifier rejects a tampered reported confidence interval."""

import copy
import os
from pathlib import Path
import unittest

import adr024_campaign as campaign
import verify_adr024_campaign as verifier

# Preserved copy of the completed ADR024 campaign in the ignored private evidence store; the
# original acquisition directory /tmp/opencode/nanfo-adr024-evaluation-002 no longer exists.
PRESERVED = Path(os.environ.get("NANFO_ADR024_EVALUATION_ROOT")
                 or Path(__file__).resolve().parents[1] / "ai-engine/artifacts/adr024-qualified-001/model")


class IndependentVerifierTests(unittest.TestCase):
    def test_completed_raw_reconstruction_and_tampered_report_rejection(self):
        root = PRESERVED
        if not (root / "test-report.json").exists():
            self.skipTest("private preserved ADR024 campaign absent (explicit portable-lane boundary)")
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
