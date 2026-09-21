"""Operator-only offline ADR021 review. Output to stdout; no artifact writes."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from .shadow.io import loadEvaluation
else:
    from shadow.io import loadEvaluation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True, help="separately trusted manifest digest")
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        decision = loadEvaluation(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            diagnostic_path=args.diagnostic,
            outcomes_path=args.outcomes,
            benchmark_path=args.benchmark,
            now=datetime.now(UTC),
        )
        print(decision.model_dump_json(indent=2))
        return 2 if decision.status == "abstain" else 0
    except (ValueError, OSError, TypeError, KeyError):
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": "shadow_evidence_validation_failed",
                    "execution": "not_applied",
                    "safety_authorized": False,
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
