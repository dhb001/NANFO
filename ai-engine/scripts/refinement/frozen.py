"""Read-only ADR014 runtime import under a distinct package identity.

The original loader checks its own copied source, original metadata, runtime and
restricted tensors. No source check is disabled and no old observations are used.
"""

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "artifacts/adr014-001"
HOLDOUT = ROOT / "artifacts/adr014-holdout-001"
PARENT_HASH = "5b8818af655ec8efce5d3bc3def27db599f3e0df379a0ae263dcefb5f72a80a5"
ALIAS = "_nanfo_adr014_frozen"


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def module(name):
    if ALIAS not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            ALIAS,
            ORIGINAL / "source/__init__.py",
            submodule_search_locations=[str(ORIGINAL / "source")],
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[ALIAS] = package
        spec.loader.exec_module(package)
    return importlib.import_module(f"{ALIAS}.{name}")


def incumbent():
    artifacts = module("artifacts")
    plan = artifacts.parseJson((HOLDOUT / "plan.json").read_bytes())
    original = artifacts.parseJson((ORIGINAL / "plan.json").read_bytes())
    if artifacts.clientSources() != original["client_source_sha256"]:
        raise ValueError("original copied source no longer matches frozen plan")
    path = Path(plan["checkpoint_path"])
    if not path.resolve().is_relative_to(ORIGINAL) or digest(path) != PARENT_HASH:
        raise ValueError("incumbent checkpoint identity differs")
    agent, metadata = artifacts.loadCheckpoint(path)
    if metadata.client_source_files != original["client_source_sha256"]:
        raise ValueError("incumbent metadata/source mismatch")
    if metadata.environment_spec["version"] != 4 or metadata.contract["state_dim"] != 16:
        raise ValueError("incumbent is not the declared V4 16-feature model")
    return agent, metadata, path
