"""Read one bounded JSON scenario from stdin; print a model-only estimate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.network.energy_estimate import EnergyScenario, estimate_energy  # noqa: E402

MAX_INPUT_BYTES = 1_048_576


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        print(json.dumps({"error": "Scenario exceeds 1 MiB.", "model_only": True}), file=sys.stderr)
        return 2
    try:
        scenario = EnergyScenario.model_validate_json(raw)
        result = estimate_energy(scenario)
    except ValidationError as exc:
        print(json.dumps({
            "error": "Invalid energy scenario.", "model_only": True,
            "details": exc.errors(include_input=False, include_context=False, include_url=False),
        }), file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
