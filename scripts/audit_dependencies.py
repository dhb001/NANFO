"""Audit exact lock inventories without installing application or frozen runtimes.

Run with Python 3.12+ and pip-audit==2.10.0. Reports deliberately retain raw feed
entries; policy decisions deduplicate exact package/version/advisory IDs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "security/dependency-exceptions.v1.json"
ADVISORY_ID = re.compile(r"(?:PYSEC-\d{4}-\d+|CVE-\d{4}-\d{4,}|GHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}|BIT-[a-z0-9-]+-\d{4}-\d+)")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def valid_version(value):
    require(text(value), "Invalid dependency version type/value")
    try:
        Version(value)
    except InvalidVersion as exc:
        raise ValueError("Invalid dependency version") from exc


def advisory_id(value):
    require(isinstance(value, str) and ADVISORY_ID.fullmatch(value), "Invalid advisory ID")


def validate_report(report, *, allow_unversioned_skip=False):
    """Validate pip-audit2.10 JSON, which has no schema-version field.

    Unknown top-level fields (including a new schema version) require review.
    Audit-only invocation never produces fixes. Duplicate advisory rows are valid;
    duplicate dependencies are not, as a dict comparison could hide an omitted row.
    """
    require(isinstance(report, dict) and set(report) == {"dependencies", "fixes"},
            "Invalid audit report schema")
    require(isinstance(report["dependencies"], list), "Invalid dependencies list")
    require(isinstance(report["fixes"], list) and not report["fixes"], "Unexpected audit fixes")
    seen = set()
    for package in report["dependencies"]:
        require(isinstance(package, dict), "Invalid dependency record")
        name = package.get("name")
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name),
                "Invalid dependency name")
        require(normalized(name) not in seen, "Duplicate audit dependency")
        seen.add(normalized(name))
        if "skip_reason" in package:
            required = {"name", "skip_reason"}
            require(set(package) in (required, required | {"version"}), "Ambiguous audit skip record")
            require(text(package["skip_reason"]), "Invalid audit skip reason")
            if "version" in package:
                valid_version(package["version"])
            else:
                require(allow_unversioned_skip, "Missing skipped dependency version")
            continue
        require(set(package) == {"name", "version", "vulns"}, "Invalid audited dependency schema")
        valid_version(package["version"])
        require(isinstance(package["vulns"], list), "Invalid vulnerability list")
        for vuln in package["vulns"]:
            require(isinstance(vuln, dict) and set(vuln) == {"id", "aliases", "fix_versions", "description"},
                    "Invalid vulnerability schema")
            advisory_id(vuln["id"])
            require(isinstance(vuln["aliases"], list), "Invalid advisory aliases")
            for alias in vuln["aliases"]:
                advisory_id(alias)
            require(isinstance(vuln["fix_versions"], list), "Invalid fixed versions")
            for version in vuln["fix_versions"]:
                valid_version(version)
            require(text(vuln["description"]), "Invalid advisory description")


def validate_policy(policy):
    require(isinstance(policy, dict) and set(policy) <= {"schema_version", "reviewed", "exceptions", "coverage_gaps"},
            "Invalid exception policy schema")
    require(type(policy.get("schema_version")) is int and policy["schema_version"] == 1,
            "Unsupported exception policy schema")
    if "reviewed" in policy:
        require(text(policy["reviewed"]), "Invalid review date")
        dt.date.fromisoformat(policy["reviewed"])
    for kind in ("exceptions", "coverage_gaps"):
        require(isinstance(policy.get(kind), list), "Invalid policy entries")
        for entry in policy[kind]:
            required = {"lane", "package", "version", "owner", "expires", "rationale", "remediation"}
            required.add("advisories" if kind == "exceptions" else "reason")
            require(isinstance(entry, dict) and set(entry) == required, "Invalid policy entry schema")
            require(all(text(entry[key]) for key in required - {"advisories"}), "Incomplete exception metadata")
            require(entry["lane"] in ("backend", "ai", "ai-upstream", "emulation"), "Invalid policy lane")
            require(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry["package"]), "Invalid policy package")
            valid_version(entry["version"])
            dt.date.fromisoformat(entry["expires"])
            if kind == "exceptions":
                require(isinstance(entry["advisories"], list) and entry["advisories"], "Invalid exception IDs")
                for identity in entry["advisories"]:
                    advisory_id(identity)


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def inventory(lane):
    if lane == "ai-upstream":
        # Supplemental public-release query, never a substitute for +cpu coverage.
        cpu = inventory("ai")["torch"]
        if cpu != "2.8.0+cpu":
            raise ValueError("Review supplemental Torch version after any frozen pin change")
        return {"torch": "2.8.0"}
    if lane == "emulation":
        lines = (ROOT / "emulation/requirements.txt").read_text().splitlines()
        return dict((normalized(line.split("==")[0]), line.split("==")[1])
                    for line in lines if line and not line.startswith("#"))
    path = ROOT / ("backend/poetry.lock" if lane == "backend" else "ai-engine/uv.lock")
    packages = tomllib.loads(path.read_text())["package"]
    return {normalized(p["name"]): p["version"] for p in packages
            if p["name"] != "nanfo-routing"}


def findings(report):
    validate_report(report)
    rows = [(normalized(p["name"]), p["version"], v["id"])
            for p in report["dependencies"] if "skip_reason" not in p for v in p["vulns"]]
    skipped = {(normalized(p["name"]), p["version"], p["skip_reason"])
               for p in report["dependencies"] if "skip_reason" in p}
    return len(rows), set(rows), skipped


def evaluate(lane, report, policy, today):
    raw, unique, skipped = findings(report)
    validate_policy(policy)
    errors = []
    accepted = set()
    for exception in policy["exceptions"]:
        if exception["lane"] != lane:
            continue
        if not all(exception.get(key) for key in ("owner", "rationale", "remediation", "expires")):
            errors.append("Incomplete exception metadata")
            continue
        if dt.date.fromisoformat(exception["expires"]) <= today:
            errors.append(f"Expired exception: {exception['package']}")
            continue
        accepted.update((exception["package"], exception["version"], advisory)
                        for advisory in exception["advisories"])
    for row in sorted(unique - accepted):
        errors.append("Unreviewed advisory: " + " / ".join(row))
    for name, version, reason in sorted(skipped):
        matches = [e for e in policy.get("coverage_gaps", [])
                   if e["lane"] == lane and e["package"] == name and e["version"] == version
                   and e["reason"] == reason and dt.date.fromisoformat(e["expires"]) > today
                   and all(e.get(key) for key in ("owner", "rationale", "remediation"))]
        if not matches:
            errors.append(f"Unreviewed audit coverage gap: {name}=={version}: {reason}")
    return {"lane": lane, "raw_advisory_rows": raw,
            "distinct_package_advisory_pairs": len(unique),
            "affected_packages": len({r[0] for r in unique}),
            "accepted_pairs": len(unique & accepted),
            "coverage_gaps": [list(row) for row in sorted(skipped)], "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=("backend", "ai", "ai-upstream", "emulation"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=POLICY)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pins = inventory(args.lane)
    requirements = args.output / f"{args.lane}-inventory.txt"
    requirements.write_text("".join(f"{name}=={version}\n" for name, version in sorted(pins.items())))
    destination = args.output / f"{args.lane}-raw.json"
    destination.unlink(missing_ok=True)
    summary_path = args.output / f"{args.lane}-summary.json"
    summary_path.unlink(missing_ok=True)
    result = subprocess.run([sys.executable, "-m", "pip_audit", "--no-deps", "--disable-pip",
                             "--progress-spinner", "off", "--format", "json",
                             "-r", str(requirements), "-o", str(destination)], check=False)
    if result.returncode not in (0, 1) or not destination.exists():
        raise SystemExit("Audit tool/feed failure")
    try:
        report = json.loads(destination.read_text(), object_pairs_hook=unique_json_object)
        validate_report(report, allow_unversioned_skip=True)
    except (ValueError, TypeError) as exc:
        raise SystemExit(f"Invalid audit report: {exc}") from exc
    # pip-audit omits the version on skipped entries. Restore it only when the
    # tool's exact reason identifies the requested pin; never normalize +cpu away.
    for package in report["dependencies"]:
        name = normalized(package["name"])
        if "skip_reason" in package and name in pins and "version" not in package:
            expected = f"Dependency not found on PyPI and could not be audited: {name} ({pins[name]})"
            if package["skip_reason"] == expected:
                package["version"] = pins[name]
    actual = {normalized(p["name"]): p.get("version") for p in report["dependencies"]}
    if actual != pins:
        raise SystemExit("Audit inventory incomplete or changed; refusing a clean claim")
    try:
        summary = evaluate(args.lane, report,
                           json.loads(args.policy.read_text(), object_pairs_hook=unique_json_object), dt.date.today())
    except (ValueError, TypeError) as exc:
        raise SystemExit(f"Invalid audit report/policy: {exc}") from exc
    if result.returncode == 1 and not summary["raw_advisory_rows"]:
        raise SystemExit("Audit exited unsuccessfully without advisory results")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    raise SystemExit(bool(summary["errors"]))


def unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "Duplicate JSON key")
        value[key] = item
    return value


if __name__ == "__main__":
    main()
