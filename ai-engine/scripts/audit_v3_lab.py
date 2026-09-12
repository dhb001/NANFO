"""Read-only producer artifact compatibility audit. No Docker, training or qualification."""

import argparse
import json
from pathlib import Path

from nanfo_routing.contracts import Data, Request, parseJson
from nanfo_routing.evidence import validateMeasurement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", type=Path)
    args = parser.parse_args()
    with args.matrix.open("rb") as source:
        content = source.read(16 * 1024 * 1024 + 1)
    if len(content) > 16 * 1024 * 1024:
        raise ValueError("matrix exceeds bound")
    rows = parseJson(content)
    specs = set()
    for row in rows:
        data = Data.model_validate({key: value for key, value in row.items() if key != "policy"})
        request = Request(
            command="step" if data.step_index else "reset",
            episode_id=data.episode_id if data.step_index else None,
            step_index=data.step_index or None,
            seed=data.seed,
            scenario=data.scenario,
            action=data.observation.previous_action if data.step_index else None,
            mode=data.mode,
            window_seconds=2.0,
            episode_steps=2,
        )
        validateMeasurement(data, request)
        specs.add(data.evidence["spec_hash"])
    print(
        json.dumps(
            {
                "validated_stored_windows": len(rows),
                "spec_hashes": sorted(specs),
                "live_collection": False,
                "training": False,
                "qualification": False,
            }
        )
    )


if __name__ == "__main__":
    main()
