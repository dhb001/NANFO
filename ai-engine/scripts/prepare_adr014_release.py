"""Read completed lab handoff and raw smoke evidence; write AI-owned pinned release."""

import hashlib
from pathlib import Path

from nanfo_routing.artifacts import atomicWrite
from nanfo_routing.contracts import Data, Request, jsonBytes, parseJson
from nanfo_routing.evidence import validateMeasurement
from nanfo_routing.expanded import frozenPlan

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff"
SPEC = "bb15142a19ed3ee87a6aec2c6f9109d789d9736a5e6afda826ad898ef5fe7200"


def main():
    lab = ROOT.parent / "emulation"
    handoff = lab / "DRAIN-V4-VALIDATION.md"
    text = handoff.read_text()
    if IMAGE not in text or SPEC not in text or "The lab slot is released" not in text:
        raise ValueError("completed pinned lab release not present")
    hashes, spec = {}, None
    for mode, episode in (
        ("matched", "5d103ad3-7fe0-4564-a584-a771a454e3ec"),
        ("ospf", "9aec0872-c979-4c01-bb02-d977e6addbc2"),
    ):
        summary = parseJson(
            (lab / "output" / f"experiment-smoke-{mode}-{episode}-summary.json").read_bytes()
        )
        if (
            summary["passed"] is not True
            or summary["cleanup_verified"] is not True
            or summary["lab_image_ids"] != [IMAGE]
            or summary["environment_spec_hashes"] != [SPEC]
        ):
            raise ValueError("lab smoke not completed with exact released provenance")
        for index in range(3):
            path = lab / "output" / f"experiment-{episode}-{index:02}.json"
            content = path.read_bytes()
            data = Data.model_validate(parseJson(content))
            request = Request(
                command="reset" if index == 0 else "step",
                seed=1000,
                scenario="path0",
                mode=mode,
                window_seconds=2.0,
                episode_steps=2,
                episode_id=episode if index else None,
                step_index=index if index else None,
                action=index % 2 if index else None,
            )
            validateMeasurement(data, request)
            spec = data.evidence["environment_spec"]
            if (
                data.evidence["spec_hash"] != SPEC
                or data.evidence["provenance"]["lab_image_id"] != IMAGE
            ):
                raise ValueError("raw smoke provenance mismatch")
            hashes[str(path.relative_to(lab))] = hashlib.sha256(content).hexdigest()
    plan = frozenPlan()
    # Only seed metadata, never historical validation/test outcomes or weights.
    old = {}
    for path in (ROOT / "artifacts").glob("**/train*/summary.json"):
        row = parseJson(path.read_bytes())
        if row.get("kind") == "train":
            old[str(path.relative_to(ROOT))] = row["seeds"]
    if set(plan["train_seeds"]) & {seed for seeds in old.values() for seed in seeds}:
        raise ValueError("proposed new training seeds already used")
    release = {
        "released": True,
        "image_id": IMAGE,
        "spec_hash": SPEC,
        "environment_spec": spec,
        "lab_handoff_sha256": hashlib.sha256(handoff.read_bytes()).hexdigest(),
        "verified_raw_smoke_sha256": hashes,
        "prior_train_seed_inventory": old,
        "limitations": "late packet counts unavailable; ICMP RTT only; no safety authorization",
    }
    output = ROOT / "artifacts" / "adr014-release.json"
    if output.exists():
        raise ValueError("release snapshot already exists; never overwrite")
    atomicWrite(output, jsonBytes(release))
    print(
        jsonBytes(
            {
                "release": str(output),
                "image_id": IMAGE,
                "spec_hash": SPEC,
                "verified_raw_windows": len(hashes),
                "new_seeds_unused": True,
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
