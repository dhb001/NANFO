"""Governance files stay consistent with CI (ADR-028 CI-Repo task 12). Runs in the portable lane."""

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
RULESET = ROOT / ".github/rulesets/main.json"
# The documented convention: `Type(area): summary [FINDING-ID]`; the area is optional.
COMMIT_TYPES = ("Feat", "Fix", "Security", "Perf", "Refactor", "Test", "Docs", "CI", "Deps", "Chore", "Revert")
SUBJECT = re.compile(rf"^(?:{'|'.join(COMMIT_TYPES)})(?:\([a-z][a-z0-9-]*\))?: \S.*$")


def required_checks():
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
    rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    return [check["context"] for check in rule["parameters"]["required_status_checks"]]


def job_names(workflow_file):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / workflow_file).read_text(encoding="utf-8"))
    return {job.get("name", job_id) for job_id, job in workflow["jobs"].items()}


def test_contributing_lists_exactly_the_required_checks_of_the_ruleset():
    text = CONTRIBUTING.read_text(encoding="utf-8")
    block = re.search(r"<!-- required-checks:start -->\n(.*?)<!-- required-checks:end -->", text, re.S)
    assert block, "CONTRIBUTING.md lost its required-checks block"
    documented = re.findall(r"^- `([a-z0-9-]+)`$", block.group(1), re.M)
    assert len(documented) == len(set(documented))
    assert set(documented) == set(required_checks())


def test_contributing_documents_how_the_owner_applies_and_updates_the_ruleset():
    text = CONTRIBUTING.read_text(encoding="utf-8")
    assert "gh api --method POST repos/dhb001/NANFO/rulesets --input .github/rulesets/main.json" in text
    assert 'gh api --method PUT "repos/dhb001/NANFO/rulesets/$id" --input .github/rulesets/main.json' in text
    name = json.loads(RULESET.read_text(encoding="utf-8"))["name"]
    assert f'select(.name == "{name}")' in text
    # SECURITY.md links to this section by its anchor.
    assert "## Branch protection (owner action)" in text
    assert "CONTRIBUTING.md#branch-protection-owner-action" in (ROOT / "SECURITY.md").read_text(encoding="utf-8")


def test_every_lane_that_executes_allowlisted_skips_is_a_required_check():
    """A skip is only acceptable when the lane that really runs those tests can block a merge."""
    budget = json.loads((ROOT / ".github/ci-skip-budget.json").read_text(encoding="utf-8"))
    lanes = set()
    for lane in budget["lanes"].values():
        for reason in lane["reasons"]:
            match = re.search(r"executed with zero skips by (?P<workflow>[\w.-]+\.yml) (?P<job>[\w-]+)", reason["why"])
            if match:
                assert match["job"] in job_names(match["workflow"]), reason["why"]
                lanes.add(match["job"])
            else:
                # Everything else must be an explicit owner/private lane, never a silent skip.
                assert re.match(r"^(?:Owner opt-in lane|Private evidence lane) ", reason["why"]), reason["why"]
    assert lanes, "no executing lanes found in the skip budget"
    assert lanes <= set(required_checks()), sorted(lanes - set(required_checks()))


def test_contributing_examples_and_dependabot_prefixes_follow_the_commit_convention():
    text = CONTRIBUTING.read_text(encoding="utf-8")
    examples = re.search(r"Examples:\n\n```\n(.*?)```", text, re.S)
    assert examples
    subjects = [line for line in examples.group(1).splitlines() if line]
    assert subjects and all(SUBJECT.match(line) for line in subjects), subjects
    assert all(re.search(r"\[[^\]]+\]$", line) for line in subjects if not line.startswith("Deps("))
    assert SUBJECT.match("Feat: legacy subject without an area")
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    prefixes = {entry["commit-message"]["prefix"] for entry in config["updates"]}
    for prefix in prefixes:
        # Dependabot appends ": <summary>" after a closing parenthesis.
        assert re.fullmatch(r"Deps\([a-z][a-z0-9-]*\)", prefix), prefix
        assert SUBJECT.match(f"{prefix}: bump example")


def test_codeowners_names_the_maintainer_and_every_rule_is_well_formed():
    lines = [line.strip() for line in (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8").splitlines()]
    rules = [line.split() for line in lines if line and not line.startswith("#")]
    assert rules and rules[0] == ["*", "@dhb001"], "the default rule must come first"
    for pattern, *owners in rules:
        assert owners and all(re.fullmatch(r"@[A-Za-z0-9-]+(?:/[A-Za-z0-9._-]+)?", owner) for owner in owners), pattern


def test_pull_request_template_asks_for_the_finding_and_the_evidence_gates():
    template = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
    assert "Type(area): imperative summary [FINDING-ID]" in template
    for required in ("## Finding", "## Tests", "private_artifacts.txt", "evidence_hygiene.py", ".env.example"):
        assert required in template, required
