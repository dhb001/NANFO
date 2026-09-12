"""Standalone measured-alert adapter after campaign slot release, not a nested lock."""

import argparse
import json
import secrets
import sys
import types
from pathlib import Path

from scripts.acceptance.campaign import preflight, sources
from scripts.acceptance.common import Blocked, write_new
from scripts.acceptance.runtime import PRESERVABLE_ID, snapshot
from scripts.acceptance.stage import BACKEND, adapted_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--slot-released", action="store_true", required=True)
    parser.add_argument("--preserve-stopped-container", choices=[PRESERVABLE_ID], required=True)
    args = parser.parse_args()
    directory = Path("/tmp/opencode") / ("step14-alerts-external-" + secrets.token_hex(16))
    directory.mkdir(mode=0o700)
    before = preflight(sources(), preserve_stopped=[args.preserve_stopped_container])
    write_new(directory / "baseline-before.json", before)
    path = BACKEND / "scripts/verify_measured_alerts.py"
    code, changes = adapted_source(path, {
        "@alerts.example.invalid": "@alerts.example.com",
        "operator@alerts.example.invalid": "operator@alerts.example.com",
    })
    write_new(directory / "adaptations.json", changes)
    module = types.ModuleType("scripts.acceptance_measured_alerts")
    module.__file__ = str(path)
    exec(code, module.__dict__)
    argv = ["--live", "--slot-released", "--timeout-seconds", "480", "--output-parent", str(directory),
            "--preserve-stopped-container", args.preserve_stopped_container]
    write_new(directory / "command.json", {"argv": [sys.executable, "-m", "scripts.verify_measured_alerts", *argv],
                                           "adaptation": "valid login email fixture only; no detector/traffic/measurement changes"})
    try:
        result = module.main(argv)
    finally:
        after = snapshot()
        write_new(directory / "baseline-after.json", after)
        unchanged = before == after
        write_new(directory / "preservation.json", {"passed": unchanged, "preserved_id": PRESERVABLE_ID,
                  "before_sha256": before[PRESERVABLE_ID]["InspectSHA256"],
                  "after_sha256": after.get(PRESERVABLE_ID, {}).get("InspectSHA256")})
    if not unchanged:
        raise Blocked("external_baseline_changed")
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({"status": "failed", "reason": "external_adapter_failed_diagnostics_withheld"}))
        raise SystemExit(1) from None
