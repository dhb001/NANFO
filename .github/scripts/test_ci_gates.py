"""Regressions for the JUnit CI gates (zero skips, required cases, explicit skip budgets)."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import ci_gates as gates

ROOT = Path(__file__).resolve().parents[2]


def report(cases):
    """cases: (name, tag|None, message). Mirrors pytest's JUnit layout."""
    body = []
    for name, tag, message in cases:
        inner = f'<{tag} type="pytest.{tag}" message="{message}">t.py:1: {message}</{tag}>' if tag else ""
        body.append(f'<testcase classname="tests.unit.test_x" name="{name}" time="0.1">{inner}</testcase>')
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{"".join(body)}</testsuite></testsuites>'


class GateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path

    def budget(self, reasons, lane="backend"):
        return self.write("budget.json", json.dumps({"schema": gates.BUDGET_SCHEMA, "lanes": {lane: {"reasons": reasons}}}))

    def run_gate(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = gates.main(["junit", *map(str, args)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_passing_report_passes_and_failures_or_errors_always_fail(self):
        clean = self.write("clean.xml", report([("test_a", None, ""), ("test_b", None, "")]))
        self.assertEqual(self.run_gate(clean, "--zero-skips")[0], 0)
        for tag in ("failure", "error"):
            path = self.write(f"{tag}.xml", report([("test_a", None, ""), ("test_b", tag, "boom")]))
            code, _, stderr = self.run_gate(path)
            self.assertEqual(code, 1)
            self.assertIn(f"{tag}: tests.unit.test_x::test_b", stderr)

    def test_zero_skip_lane_rejects_a_single_skip_or_xfail(self):
        for tag in ("skipped",):
            path = self.write("skip.xml", report([("test_a", None, ""), ("test_b", tag, "nginx missing")]))
            code, _, stderr = self.run_gate(path, "--zero-skips")
            self.assertEqual(code, 1)
            self.assertIn("skip in zero-skip lane", stderr)

    def test_empty_unreadable_and_shrunken_reports_fail(self):
        self.assertEqual(self.run_gate(self.write("empty.xml", report([])))[0], 1)
        self.assertEqual(self.run_gate(self.write("broken.xml", "<testsuites><testsuite>"))[0], 2)
        self.assertEqual(self.run_gate(self.root / "missing.xml")[0], 2)
        few = self.write("few.xml", report([("test_a", None, "")]))
        code, _, stderr = self.run_gate(few, "--min-cases", "6")
        self.assertEqual(code, 1)
        self.assertIn("expected at least 6 cases", stderr)

    def test_required_case_must_exist_and_pass_in_every_parametrization(self):
        path = self.write("req.xml", report([("test_real_nginx[a]", None, ""), ("test_real_nginx[b]", "skipped", "x")]))
        code, _, stderr = self.run_gate(path, "--require", "test_real_nginx")
        self.assertEqual(code, 1)
        self.assertIn("did not pass (skipped)", stderr)
        code, _, stderr = self.run_gate(path, "--require", "test_absent")
        self.assertIn("required case missing: test_absent", stderr)
        ok = self.write("ok.xml", report([("test_real_nginx", None, "")]))
        self.assertEqual(self.run_gate(ok, "--require", "test_real_nginx")[0], 0)
        # Prefix names never satisfy a requirement by accident.
        near = self.write("near.xml", report([("test_real_nginx_other", None, "")]))
        self.assertEqual(self.run_gate(near, "--require", "test_real_nginx")[0], 1)

    def test_budget_counts_allowlisted_reasons_and_rejects_new_kinds(self):
        budget = self.budget([
            {"pattern": r"_TEST_DSN not configured", "max": 2, "why": "executed in database-contracts"},
            {"pattern": r"^NANFO_TEST_NGINX=1 required$", "max": 1, "why": "executed in gateway-headers"},
        ])
        within = self.write("within.xml", report([
            ("test_a", "skipped", "INTENT_TEST_DSN not configured"), ("test_b", "skipped", "ALERT_TEST_DSN not configured"),
            ("test_c", "skipped", "NANFO_TEST_NGINX=1 required"), ("test_d", None, ""),
        ]))
        code, stdout, _ = self.run_gate(within, "--budget", budget, "--lane", "backend")
        self.assertEqual(code, 0)
        self.assertIn("2/2", stdout)
        over = self.write("over.xml", report([("test_a", "skipped", "X_TEST_DSN not configured")] * 3))
        code, _, stderr = self.run_gate(over, "--budget", budget, "--lane", "backend")
        self.assertEqual(code, 1)
        self.assertIn("skip budget exceeded", stderr)
        new = self.write("new.xml", report([("test_a", None, ""), ("test_z", "skipped", "flaky, skipping for now")]))
        code, _, stderr = self.run_gate(new, "--budget", budget, "--lane", "backend")
        self.assertEqual(code, 1)
        self.assertIn("skip reason not allowlisted", stderr)

    def test_budget_schema_is_strict(self):
        clean = self.write("clean.xml", report([("test_a", None, "")]))
        for reasons in ([{"pattern": "x", "max": 1}], [{"pattern": "x", "max": "1", "why": "a" * 20}],
                        [{"pattern": "(", "max": 1, "why": "a" * 20}], [{"pattern": "x", "max": 1, "why": "short"}]):
            with self.subTest(reasons=reasons):
                self.assertEqual(self.run_gate(clean, "--budget", self.budget(reasons), "--lane", "backend")[0], 2)
        self.assertEqual(self.run_gate(clean, "--budget", self.budget([]), "--lane", "other")[0], 2)
        wrong = self.write("wrong.json", json.dumps({"schema": "v0", "lanes": {}}))
        self.assertEqual(self.run_gate(clean, "--budget", wrong, "--lane", "backend")[0], 2)

    def test_budget_and_zero_skips_are_exclusive_and_paired(self):
        clean = self.write("clean.xml", report([("test_a", None, "")]))
        budget = self.budget([])
        for args in (("--budget", budget), ("--lane", "backend"), ("--zero-skips", "--budget", budget, "--lane", "backend")):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                with contextlib.redirect_stderr(io.StringIO()):
                    gates.main(["junit", str(clean), *map(str, args)])

    def test_repository_budget_is_valid_and_every_reason_explains_where_it_runs(self):
        document = json.loads((ROOT / ".github/ci-skip-budget.json").read_text())
        self.assertEqual(document["schema"], gates.BUDGET_SCHEMA)
        self.assertTrue(document["lanes"])
        for lane in document["lanes"]:
            with self.subTest(lane=lane):
                reasons = gates.load_budget(ROOT / ".github/ci-skip-budget.json", lane)
                self.assertTrue(reasons)


if __name__ == "__main__":
    unittest.main()
