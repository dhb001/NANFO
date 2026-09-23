"""Run deployment/emulation/root-script tests with an exact nonportable boundary.

Use the locked backend interpreter from the repository root. No lab is launched.
Historical inputs are not replaced by invented qualification artifacts.
"""

import argparse
from pathlib import Path
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junitxml", type=Path, required=True)
    args = parser.parse_args()
    Path("/tmp/opencode").mkdir(exist_ok=True)
    report = args.junitxml.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    # Never accept a stale passing report after interrupted pytest.
    report.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in (".", "backend", "scripts")),
           "PYTHONNOUSERSITE": "1"}
    combined = ET.Element("testsuites")
    status = 0
    # Deployment entrypoint tests set process umask. Each suite receives a fresh
    # process, so later filesystem-security fixtures retain their real defaults.
    for suite in ("deploy", "emulation/tests", "scripts"):
        part = report.with_name(f"{report.stem}-{suite.split('/')[0]}.xml")
        part.unlink(missing_ok=True)
        command = [sys.executable, "-m", "pytest", suite, "-q", f"--junitxml={part}",
                   *[f"--deselect={node}" for node in EXCLUSIONS if node.startswith(suite)]]
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        status |= result.returncode
        if not part.exists():
            raise SystemExit(f"Missing test report: {suite}")
        combined.extend(ET.parse(part).getroot())
    ET.ElementTree(combined).write(report, encoding="unicode")
    if status:
        raise SystemExit(status)
    cases = ET.parse(report).getroot().findall(".//testcase")
    if not cases or any(case.find(tag) is not None for case in cases
                        for tag in ("skipped", "failure", "error")):
        raise SystemExit("Portable lane must execute cases with zero skips/failures/errors")
    print(f"Portable lane: {len(cases)} JUnit cases, zero skips; explicit boundary:")
    for node, reason in EXCLUSIONS.items():
        print(f"  {node}: {reason}")


if __name__ == "__main__":
    main()
