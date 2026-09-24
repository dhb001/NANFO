"""CI gates over pytest JUnit XML reports (stdlib only, ADR-028).

    python .github/scripts/ci_gates.py junit REPORT [--zero-skips] [--min-cases N]
        [--require TEST_NAME ...] [--budget .github/ci-skip-budget.json --lane NAME]

Every mode fails on unreadable/empty reports and on failed or erroring cases.

--zero-skips      The lane claims zero skips: any skipped (or xfailed) case fails.
--budget/--lane   Skips are allowed only for reasons allowlisted for the lane, each up to
                  its explicit count. A new kind of skip therefore fails even when the
                  total is small, and growth of a known kind needs a reviewed bump.
--require NAME    The named test function (all its parametrizations) must be present
                  and must have passed.
--min-cases N     Guards against silently shrinking collection.

Output contains counts, test ids and skip reasons only (never failure bodies).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

BUDGET_SCHEMA = "nanfo-ci-skip-budget-v1"


class GateError(Exception):
    """A gate refusal with a human-readable reason."""


@dataclass(frozen=True)
class Case:
    nodeid: str
    name: str
    outcome: str  # passed | skipped | failure | error
    reason: str


def load_cases(path: Path) -> list[Case]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise GateError(f"unreadable JUnit report {path}: {type(exc).__name__}") from exc
    cases = []
    for element in root.iter("testcase"):
        outcome, reason = "passed", ""
        for tag in ("error", "failure", "skipped"):
            child = element.find(tag)
            if child is not None:
                outcome = tag
                reason = (child.get("message") or child.text or "").strip()
                break
        name = element.get("name", "")
        cases.append(Case(f"{element.get('classname', '')}::{name}", name, outcome, reason))
    return cases


def load_budget(path: Path, lane: str) -> list[dict]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"unreadable skip budget {path}") from exc
    if not isinstance(document, dict) or document.get("schema") != BUDGET_SCHEMA:
        raise GateError(f"skip budget must declare schema {BUDGET_SCHEMA}")
    entry = document.get("lanes", {}).get(lane)
    if not isinstance(entry, dict) or not isinstance(entry.get("reasons"), list):
        raise GateError(f"skip budget has no lane {lane!r}")
    reasons = []
    for item in entry["reasons"]:
        if not (isinstance(item, dict) and set(item) == {"pattern", "max", "why"}
                and isinstance(item["pattern"], str) and item["pattern"]
                and type(item["max"]) is int and item["max"] >= 0
                and isinstance(item["why"], str) and len(item["why"].strip()) >= 16):
            raise GateError("each budget reason needs pattern, integer max >= 0 and a why (>= 16 chars)")
        try:
            reasons.append({**item, "regex": re.compile(item["pattern"])})
        except re.error as exc:
            raise GateError(f"invalid budget pattern {item['pattern']!r}") from exc
    return reasons


def check_junit(cases: list[Case], *, zero_skips=False, min_cases=0, required=(), budget=None) -> list[str]:
    """Return human-readable gate errors (empty list = pass) and never raise on content."""
    errors = []
    if not cases:
        errors.append("report contains no test cases")
    if len(cases) < min_cases:
        errors.append(f"expected at least {min_cases} cases, found {len(cases)}")
    for case in cases:
        if case.outcome in ("failure", "error"):
            errors.append(f"{case.outcome}: {case.nodeid}")
    skipped = [case for case in cases if case.outcome == "skipped"]
    if zero_skips:
        errors.extend(f"skip in zero-skip lane: {case.nodeid} ({case.reason})" for case in skipped)
    for name in required:
        selected = [case for case in cases if case.name == name or case.name.startswith(name + "[")]
        if not selected:
            errors.append(f"required case missing: {name}")
        errors.extend(f"required case did not pass ({case.outcome}): {case.nodeid}"
                      for case in selected if case.outcome != "passed")
    if budget is not None:
        used = [0] * len(budget)
        for case in skipped:
            index = next((i for i, item in enumerate(budget) if item["regex"].search(case.reason)), None)
            if index is None:
                errors.append(f"skip reason not allowlisted: {case.nodeid} ({case.reason})")
            else:
                used[index] += 1
        for item, count in zip(budget, used):
            if count > item["max"]:
                errors.append(f"skip budget exceeded for /{item['pattern']}/: {count} > {item['max']} ({item['why']})")
    return errors


def summary(cases: list[Case], budget=None) -> str:
    counts = {outcome: sum(case.outcome == outcome for case in cases)
              for outcome in ("passed", "skipped", "failure", "error")}
    lines = [f"{len(cases)} cases: " + ", ".join(f"{key}={value}" for key, value in counts.items())]
    if budget is not None:
        for item in budget:
            count = sum(case.outcome == "skipped" and bool(item["regex"].search(case.reason)) for case in cases)
            lines.append(f"  skip reason /{item['pattern']}/: {count}/{item['max']} - {item['why']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    junit = commands.add_parser("junit", help="gate a pytest JUnit XML report")
    junit.add_argument("report", type=Path)
    junit.add_argument("--zero-skips", action="store_true")
    junit.add_argument("--min-cases", type=int, default=1)
    junit.add_argument("--require", action="append", default=[], metavar="TEST_NAME")
    junit.add_argument("--budget", type=Path)
    junit.add_argument("--lane")
    args = parser.parse_args(argv)
    if (args.budget is None) != (args.lane is None):
        parser.error("--budget and --lane must be used together")
    if args.zero_skips and args.budget:
        parser.error("--zero-skips and --budget are mutually exclusive")
    try:
        cases = load_cases(args.report)
        budget = load_budget(args.budget, args.lane) if args.budget else None
    except GateError as exc:
        print(f"ci-gate: {exc}", file=sys.stderr)
        return 2
    errors = check_junit(cases, zero_skips=args.zero_skips, min_cases=args.min_cases,
                         required=args.require, budget=budget)
    print(summary(cases, budget))
    for error in errors:
        print(f"ci-gate: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
