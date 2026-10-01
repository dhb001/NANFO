"""Workflow, ruleset and Dependabot invariants (ADR-028 CI-Repo). Runs in the portable lane."""

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
RULESET = ROOT / ".github/rulesets/main.json"
ACTIONS_APP_ID = 15368
PIN = re.compile(r"^\s*(?:-\s+)?uses:\s+(?P<action>[\w.-]+/[\w.-]+)@(?P<sha>[0-9a-f]{40})\s+#\s+v\d+\.\d+\.\d+\s*$")
# Required jobs may only be conditional in ways that are always true on pull_request.
SAFE_REQUIRED_JOB_CONDITIONS = {
    "${{ github.event_name != 'workflow_dispatch' || inputs.run_database_tests }}",
    "${{ always() }}",
}


def load(path):
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 parses the bare key `on` as boolean True.
    document["on"] = document.pop(True, document.get("on"))
    return document


@pytest.fixture(scope="module")
def workflows():
    assert WORKFLOWS, "no workflows found"
    return {path.name: load(path) for path in WORKFLOWS}


def test_every_workflow_is_least_privilege_and_never_uses_privileged_triggers(workflows):
    for name, workflow in workflows.items():
        assert workflow["permissions"] == {"contents": "read"}, name
        triggers = workflow["on"]
        assert "pull_request_target" not in triggers and "workflow_run" not in triggers, name
        for job_id, job in workflow["jobs"].items():
            assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}, f"{name}:{job_id}"


def test_concurrency_cancels_only_superseded_pull_request_runs(workflows):
    for name, workflow in workflows.items():
        concurrency = workflow["concurrency"]
        assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}", name
        assert "github.ref" in concurrency["group"] and "github.workflow" in concurrency["group"], name


def test_every_action_is_pinned_to_one_full_commit_sha_with_a_version_comment():
    shas = {}
    for path in WORKFLOWS:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^\s*(?:-\s+)?uses:", line):
                match = PIN.match(line)
                assert match, f"{path.name}:{number} is not a full-SHA pin with a version comment: {line.strip()}"
                shas.setdefault(match["action"], set()).add(match["sha"])
    assert shas, "no actions found"
    assert all(len(pins) == 1 for pins in shas.values()), f"one SHA per action expected: {shas}"


def test_every_job_is_bounded_and_checkout_never_persists_credentials(workflows):
    for name, workflow in workflows.items():
        for job_id, job in workflow["jobs"].items():
            assert 0 < job["timeout-minutes"] <= 60, f"{name}:{job_id}"
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] is False, f"{name}:{job_id}"


def test_setup_python_always_reads_the_python_version_file_of_the_project_it_tests(workflows):
    # The AI engine has its own lock and interpreter pin; every other job runs backend tooling.
    seen = set()
    for name, workflow in workflows.items():
        for job_id, job in workflow["jobs"].items():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("actions/setup-python@"):
                    expected = "ai-engine/.python-version" if (name, job_id) == ("quality.yml", "ai") \
                        else "backend/.python-version"
                    assert step["with"] == {"python-version-file": expected}, f"{name}:{job_id}"
                    seen.add(expected)
    assert seen == {"ai-engine/.python-version", "backend/.python-version"}


def always_reporting_jobs(workflows):
    """Job display names of workflows that run on every pull request (no path/branch filters)."""
    names = {}
    for workflow_name, workflow in workflows.items():
        trigger = workflow["on"].get("pull_request", "missing") if isinstance(workflow["on"], dict) else "missing"
        if trigger == "missing" or (trigger and set(trigger) & {"paths", "paths-ignore", "branches", "branches-ignore"}):
            continue
        for job_id, job in workflow["jobs"].items():
            names[job.get("name", job_id)] = (workflow_name, job)
    return names


