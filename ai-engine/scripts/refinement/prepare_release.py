"""Pin the lab owner's published completed release after independent raw replay."""

import subprocess

from campaign import OUTPUT, read, release, write
from frozen import ROOT, digest
from inspect_release import inspect

DIRECTORY = ROOT.parent / "emulation/output/adr015-smoke-8e424505-cc49-40bb-afae-ee91d5045028"
IMAGE = "sha256:31c749ef79621fc15e959991f04ab5884f2cb3a16924ad3fc522f74edd3f48d9"


def main():
    if OUTPUT.exists():
        raise ValueError("campaign already frozen")
    if (
        digest(DIRECTORY / "summary.json")
        != "fce560ea5237fb63b0610fdd78292d04c09675fc5ccf592cfb11d12c79178386"
    ):
        raise ValueError("published lab summary identity mismatch")
    if (
        digest(DIRECTORY / "plan.json")
        != "f45b7abadd5c95e3dc2987af1aefbb2cfc3b27bc761dae92717c7b29374698aa"
    ):
        raise ValueError("published instrumentation plan identity mismatch")
    summary, plan = read(DIRECTORY / "summary.json"), read(DIRECTORY / "plan.json")
    if (
        summary["passed"] is not True
        or summary["cleanup_verified"] is not True
        or len(summary["windows"]) != 54
        or summary["image_id"] != IMAGE
    ):
        raise ValueError("lab owner did not complete release")
    for name, sha in summary["artifact_sha256"].items():
        if "/" in name or digest(DIRECTORY / name) != sha:
            raise ValueError("lab instrumentation inventory differs")
    replay = inspect(DIRECTORY)
    if replay["valid_windows"] != 48 or replay["failures"] or len(replay["profiles"]) != 16:
        raise ValueError("independent V5 raw replay failed")
    image = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout.strip()
    if image != IMAGE:
        raise ValueError("released image not available locally")
    target = ROOT / "artifacts/adr015-release.json"
    if target.exists():
        raise ValueError("release already pinned; do not overwrite")
    write(
        target,
        {
            "released": True,
            "image_id": IMAGE,
            "spec_hash": plan["spec_hash"],
            "environment_spec": plan["environment_spec"],
            "lab_owner_handoff": "emulation/REFINEMENT-V5.md:Validated Release",
            "smoke_summary_sha256": digest(DIRECTORY / "summary.json"),
            "smoke_plan_sha256": digest(DIRECTORY / "plan.json"),
            "independent_raw_validation": replay,
        },
    )
    release(target)
    target.chmod(0o400)
    print(str(target))


if __name__ == "__main__":
    main()
