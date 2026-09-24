"""Portable-lane boundary regressions; subprocesses are faked, the real lane never recurses."""

import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import run_portable_tests as portable


def write_junit(path, outcomes):
    """outcomes: list of (classname, name, tag|None) written as one pytest-style suite."""
    suites = ET.Element("testsuites")
    suite = ET.SubElement(suites, "testsuite", name="pytest")
    for classname, name, tag in outcomes:
        case = ET.SubElement(suite, "testcase", classname=classname, name=name)
        if tag:
            ET.SubElement(case, tag, message="synthetic")
    ET.ElementTree(suites).write(path, encoding="unicode")


class FakePytest:
    """Stands in for `python -m pytest <suite> --junitxml=...`; records every invocation."""

    def __init__(self, outcomes_by_suite=None, returncode=0):
        self.outcomes_by_suite = outcomes_by_suite or {}
        self.returncode = returncode
        self.commands = []

    def __call__(self, command, **_kwargs):
        self.commands.append(command)
        suite = command[3]
        report = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
        write_junit(report, self.outcomes_by_suite.get(suite, [(suite.replace("/", "."), "test_ok", None)]))
        return subprocess.CompletedProcess(command, self.returncode)


def all_boundary_nodeids(suite):
    return [f"{node}::test_case" for node in portable.suite_exclusions(suite)] + [f"{suite}/test_x.py::test_ok"]


class PortableLaneTests(unittest.TestCase):
    def run_main(self, fake, nodeids=all_boundary_nodeids):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(portable, "collected_nodeids", side_effect=lambda suite, env: nodeids(suite)), \
                patch.object(portable.subprocess, "run", side_effect=fake), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            portable.main(["--junitxml", str(Path(directory) / "portable.xml")])
            return output.getvalue()

    def test_lane_covers_deploy_emulation_root_scripts_and_ci_gates(self):
        self.assertEqual(portable.SUITES, ("deploy", "emulation/tests", "scripts", ".github/scripts"))
        for suite in portable.SUITES:
            self.assertTrue((portable.ROOT / suite).is_dir(), suite)

    def test_every_exclusion_belongs_to_exactly_one_suite_and_has_a_reason(self):
        for node, reason in portable.EXCLUSIONS.items():
            with self.subTest(node=node):
                self.assertEqual(sum(node.startswith(suite + "/") for suite in portable.SUITES), 1)
                self.assertGreaterEqual(len(reason.strip()), 16)

    def test_exclusion_prefixes_match_classes_methods_and_parameters_only(self):
        self.assertTrue(portable.matches("s/t.py::C", "s/t.py::C::test_a"))
        self.assertTrue(portable.matches("s/t.py::C::test_a", "s/t.py::C::test_a[1]"))
        self.assertFalse(portable.matches("s/t.py::C::test_a", "s/t.py::C::test_ab"))

    def test_stale_exclusion_is_detected(self):
        with patch.dict(portable.EXCLUSIONS, {"scripts/test_x.py::A::test_gone": "renamed test left behind"},
                        clear=True):
            self.assertEqual(portable.stale_exclusions("scripts", ["scripts/test_x.py::A::test_kept"]),
                             ["scripts/test_x.py::A::test_gone"])
            self.assertEqual(portable.stale_exclusions("deploy", []), [])

    def test_skipped_failed_and_erroring_cases_are_problems(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "r.xml"
            write_junit(path, [("a", "ok", None), ("a", "s", "skipped"), ("a", "f", "failure"), ("a", "e", "error")])
            problems = portable.outcome_problems(ET.parse(path).getroot().findall(".//testcase"))
        self.assertEqual(problems, [("a::s", "skipped"), ("a::f", "failure"), ("a::e", "error")])

    def test_clean_lane_passes_and_deselects_only_its_own_boundary(self):
        fake = FakePytest()
        output = self.run_main(fake)
        self.assertIn("zero skips", output)
        self.assertEqual([command[3] for command in fake.commands], list(portable.SUITES))
        for command in fake.commands:
            deselected = {arg.split("=", 1)[1] for arg in command if arg.startswith("--deselect=")}
            self.assertEqual(deselected, set(portable.suite_exclusions(command[3])))

    def test_a_single_skip_fails_the_zero_skip_lane(self):
        fake = FakePytest({"deploy": [("deploy.t", "test_ok", None), ("deploy.t", "test_skip", "skipped")]})
        with self.assertRaisesRegex(SystemExit, "zero skips"):
            self.run_main(fake)

    def test_stale_boundary_entry_fails_even_when_tests_pass(self):
        with self.assertRaisesRegex(SystemExit, "Stale portable exclusions"):
            self.run_main(FakePytest(), nodeids=lambda suite: [f"{suite}/test_x.py::test_ok"])

    def test_empty_suite_fails(self):
        with self.assertRaisesRegex(SystemExit, "empty suites"):
            self.run_main(FakePytest({".github/scripts": []}))

    def test_pytest_failure_status_propagates(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_main(FakePytest(returncode=1))
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