def test_ruleset_requires_pull_requests_and_blocks_force_push_and_deletion():
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
    assert ruleset["target"] == "branch" and ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    types = [rule["type"] for rule in ruleset["rules"]]
    assert {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= set(types)
    assert ruleset["bypass_actors"] == []


def test_every_required_check_is_a_real_job_that_reports_on_every_pull_request(workflows):
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
    checks = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")["parameters"]
    assert checks["strict_required_status_checks_policy"] is True
    contexts = [check["context"] for check in checks["required_status_checks"]]
    assert all(check["integration_id"] == ACTIONS_APP_ID for check in checks["required_status_checks"])
    assert len(contexts) == len(set(contexts))
    requested = {"backend", "frontend", "ai", "python-inventories", "npm-lock", "evidence-hygiene",
                 "database-contracts", "production-browser", "packaging"}
    assert requested <= set(contexts)
    jobs = always_reporting_jobs(workflows)
    for context in contexts:
        assert context in jobs, f"required check {context!r} is not an always-reporting job name"
        condition = jobs[context][1].get("if")
        assert condition is None or condition in SAFE_REQUIRED_JOB_CONDITIONS, f"{context}: {condition}"
        assert "strategy" not in jobs[context][1], f"{context}: matrix legs report under suffixed names"


def test_backend_lane_uses_the_explicit_skip_budget_and_private_marker(workflows):
    commands = " ".join(step.get("run", "") for step in workflows["quality.yml"]["jobs"]["backend"]["steps"])
    assert '-m "not private_artifacts"' in commands and "--deselect" not in commands
    assert "--budget ../.github/ci-skip-budget.json --lane backend" in commands
    assert re.search(r"--cov-fail-under=\"\$COVERAGE_FLOOR\"", commands)
    # Measured baseline 85.60% (CI's exact command, 2026-09-25) minus one point.
    assert workflows["quality.yml"]["jobs"]["backend"]["env"]["COVERAGE_FLOOR"] == "84"


def test_dependabot_covers_every_ecosystem_weekly_and_never_bumps_frozen_runtimes():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    entries = {}
    for entry in config["updates"]:
        for directory in entry.get("directories", [entry.get("directory")]):
            entries[(entry["package-ecosystem"], directory)] = entry
    for key in [("github-actions", "/"), ("npm", "/frontend"), ("pip", "/backend"), ("uv", "/ai-engine"),
                ("docker", "/deploy"), ("docker", "/emulation")]:
        assert key in entries, key
        entry = entries[key]
        assert entry["schedule"]["interval"] == "weekly"
        assert any(group.get("update-types") == ["minor", "patch"] for group in entry["groups"].values()), key
    assert ("pip", "/emulation") not in entries, "frozen emulation requirements must not be bumped"
    assert {"dependency-name": "torch"} in entries[("uv", "/ai-engine")]["ignore"]
    docker = entries[("docker", "/emulation")]
    # C23: the successor lab (emulation/Dockerfile) is tracked; only the frozen recipe is excluded.
    assert docker["exclude-paths"] == ["Dockerfile.frozen"]
    for pattern in docker["exclude-paths"]:
        assert any((ROOT / directory.lstrip("/") / pattern).is_file() for directory in docker["directories"]), \
            f"stale Dependabot exclusion: {pattern}"


def test_history_secret_scan_allows_only_the_71_expired_tokens_and_exact_fingerprints():
    """ADR-028 section 5: the full-history gitleaks gate may not be widened silently."""
    import tomllib

    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert config["extend"] == {"useDefault": True}
    [rule] = [rule for rule in config["rules"] if rule["id"] == "nanfo-receiver-token-file"]
    [allow] = rule["allowlists"]
    assert set(allow) == {"description", "condition", "commits", "paths"}
    assert allow["condition"] == "AND"
    assert allow["commits"] == ["3f9f1f1fd247cd1af6d66cf38d94155ee32a91e1"]
    assert allow["paths"] == ["^nanfo-experimental-campaign-014/[^/]+/receiver-token$"]
    # Global allowlists target the generic rule only and never commits: either digest-shaped
    # values anywhere, or one exact file AND exact non-credential extracted expressions.
    for entry in config.get("allowlists", []):
        assert entry["targetRules"] == ["generic-api-key"] and "commits" not in entry
        assert entry["regexes"]
        if "paths" in entry:
            assert entry["condition"] == "AND" and entry.get("regexTarget", "secret") == "secret"
            assert len(entry["paths"]) == 1 and re.fullmatch(r"\^[\w/.\\-]+\$", entry["paths"][0])
            assert all(re.fullmatch(r"\^[\w=.]+\$", regex) for regex in entry["regexes"]), entry["regexes"]
        else:
            assert all("[0-9a-f]{64}" in regex for regex in entry["regexes"])
    fingerprints = [line for line in (ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")]
    assert fingerprints and len(fingerprints) == len(set(fingerprints))
    for line in fingerprints:
        # Bound to one historical commit, file, rule and line: cannot hide a new finding.
        assert re.fullmatch(r"[0-9a-f]{40}:[^:\s]+:(?:generic-api-key|jwt):\d+", line), line
    workflow = (ROOT / ".github/workflows/evidence-hygiene.yml").read_text(encoding="utf-8")
    for required in ('--log-opts="--all"', "--config .gitleaks.toml", "--gitleaks-ignore-path .gitleaksignore",
                     "fetch-depth: 0", "--exit-code 1"):
        assert required in workflow, required


def test_packaging_builds_and_scans_every_supported_image_and_never_the_frozen_lab(workflows):
    steps = workflows["packaging.yml"]["jobs"]["packaging"]["steps"]
    script = "\n".join(line for step in steps for line in step.get("run", "").splitlines()
                       if not line.lstrip().startswith("#"))
    for dockerfile in sorted((ROOT / "deploy").glob("Dockerfile.*")):
        if not dockerfile.name.endswith(".dockerignore"):
            assert f"--file deploy/{dockerfile.name}" in script, f"{dockerfile.name} is never built"
    # C23: the successor lab is linted, built by its official builder and scanned.
    assert "dockerfiles+=(emulation/Dockerfile)" in script and "python3 emulation/control.py build" in script
    assert "Dockerfile.frozen" not in script, "the frozen lab recipe is never linted or rebuilt"
    built = set(re.findall(r"--tag (\S+:ci)", script)) | set(re.findall(r'docker tag "\$image" (\S+:ci)', script))
    scans = re.findall(r"^trivy image (.*) (\S+:ci)$", script, re.M)
    assert all("--exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed" in options for options, _ in scans)
    # Only the frozen-AI image (reviewed torch exception, ADR-028 section 1) is build-only.
    assert {image for _, image in scans} == built - {"nanfo-backend-ai:ci"}
    assert "nanfo-lab:ci" in built


def test_ai_lane_runs_every_suite_and_budgets_exactly_the_registered_private_modules(workflows):
    import importlib.util

    commands = [step.get("run", "") for step in workflows["quality.yml"]["jobs"]["ai"]["steps"]]
    # The whole suite: no path list, marker deselection or --deselect can shrink it.
    assert "uv run --no-sync pytest -q --junitxml=quality-results.xml" in commands
    gate = " ".join(next(command for command in commands if "ci_gates.py junit quality-results.xml" in command).split())
    assert "--budget ../.github/ci-skip-budget.json --lane ai" in gate and "--zero-skips" not in gate
    [reason] = json.loads((ROOT / ".github/ci-skip-budget.json").read_text(encoding="utf-8"))["lanes"]["ai"]["reasons"]
    registry = [line.strip() for line in (ROOT / "ai-engine/tests/private_artifacts.txt").read_text(
        encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert registry and reason["max"] == len(registry), "one module-level skip per registered module"
    # The allowlisted text is exactly what the helper raises in a clean checkout.
    spec = importlib.util.spec_from_file_location("ai_private_store", ROOT / "ai-engine/tests/private_store.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.STORE = ROOT / "ai-engine/tests/absent-private-store"
    for module in registry:
        with pytest.raises(pytest.skip.Exception) as skipped:
            helper.requirePrivateStore(module)
        assert re.search(reason["pattern"], skipped.value.msg), skipped.value.msg


def test_backend_private_artifact_registry_names_only_real_tests():
    """A renamed or deleted test must leave backend/tests/private_artifacts.txt (no dead entries)."""
    registry = ROOT / "backend/tests/private_artifacts.txt"
    entries = [line.strip() for line in registry.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    assert entries and len(entries) == len(set(entries))
    for entry in entries:
        path, _, name = entry.partition("::")
        source = ROOT / "backend" / path
        assert path.startswith("tests/") and source.is_file(), entry
        if name:
            assert re.fullmatch(r"test_\w+", name), entry
            assert re.search(rf"^\s*(?:async\s+)?def {name}\(", source.read_text(encoding="utf-8"), re.M), entry


def test_every_lane_that_executes_allowlisted_skips_runs_at_least_that_many_cases(workflows):
    """A backend skip is only honest if its executing lane runs >= that many cases with zero skips."""
    budget = json.loads((ROOT / ".github/ci-skip-budget.json").read_text(encoding="utf-8"))
    checked = 0
    for reason in budget["lanes"]["backend"]["reasons"]:
        match = re.search(r"executed with zero skips by (?P<workflow>[\w.-]+\.yml) (?P<job>[\w-]+)", reason["why"])
        if not match:
            continue
        [job] = [job for job_id, job in workflows[match["workflow"]]["jobs"].items()
                 if job.get("name", job_id) == match["job"]]
        [gate] = [" ".join(step["run"].split()) for step in job["steps"] if "ci_gates.py junit" in step.get("run", "")]
        assert "--zero-skips" in gate, match["job"]
        floor = re.search(r"--min-cases (\d+)", gate)
        assert (int(floor.group(1)) if floor else 1) >= reason["max"], (match["job"], reason["max"])
        checked += 1
    assert checked >= 4


def test_tracked_evidence_scan_uses_the_reviewed_fixture_and_location_exception_files(workflows):
    [scan] = [" ".join(step["run"].split()) for step in workflows["evidence-hygiene.yml"]["jobs"]["evidence-hygiene"]["steps"]
              if "evidence_hygiene.py scan" in step.get("run", "")]
    assert "--tracked" in scan and "--include-untracked" not in scan, "CI scans exactly the committed tree"
    assert "--fixtures security/evidence-fixtures.v1.json" in scan
    assert "--location-exceptions security/evidence-location-exceptions.v1.json" in scan


def test_successor_lab_build_context_contains_every_copied_file():
    """packaging builds emulation/Dockerfile with context emulation/: every COPY source must ship."""
    import subprocess

    lines = (ROOT / "emulation/Dockerfile").read_text(encoding="utf-8").splitlines()
    ignored = {line.strip() for line in (ROOT / "emulation/.dockerignore").read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#")}
    sources = [part for line in lines if line.split()[:1] == ["COPY"] and "--from" not in line
               for part in line.split()[1:-1] if not part.startswith("--") and part != "."]
    assert "debian-snapshot.sources" in sources and "requirements.txt" in sources
    for source in sources:
        path = ROOT / "emulation" / source
        assert path.is_file() and source not in ignored, source
        checked = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(path)], check=False)
        assert checked.returncode == 1, f"{source} is git-ignored and would be missing from a CI checkout"


def test_api_contract_job_checks_committed_types_and_is_not_a_required_check(workflows):
    job = workflows["quality.yml"]["jobs"]["api-contract"]
    [check] = [step for step in job["steps"] if "npm run api:check" in step.get("run", "")]
    assert check["working-directory"] == "frontend"
    # No signing-key literal in the workflow: the placeholder key is random per run.
    assert "JWT_SECRET_KEY" not in check.get("env", {}) and "secrets.token_hex(32)" in check["run"]
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
    rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    assert "api-contract" not in {item["context"] for item in rule["parameters"]["required_status_checks"]}
