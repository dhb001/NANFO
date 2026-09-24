"""Security policy regressions: exact IDs, expiry, skipped feeds and duplicate counts."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_dependencies import POLICY, evaluate, inventory, main, unique_json_object


def vulnerability(identity="CVE-2026-12345"):
    return dict(id=identity, aliases=[], fix_versions=[], description="Reviewed test advisory")


class AuditPolicyTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 21)
        self.report = {"dependencies": [{"name": "example", "version": "1.0",
                                        "vulns": [vulnerability(), vulnerability()]}], "fixes": []}
        self.exception = dict(lane="backend", package="example", version="1.0",
                              advisories=["CVE-2026-12345"], expires="2026-10-21", owner="reviewer",
                              rationale="Reviewed bounded exposure", remediation="Replace library")
        self.policy = {"schema_version": 1, "exceptions": [self.exception], "coverage_gaps": []}

    def check(self, report=None, policy=None):
        return evaluate("backend", report or self.report, policy or self.policy, self.today)

    def test_duplicate_feed_rows_are_one_pair(self):
        result = self.check()
        self.assertEqual(result["raw_advisory_rows"], 2)
        self.assertEqual(result["distinct_package_advisory_pairs"], 1)
        self.assertEqual(result["accepted_pairs"], 1)
        self.assertEqual(result["errors"], [])

    def test_new_advisory_on_excepted_package_fails(self):
        self.report["dependencies"][0]["vulns"].append(vulnerability("CVE-2026-54321"))
        self.assertIn("CVE-2026-54321", " ".join(self.check()["errors"]))

    def test_exception_does_not_cover_other_version_or_lane(self):
        for key, value in (("version", "2.0"), ("lane", "ai")):
            policy = deepcopy(self.policy)
            policy["exceptions"][0][key] = value
            self.assertTrue(self.check(policy=policy)["errors"])

    def test_expiry_day_fails_closed(self):
        self.exception["expires"] = self.today.isoformat()
        self.assertTrue(self.check()["errors"])

    def test_missing_rationale_fails(self):
        self.exception["rationale"] = ""
        with self.assertRaisesRegex(ValueError, "Incomplete exception metadata"):
            self.check()

    def test_skip_is_not_a_clean_audit(self):
        self.report["dependencies"].append(dict(name="torch", version="2.8.0+cpu",
                                                skip_reason="not on PyPI"))
        self.assertTrue(self.check()["errors"])
        self.policy["coverage_gaps"] = [dict(lane="backend", package="torch",
                                            version="2.8.0+cpu", reason="not on PyPI",
                                            expires="2026-10-21", owner="reviewer",
                                            rationale="Exact build unavailable", remediation="SBOM review")]
        result = self.check()
        self.assertFalse(result["errors"])
        self.assertEqual(len(result["coverage_gaps"]), 1)
        self.report["dependencies"][-1]["skip_reason"] = "network unavailable"
        self.assertTrue(self.check()["errors"])

    def test_lock_inventory_retains_cpu_build_and_all_dev_pins(self):
        ai = inventory("ai")
        self.assertEqual(ai["torch"], "2.8.0+cpu")
        self.assertIn("pytest", ai)
        self.assertIn("pypdf", inventory("backend"))
        self.assertEqual(inventory("emulation")["eventlet"], "0.30.2")

    def test_tool_failure_cannot_reuse_stale_clean_report(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "backend-raw.json"
            destination.write_text(json.dumps({"dependencies": []}))
            with patch("sys.argv", ["audit", "backend", "--output", directory]), \
                    patch("audit_dependencies.subprocess.run") as run:
                run.return_value.returncode = 2
                with self.assertRaisesRegex(SystemExit, "tool/feed failure"):
                    main()
            self.assertFalse(destination.exists())

    def test_empty_inventory_response_fails_instead_of_reporting_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            def incomplete(*args, **kwargs):
                (Path(directory) / "backend-raw.json").write_text(
                    json.dumps({"dependencies": [], "fixes": []}))
                return type("Result", (), {"returncode": 0})()

            with patch("sys.argv", ["audit", "backend", "--output", directory]), \
                    patch("audit_dependencies.subprocess.run", side_effect=incomplete):
                with self.assertRaisesRegex(SystemExit, "inventory incomplete"):
                    main()

    def invoke_report(self, report, *, code=0):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "backend-summary.json"
            summary.write_text('{"errors": []}')

            def auditor(*args, **kwargs):
                (Path(directory) / "backend-raw.json").write_text(json.dumps(report))
                return type("Result", (), {"returncode": code})()

            with patch("sys.argv", ["audit", "backend", "--output", directory]), \
                    patch("audit_dependencies.inventory", return_value={"example": "1.0"}), \
                    patch("audit_dependencies.subprocess.run", side_effect=auditor):
                with self.assertRaises(SystemExit) as exit_result:
                    main()
            self.assertNotEqual(exit_result.exception.code, 0)
            self.assertFalse(summary.exists(), "Malformed audit retained a clean summary")

    def test_main_exact_inventory_missing_vulns_return_zero_fails(self):
        self.invoke_report({"dependencies": [{"name": "example", "version": "1.0"}], "fixes": []})

    def test_main_rejects_malformed_exact_inventory_records(self):
        valid = {"name": "example", "version": "1.0", "vulns": []}
        for field, values in {
            "vulns": [None, {}, "", False, 0, [None], [{}], [{"id": "CVE-2026-12345"}]],
            "name": [None, 42, "", " bad", "../example"],
            "version": [None, 1.0, "", "not-a-version", " 1.0"],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.invoke_report({"dependencies": [{**valid, field: value}], "fixes": []})

    def test_main_rejects_malformed_report_structure_and_duplicate_dependencies(self):
        valid = {"name": "example", "version": "1.0", "vulns": []}
        for report in (None, [], {}, {"dependencies": []},
                       {"dependencies": {}, "fixes": []},
                       {"dependencies": [valid], "fixes": None},
                       {"dependencies": [valid], "fixes": [{}]},
                       {"dependencies": [valid], "fixes": [], "version": 2},
                       {"dependencies": [valid, valid], "fixes": []}):
            with self.subTest(report=report):
                self.invoke_report(report)

    def test_main_rejects_invalid_advisory_types_ids_and_versions(self):
        for field, values in {
            "id": [None, 1, "", "*", "CVE-NEW", "GHSA-xxxx-xxxx-xxxx "],
            "aliases": [None, "CVE-2026-12345", [None], ["*"]],
            "fix_versions": [None, "1.0", [1], ["invalid"]],
            "description": [None, [], ""],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.invoke_report({"dependencies": [{"name": "example", "version": "1.0",
                        "vulns": [{**vulnerability(), field: value}]}], "fixes": []})

    def test_main_rejects_ambiguous_empty_or_unreviewed_skips(self):
        for package in (
            dict(name="example", version="1.0", skip_reason="", vulns=[]),
            dict(name="example", version="1.0", skip_reason="not on PyPI", vulns=[]),
            dict(name="example", version="1.0", skip_reason=None),
            dict(name="example", version="1.0", skip_reason="not reviewed"),
        ):
            with self.subTest(package=package):
                # A structurally valid unknown skip creates a failing summary.
                if package.get("skip_reason") == "not reviewed":
                    self.assertTrue(evaluate("backend", {"dependencies": [package], "fixes": []},
                                             self.policy, self.today)["errors"])
                else:
                    self.invoke_report({"dependencies": [package], "fixes": []})

    def test_policy_schema_version_types_and_ids_fail_closed(self):
        for version in (True, "1", 2, None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.check(policy={**self.policy, "schema_version": version})
        self.exception["advisories"] = "CVE-2026-12345"
        with self.assertRaises(ValueError):
            self.check()

    def test_duplicate_json_keys_cannot_replace_advisories_with_clean_list(self):
        payload = '{"dependencies":[{"name":"example","version":"1.0","vulns":[{}],"vulns":[]}],"fixes":[]}'
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            json.loads(payload, object_pairs_hook=unique_json_object)

    def test_stale_exception_for_removed_package_fails_closed(self):
        # A dead exception would silently re-accept advisories if the pin ever returned.
        self.policy["exceptions"].append(dict(self.exception, package="ecdsa", version="0.19.2",
                                              advisories=["PYSEC-2026-1325"]))
        errors = self.check()["errors"]
        self.assertIn("Stale exception: ecdsa==0.19.2 is not in the backend inventory", errors)
        # The live, matching exception is still honoured.
        self.assertEqual(self.check()["accepted_pairs"], 1)

    def test_stale_coverage_gap_fails_closed(self):
        self.policy["coverage_gaps"] = [dict(lane="backend", package="torch", version="2.8.0+cpu",
                                             reason="not on PyPI", expires="2026-10-21", owner="reviewer",
                                             rationale="Exact build unavailable", remediation="SBOM review")]
        self.assertIn("Stale coverage gap: torch==2.8.0+cpu is not in the backend inventory",
                      self.check()["errors"])

    def test_repository_policy_matches_current_lock_inventories(self):
        """Every reviewed entry names an exact pin that is still locked (no dead policy)."""
        policy = json.loads(POLICY.read_text(), object_pairs_hook=unique_json_object)
        inventories = {lane: inventory(lane) for lane in ("backend", "ai", "ai-upstream", "emulation")}
        for kind in ("exceptions", "coverage_gaps"):
            for entry in policy[kind]:
                with self.subTest(kind=kind, package=entry["package"]):
                    self.assertEqual(inventories[entry["lane"]].get(entry["package"]), entry["version"])

    def test_python_jose_and_ecdsa_are_gone_with_their_exception(self):
        """ADR-028 C10: PyJWT replaced python-jose, so the ecdsa exception must not survive."""
        backend = inventory("backend")
        for package in ("python-jose", "ecdsa"):
            self.assertNotIn(package, backend)
        self.assertIn("pyjwt", backend)
        policy = json.loads(POLICY.read_text())
        self.assertFalse([e for e in policy["exceptions"] if e["package"] in ("ecdsa", "python-jose")])


if __name__ == "__main__":
    unittest.main()
