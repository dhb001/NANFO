"""Read-only reconstruction of the saved actual live service acceptance evidence."""

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

from app.modules.autonomy.schemas import Observation, contract_digest
from scripts.frozen_model_diagnostic import canonical_hash


def read(path):
    return json.loads(path.read_bytes())


def audit(root):
    plan = read(root / "plan.json")
    outcome = read(root / "result.json")
    assert outcome["status"] == "passed" and not outcome["recommendations_applied"]
    assert not plan["training"] and plan["fixed_acquisition_action"] == 0
    assert all(row["removed"] for row in read(root / "cleanup.json"))
    decisions = read(root / "durable-decisions.json")
    recommended = [row for row in decisions if row["status"] == "recommended"]
    assert len(recommended) == 4
    assert len([row for row in decisions if row["status"] == "observed"]) == 2
    assert len([row for row in decisions if row["status"] == "blocked"]) == 2
    assert all(row["execution_id"] is None and row["authorization"] is None and row["safety"] is None for row in decisions)
    identities, measured = [], 0
    for item in plan["episodes"]:
        scenario = item["scenario"]
        directory = root / scenario
        raw = (directory / "feed/evidence.jsonl").read_bytes()
        closed = read(directory / "feed/closed.json")
        assert hashlib.sha256(raw).hexdigest() == closed["evidence_sha256"]
        frames = [json.loads(line) for line in raw.splitlines()]
        ipc = [row for row in frames if row["kind"] == "ipc" and row["request"]["command"] != "close"]
        assert len(ipc) == 3
        admission = read(directory / "admission.json")
        attached = read(directory / "attached.json")
        assert attached["feed_offset"] == len(raw.splitlines()[0]) + 1
        assert hashlib.sha256(raw.splitlines()[0]).hexdigest() == admission["session_sha256"]
        declared = datetime.fromisoformat(plan["declared_at"])
        anchor_wall = datetime.fromisoformat(attached["anchor_wall"])
        assert anchor_wall > declared
        for index, frame in enumerate(ipc):
            data = frame["response"]["data"]
            assert data["seed"] == item["seed"] and data["scenario"] == scenario and data["mode"] == "matched"
            assert data["observation"]["previous_action"] == 0
            assert data["evidence"]["measurement_complete"] is True
            assert data["evidence"]["provenance"]["lab_image_id"] == plan["image_id"]
            snapshot = read(directory / f"snapshot-{index}.json")
            assert snapshot["history"] == {"version": 3, "frames": [{"request": frame["request"], "response": frame["response"]}]}
            assert snapshot["history_sha256"] == canonical_hash(snapshot["history"])
            end = data["evidence"]["post_control_interval"]["end"]
            start = data["evidence"]["post_control_interval"]["start"]
            assert attached["anchor_monotonic"] < start < end
            observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
            assert observed == anchor_wall + timedelta(seconds=end - attached["anchor_monotonic"])
            receipt = read(root / "observations" / ("receipt-" + snapshot["snapshot_id"] + ".json"))
            assert receipt["history_sha256"] == snapshot["history_sha256"]
            assert receipt["admission_sha256"] == hashlib.sha256((directory / "admission.json").read_bytes()).hexdigest()
            if index:
                decision = read(root / f"{scenario}-recommend-{index}-decision.json")
                assert decision["status"] == "recommended"
                assert decision["proposal"]["action_id"] == item["expected_route"]
                assert decision["observation"]["observed_at"] == snapshot["observed_at"]
                completed = datetime.fromisoformat(decision["updated_at"].replace("Z", "+00:00"))
                assert 0 < (completed - observed).total_seconds() <= 30
                identities.append({"decision_id": decision["decision_id"], "scenario": scenario,
                    "route": decision["proposal"]["action_id"], "age_at_persistence_seconds": (completed - observed).total_seconds()})
            measured += 1
        helper = read(directory / "fresh-helper.json")
        assert helper["status"] == "fresh_provider_inference_verified"
        assert contract_digest(Observation.model_validate(helper["observation"])) == helper["observation_sha256"]
        assert not read(directory / "stale.json")["fresh"]
        assert not read(directory / "disconnected.json")["compatible"]
    files = {str(path.relative_to(root)): {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "size_bytes": path.stat().st_size} for path in sorted(root.rglob("*"))
             if path.is_file() and path.name != "evidence-audit.json"}
    return {"status": "passed", "measured_frames": measured, "durable_recommendations": identities,
            "original_frame_preservation": True, "real_clock_derived_freshness": True,
            "no_recommendation_dispatch": True, "cleanup_verified": True, "files": files}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = audit(args.root)
    with (args.root / "evidence-audit.json").open("x") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({key: value for key, value in result.items() if key != "files"}))
