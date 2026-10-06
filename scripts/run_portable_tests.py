"""Run deployment/emulation/root-script/CI-gate tests with an exact nonportable boundary.

Use the locked backend interpreter (for example from backend/:
``poetry run python ../scripts/run_portable_tests.py --junitxml=portable-results.xml``).
No lab is launched. Historical inputs are not replaced by invented qualification
artifacts. The lane claims zero skips, so it fails when any case is skipped, fails or
errors, when a suite collects nothing, and when a boundary entry below no longer
matches a collected test (stale exclusions silently shrink the boundary report).
"""

import argparse
from pathlib import Path
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
# Every portable Python suite outside backend/ and ai-engine/ (which have their own lanes).
SUITES = ("deploy", "emulation/tests", "scripts", ".github/scripts")
EXCLUSIONS = {
    "emulation/tests/test_controller.py::ControllerTests": "Pinned Ryu parser/image required",
    "emulation/tests/test_runner.py::RunnerTests::testPinnedMininetSkipsGlobalSysctls": "Pinned Mininet image required",
    "emulation/tests/test_experiment.py::ExperimentLiveTests": "Privileged owned SDN fault lab required",
    "emulation/tests/test_ospf.py::OSPFLiveTests": "Privileged owned FRR lab required",
    "scripts/test_adr024_campaign.py::CampaignTests::test_exact_original_writer_rebinding_changes_only_image": "Ignored checkpoint and historical source archive required",
    "scripts/test_recover_qualified_runtime.py::RecoveryTests::test_original_archive_and_checkpoint_are_exact": "Ignored exact historical artifacts required",
    "scripts/test_recover_qualified_runtime.py::RecoveryTests::test_registry_template_does_not_fabricate_installation": "Ignored exact historical artifacts required",
    "scripts/test_recover_qualified_runtime.py::RecoveryTests::test_actual_frozen_validator_rejects_distinct_image_source_and_spec": "Frozen AI interpreter and ignored artifacts required",
    "scripts/test_verify_adr024_campaign.py::IndependentVerifierTests::test_completed_raw_reconstruction_and_tampered_report_rejection": "Private raw completed campaign required",
}
PROBLEM_TAGS = ("skipped", "failure", "error")


def suite_exclusions(suite):
    return [node for node in EXCLUSIONS if node.startswith(suite + "/")]


def matches(prefix, nodeid):
    return nodeid == prefix or nodeid.startswith(prefix + "::") or nodeid.startswith(prefix + "[")


def stale_exclusions(suite, nodeids):
    """Boundary entries of this suite that match no collected test id."""
    return [node for node in suite_exclusions(suite) if not any(matches(node, nodeid) for nodeid in nodeids)]


def collected_nodeids(suite, env):
    result = subprocess.run([sys.executable, "-m", "pytest", suite, "--collect-only", "-q", "-p", "no:cacheprovider"],
                            cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"Portable lane collection failed: {suite}\n{result.stdout[-4000:]}{result.stderr[-4000:]}")
    return [line.strip() for line in result.stdout.splitlines() if "::" in line]


def outcome_problems(cases):
    """(nodeid, outcome) for every skipped, failed or erroring JUnit case."""
    problems = []
    for case in cases:
        for tag in PROBLEM_TAGS:
            if case.find(tag) is not None:
                problems.append((f"{case.get('classname')}::{case.get('name')}", tag))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junitxml", type=Path, required=True)
    args = parser.parse_args(argv)
    Path("/tmp/opencode").mkdir(exist_ok=True)
    report = args.junitxml.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    # Never accept a stale passing report after interrupted pytest.
    report.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in (".", "backend", "scripts")),
           "PYTHONNOUSERSITE": "1"}
    combined = ET.Element("testsuites")
    status = 0
    per_suite = {}
    stale = []
    # Deployment entrypoint tests set process umask. Each suite receives a fresh
    # process, so later filesystem-security fixtures retain their real defaults.
    for suite in SUITES:
        stale.extend(stale_exclusions(suite, collected_nodeids(suite, env)))
        part = report.with_name(f"{report.stem}-{suite.strip('.').replace('/', '-')}.xml")
        part.unlink(missing_ok=True)
        command = [sys.executable, "-m", "pytest", suite, "-q", "-p", "no:cacheprovider", f"--junitxml={part}",
                   *[f"--deselect={node}" for node in suite_exclusions(suite)]]
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        status |= result.returncode
        if not part.exists():
            raise SystemExit(f"Missing test report: {suite}")
        suites = list(ET.parse(part).getroot())
        per_suite[suite] = sum(len(item.findall(".//testcase")) for item in suites)
        combined.extend(suites)
    ET.ElementTree(combined).write(report, encoding="unicode")
    if stale:
        raise SystemExit("Stale portable exclusions (no matching collected test): " + ", ".join(stale))
    if status:
        raise SystemExit(status)
    cases = ET.parse(report).getroot().findall(".//testcase")
    problems = outcome_problems(cases)
    empty = [suite for suite, count in per_suite.items() if not count]
    if not cases or problems or empty:
        details = "\n".join(f"  {outcome}: {nodeid}" for nodeid, outcome in problems[:50])
        raise SystemExit(f"Portable lane must execute every suite with zero skips/failures/errors; "
                         f"empty suites: {empty or 'none'}\n{details}")
    print(f"Portable lane: {len(cases)} JUnit cases, zero skips "
          f"({', '.join(f'{suite}={count}' for suite, count in per_suite.items())}); explicit boundary:")
    for node, reason in EXCLUSIONS.items():
        print(f"  {node}: {reason}")


if __name__ == "__main__":
    main()
